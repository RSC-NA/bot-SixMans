"""Per-queue stats stored in the Scoreboard: migration, recording, deletion, and rollback safety."""

import copy
import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from sixMans.enums import GameState, Winner
from sixMans.game import Game
from sixMans.models.queue import QueueData
from sixMans.queue import SixMansQueue
from sixMans.scoreboard.scoreboard import SCHEMA_VERSION, Scoreboard

from .scoreboard_env import DUELS, EMPTY, GENERAL, build_cog, make_config, make_guild, make_member, scenario
from .test_game_teardown import make_text_channel, make_voice_channel


@pytest.fixture
def guild():
    return make_guild()


@pytest.fixture
def data():
    return scenario()


@pytest.fixture
def config(tmp_path):
    return make_config(tmp_path)


@pytest.fixture
def settings_path(tmp_path):
    return tmp_path / "settings.json"


@pytest.fixture
async def cog(config, guild, data):
    return await build_cog(config, guild, data)


def saved(settings_path, guild) -> dict:
    return json.loads(settings_path.read_text())["1234567896"]["GUILD"][str(guild.id)]


async def finish_game(cog, guild, queue_id, player_ids, winner=Winner.BLUE):
    queue = next(q for q in cog.queues[guild] if q.id == queue_id)
    players = [make_member(i, guild) for i in player_ids]
    half = len(players) // 2
    game = Game(
        queue=queue,
        players=players,
        blue=players[:half],
        orange=players[half:],
        captains=[players[0], players[half]],
        id=hash(tuple(player_ids)),
        state=GameState.ONGOING,
        text_channel=make_text_channel(),
        voice_channels=[make_voice_channel(201), make_voice_channel(202)],
    )
    cog.games[guild] = [game]
    cog._remove_game = AsyncMock()
    await cog._finish_game(guild, game, queue, winner)


class TestMigration:
    @pytest.mark.usefixtures("cog")
    async def test_copies_every_queues_stats_exactly(self, guild, data, settings_path):
        stats = saved(settings_path, guild)["QueueStats"]

        assert set(stats) == set(data["Queues"])
        for queue_id, queue in data["Queues"].items():
            assert stats[queue_id] == {"Name": queue["Name"], "Deleted": False, "GamesPlayed": queue["GamesPlayed"], "Players": queue["Players"]}
        assert saved(settings_path, guild)["ScoreboardSchema"] == SCHEMA_VERSION

    @pytest.mark.usefixtures("cog")
    async def test_leaves_saved_queues_untouched(self, guild, data, settings_path):
        assert saved(settings_path, guild)["Queues"] == json.loads(json.dumps(data["Queues"]))

    async def test_runs_only_once(self, cog, config, guild, settings_path):
        # Simulate old code writing to the frozen fields after a rollback and roll-forward
        queues = await config.guild(guild).Queues()
        queues[str(GENERAL)]["Players"] = {}
        queues[str(GENERAL)]["GamesPlayed"] = 0
        await config.guild(guild).Queues.set(queues)
        before = saved(settings_path, guild)["QueueStats"]

        await cog.cog_load()

        assert saved(settings_path, guild)["QueueStats"] == before
        assert cog.scoreboard.queue_games_played(guild, GENERAL) == 37

    async def test_already_migrated_guild_is_not_refilled_from_frozen_fields(self, config, guild, data, settings_path):
        data["ScoreboardSchema"] = SCHEMA_VERSION
        data["QueueStats"] = {}

        cog = await build_cog(config, guild, data)

        assert saved(settings_path, guild)["QueueStats"] == {}
        assert cog.scoreboard.queue_games_played(guild, GENERAL) == 0

    async def test_keeps_entries_from_an_interrupted_migration(self, config, guild, data, settings_path):
        partial = {str(GENERAL): {"Name": "General", "Deleted": False, "GamesPlayed": 99, "Players": {"1": {"Points": 1, "Wins": 0, "GamesPlayed": 1}}}}
        data["QueueStats"] = partial

        await build_cog(config, guild, data)

        stats = saved(settings_path, guild)["QueueStats"]
        assert stats[str(GENERAL)] == partial[str(GENERAL)]
        assert stats[str(DUELS)]["GamesPlayed"] == 5

    async def test_guild_with_no_queues(self, config, guild, settings_path):
        cog = await build_cog(config, guild, {})

        assert saved(settings_path, guild)["QueueStats"] == {}
        assert saved(settings_path, guild)["ScoreboardSchema"] == SCHEMA_VERSION
        assert cog.scoreboard.queue_players(guild, GENERAL) == {}


class TestRecording:
    async def test_game_updates_queue_stats_not_the_frozen_queue_fields(self, cog, guild, settings_path):
        queues_before = saved(settings_path, guild)["Queues"]

        await finish_game(cog, guild, GENERAL, [1, 2, 3, 4, 5, 6])

        after = saved(settings_path, guild)
        assert after["Queues"] == queues_before
        assert after["QueueStats"][str(GENERAL)]["GamesPlayed"] == 38
        assert after["QueueStats"][str(GENERAL)]["Players"]["1"] == {"Points": 31, "Wins": 12, "GamesPlayed": 20}
        assert after["QueueStats"][str(GENERAL)]["Players"]["4"] == {"Points": 23, "Wins": 8, "GamesPlayed": 17}
        assert after["GamesPlayed"] == 43
        assert after["Players"]["1"] == {"Points": 41, "Wins": 15, "GamesPlayed": 30}

    async def test_in_memory_stats_match_disk_after_reload(self, cog, guild):
        await finish_game(cog, guild, DUELS, [1, 2])
        in_memory = copy.deepcopy(cog.scoreboard.queue_players(guild, DUELS))

        await cog.cog_load()

        assert cog.scoreboard.queue_players(guild, DUELS) == in_memory
        assert cog.scoreboard.queue_games_played(guild, DUELS) == 6

    async def test_queue_added_after_migration_gets_stats_on_first_game(self, cog, guild, settings_path):
        channel = guild.get_channel(30)
        await cog.removeQueue.callback(cog, MagicMock(guild=guild, send=AsyncMock()), queue_name="Empty")
        ctx = MagicMock(guild=guild, send=AsyncMock())
        await cog.addNewQueue.callback(cog, ctx, "Fresh", 1, 2, channel)
        fresh = next(q for q in cog.queues[guild] if q.name == "Fresh")

        await finish_game(cog, guild, fresh.id, [1, 2, 3, 4, 5, 6])

        stats = saved(settings_path, guild)["QueueStats"][str(fresh.id)]
        assert stats["Name"] == "Fresh"
        assert stats["GamesPlayed"] == 1
        assert stats["Players"]["1"] == {"Points": 3, "Wins": 1, "GamesPlayed": 1}
        # Old code requires these in every saved queue, so new queues get empty ones
        queue = saved(settings_path, guild)["Queues"][str(fresh.id)]
        assert queue["Players"] == {}
        assert queue["GamesPlayed"] == 0


class TestDeletedQueues:
    async def test_removing_a_queue_keeps_its_stats_flagged_deleted(self, cog, guild, data, settings_path):
        await cog.removeQueue.callback(cog, MagicMock(guild=guild, send=AsyncMock()), queue_name="Duels")

        after = saved(settings_path, guild)
        assert str(DUELS) not in after["Queues"]
        assert after["QueueStats"][str(DUELS)] == {"Name": "Duels", "Deleted": True, "GamesPlayed": 5, "Players": data["Queues"][str(DUELS)]["Players"]}
        assert after["QueueStats"][str(GENERAL)]["Deleted"] is False

    async def test_deleted_queue_is_recorded_under_its_final_name(self, cog, guild, settings_path):
        ctx = MagicMock(guild=guild, send=AsyncMock())
        await cog.editQueue.callback(cog, ctx, "Duels", "1v1", 1, 1, guild.get_channel(20))
        await finish_game(cog, guild, DUELS, [1, 2])

        await cog.removeQueue.callback(cog, ctx, queue_name="1v1")

        stats = saved(settings_path, guild)["QueueStats"][str(DUELS)]
        assert stats["Name"] == "1v1"
        assert stats["Deleted"] is True

    async def test_deleted_queues_are_not_rebuilt(self, cog, guild):
        await cog.removeQueue.callback(cog, MagicMock(guild=guild, send=AsyncMock()), queue_name="Duels")

        record = await cog._rebuild_player_totals(guild, apply=False)

        assert str(DUELS) not in record["queues"]

    async def test_clearing_all_data_clears_queue_stats(self, cog, guild, settings_path):
        await cog._clear_all_data(guild)

        assert saved(settings_path, guild)["QueueStats"] == {}
        assert cog.scoreboard.queue_players(guild, GENERAL) == {}


class TestRollback:
    async def test_saving_queues_keeps_the_frozen_stats(self, cog, guild, data, settings_path):
        """Any queue admin command rewrites every saved queue. The frozen stats must survive that."""
        await finish_game(cog, guild, GENERAL, [1, 2, 3, 4, 5, 6])
        ctx = MagicMock(guild=guild, send=AsyncMock())

        await cog.editQueue.callback(cog, ctx, "General", "General", 1, 2, guild.get_channel(10))

        for queue_id, queue in saved(settings_path, guild)["Queues"].items():
            assert queue["Players"] == data["Queues"][queue_id]["Players"]
            assert queue["GamesPlayed"] == data["Queues"][queue_id]["GamesPlayed"]

    async def test_pre_scoreboard_code_can_still_load_saved_queues(self, cog, guild, settings_path):
        """Code from before the move parses every saved queue with QueueData, which requires these fields."""
        await finish_game(cog, guild, GENERAL, [1, 2, 3, 4, 5, 6])
        await cog.removeQueue.callback(cog, MagicMock(guild=guild, send=AsyncMock()), queue_name="Empty")

        for queue in saved(settings_path, guild)["Queues"].values():
            parsed = QueueData(**queue)
            assert parsed.GamesPlayed >= 0
            assert isinstance(parsed.Players.model_dump(), dict)
        assert str(EMPTY) not in saved(settings_path, guild)["Queues"]


class TestUnloadedGuild:
    async def test_writes_for_a_guild_missed_at_startup_keep_its_stats(self, config, guild, data, settings_path):
        """A fresh Scoreboard has nothing cached for the guild. Saving must not replace what's on disk."""
        await build_cog(config, guild, data)
        scoreboard = Scoreboard(config)
        queue = SixMansQueue("General", guild, [], {"Play": 1, "Win": 2}, 6, id=GENERAL)

        await scoreboard.record_game(guild, queue, 1, [make_member(1)], [make_member(2)])

        stats = saved(settings_path, guild)["QueueStats"]
        assert set(stats) == set(data["Queues"])
        assert stats[str(DUELS)]["GamesPlayed"] == 5
        assert stats[str(GENERAL)]["GamesPlayed"] == 38
        assert stats[str(GENERAL)]["Players"]["3"] == data["Queues"][str(GENERAL)]["Players"]["3"]

    async def test_first_write_migrates_an_unmigrated_guild(self, config, guild, data, settings_path):
        for key, value in data.items():
            await config.guild(guild).get_attr(key).set(value)
        scoreboard = Scoreboard(config)
        queue = SixMansQueue("Duels", guild, [], {"Play": 1, "Win": 1}, 2, id=DUELS)

        await scoreboard.mark_queue_deleted(guild, queue)

        stats = saved(settings_path, guild)["QueueStats"]
        assert stats[str(GENERAL)]["GamesPlayed"] == 37
        assert stats[str(DUELS)]["Deleted"] is True
        assert saved(settings_path, guild)["ScoreboardSchema"] == SCHEMA_VERSION

    async def test_rebuild_for_a_guild_missed_at_startup_keeps_its_stats(self, config, guild, data, settings_path):
        await build_cog(config, guild, data)
        scoreboard = Scoreboard(config)
        general = SixMansQueue("General", guild, [], {"Play": 1, "Win": 2}, 6, id=GENERAL)

        await scoreboard.rebuild_totals(guild, [general], apply=True)

        stats = saved(settings_path, guild)["QueueStats"]
        assert stats[str(DUELS)] == {"Name": "Duels", "Deleted": False, "GamesPlayed": 5, "Players": data["Queues"][str(DUELS)]["Players"]}
        assert stats[str(GENERAL)]["GamesPlayed"] == 37
