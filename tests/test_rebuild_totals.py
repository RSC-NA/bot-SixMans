"""Tests for rebuilding player totals lost to commit 78be65a (`rebuildPlayerTotals`).

The integration tests run against Red's real JSON config backend and read the result back from disk,
so they cover what is actually persisted, not just what a mock was called with.
"""

import asyncio
import copy
import datetime
import json
import random
import uuid
from typing import cast
from unittest.mock import AsyncMock, MagicMock, patch

import discord
import pytest
from redbot.core import Config
from redbot.core._drivers.json import JsonDriver

from sixMans.enums import Winner
from sixMans.scoreboard.stats import TOTALS_BUG_INTRODUCED, give_points, plan_totals_rebuild, sort_players
from sixMans.sixMans import SixMans, defaults
from sixMans.types import PlayerScore, PlayerStats
from sixMans.utils import format_score_time, parse_score_time

from .test_game_teardown import build_game, make_member

GENERAL = 111
LOWER = 222
BEFORE = -30  # Days relative to the bug
AFTER = 30


def at(days: float) -> str:
    return format_score_time(TOTALS_BUG_INTRODUCED + datetime.timedelta(days=days))


def score(player: int, days: float, win: int = 1, queue: int = GENERAL) -> PlayerScore:
    return PlayerScore(Game=1, Queue=queue, Player=player, Win=win, Points=3 if win else 1, DateTime=at(days))


def totals(points: int, wins: int, games: int) -> PlayerStats:
    return PlayerStats(Points=points, Wins=wins, GamesPlayed=games)


def newest_first(scores: list[PlayerScore]) -> list[PlayerScore]:
    return sorted(scores, key=lambda s: parse_score_time(s["DateTime"]), reverse=True)


# ---------------------------------------------------------------------------
# Planning: who gets rebuilt
# ---------------------------------------------------------------------------


class TestPlanTotalsRebuild:
    def test_missing_player_who_started_after_the_bug_is_added(self):
        scores = [score(1, AFTER + 1, win=0), score(1, AFTER)]
        assert plan_totals_rebuild({}, scores) == {"1": totals(4, 1, 2)}

    def test_partial_totals_from_after_the_fix_are_replaced(self):
        """A player missed by the bug gets an entry for their first game after the fix, but nothing before it."""
        scores = [score(1, AFTER + 2), score(1, AFTER + 1, win=0), score(1, AFTER)]
        assert plan_totals_rebuild({"1": totals(3, 1, 1)}, scores) == {"1": totals(7, 2, 3)}

    def test_player_who_started_before_the_bug_is_never_touched(self):
        """Stored totals already disagree with history for older players. Those aren't ours to change."""
        scores = [score(1, AFTER), score(1, BEFORE), score(2, AFTER), score(2, BEFORE)]
        stored = {"1": totals(3, 1, 1)}  # Fewer games than history, and player 2 is missing entirely
        assert plan_totals_rebuild(stored, scores) == {}

    @pytest.mark.parametrize("stored", [totals(3, 1, 1), totals(50, 20, 30), totals(0, 0, 1)])
    def test_never_lowers_or_rewrites_totals_with_as_many_games(self, stored):
        scores = [score(1, AFTER)]
        assert plan_totals_rebuild({"1": stored}, scores) == {}

    def test_first_game_exactly_at_the_cutoff_counts_as_after(self):
        scores = [score(1, 0)]
        assert plan_totals_rebuild({}, scores) == {"1": totals(3, 1, 1)}

    def test_first_game_just_before_the_cutoff_counts_as_before(self):
        scores = [score(1, -1 / 86400)]
        assert plan_totals_rebuild({}, scores) == {}

    def test_first_game_does_not_depend_on_score_order(self):
        scores = [score(1, BEFORE), score(1, AFTER), score(2, AFTER), score(2, AFTER + 1)]
        for _ in range(10):
            random.shuffle(scores)
            assert plan_totals_rebuild({}, scores) == {"2": totals(6, 2, 2)}

    def test_queue_scope_only_counts_that_queues_games(self):
        """An established General player who first tried Lower after the bug is missing from Lower only."""
        scores = [score(1, AFTER, queue=LOWER), score(1, AFTER, queue=GENERAL), score(1, BEFORE, queue=GENERAL)]

        assert plan_totals_rebuild({}, scores, LOWER) == {"1": totals(3, 1, 1)}
        assert plan_totals_rebuild({}, scores, GENERAL) == {}
        assert plan_totals_rebuild({}, scores) == {}

    def test_scores_from_before_game_ids_were_recorded(self):
        legacy = cast(PlayerScore, {k: v for k, v in score(1, AFTER).items() if k != "Game"})
        assert plan_totals_rebuild({}, [legacy]) == {"1": totals(3, 1, 1)}

    def test_does_not_modify_its_inputs(self):
        scores = [score(1, AFTER), score(2, AFTER)]
        stored = {"2": totals(3, 1, 1)}
        scores_before, stored_before = copy.deepcopy(scores), copy.deepcopy(stored)

        plan_totals_rebuild(stored, scores)

        assert scores == scores_before
        assert stored == stored_before


# ---------------------------------------------------------------------------
# Applying against Red's real config backend
# ---------------------------------------------------------------------------


def make_channel(channel_id: int):
    channel = MagicMock(spec=discord.TextChannel)
    channel.id = channel_id
    channel.send = AsyncMock()
    channel.delete = AsyncMock()
    return channel


@pytest.fixture
def guild():
    guild = MagicMock(spec=discord.Guild)
    guild.id = 395806681994493964
    guild.name = "Test Guild"
    channels = {10: make_channel(10), 20: make_channel(20)}
    guild.get_channel = lambda channel_id: channels.get(channel_id)
    return guild


@pytest.fixture
def settings_path(tmp_path):
    return tmp_path / "settings.json"


@pytest.fixture
def config(tmp_path):
    # Red shares JSON data between drivers by cog name, so each test gets its own
    driver = JsonDriver(f"SixMansTest{uuid.uuid4().hex}", "1234567896", data_path_override=tmp_path)
    conf = Config(cog_name=driver.cog_name, unique_identifier="1234567896", driver=driver, force_registration=True)
    conf.register_guild(**defaults)
    return conf


@pytest.fixture
def history():
    """Newest first, as stored. Times are relative to the bug."""
    return newest_first(
        [
            # 1: established before the bug, history agrees with stored totals
            score(1, BEFORE),
            score(1, AFTER, win=0),
            # 2: established before the bug, stored totals already disagree with history (left alone)
            score(2, BEFORE),
            score(2, BEFORE + 1),
            score(2, AFTER),
            # 3: started after the bug, never recorded
            score(3, AFTER),
            score(3, AFTER + 1, win=0),
            # 4: started after the bug, recorded once after the fix shipped
            score(4, AFTER),
            score(4, AFTER + 1),
            score(4, AFTER + 2, win=0),
            # 1 again: established in General, first tried Lower after the bug
            score(1, AFTER + 3, queue=LOWER),
            # 5: started after the bug in a queue that has since been deleted
            score(5, AFTER, queue=999),
        ]
    )


@pytest.fixture
def stored_players():
    return {
        "1": totals(4, 1, 2),
        "2": totals(5, 2, 2),
        "4": totals(1, 0, 1),
        "6": totals(30, 10, 20),  # Has no scores at all (e.g. from before scores were kept)
    }


@pytest.fixture
def stored_queues():
    def queue(name, channel_id, players, games_played):
        return {"Name": name, "Channels": [channel_id], "Points": {"Play": 1, "Win": 2}, "Players": players, "GamesPlayed": games_played, "TeamSelection": "Vote", "MaxSize": 6}

    return {
        str(GENERAL): queue("General", 10, {"1": totals(4, 1, 2), "2": totals(5, 2, 2), "4": totals(1, 0, 1)}, 400),
        str(LOWER): queue("Lower", 20, {"7": totals(3, 1, 1)}, 12),
    }


@pytest.fixture
async def cog(config, guild, history, stored_players, stored_queues):
    bot = MagicMock()
    bot.guilds = [guild]
    with patch("sixMans.sixMans.Config.get_conf", return_value=config), patch("sixMans.sixMans.asyncio.create_task"):
        cog = SixMans(bot)

    await config.guild(guild).Scores.set(history)
    await config.guild(guild).Players.set(stored_players)
    await config.guild(guild).Queues.set(stored_queues)
    await config.guild(guild).GamesPlayed.set(1234)
    await cog.cog_load()
    return cog


def read_guild(settings_path, guild) -> dict:
    return json.loads(settings_path.read_text())["1234567896"]["GUILD"][str(guild.id)]


EXPECTED_SERVER_PLAYERS = {
    "1": totals(4, 1, 2),
    "2": totals(5, 2, 2),
    "3": totals(4, 1, 2),
    "4": totals(7, 2, 3),
    "5": totals(3, 1, 1),
    "6": totals(30, 10, 20),
}
EXPECTED_GENERAL_PLAYERS = {"1": totals(4, 1, 2), "2": totals(5, 2, 2), "3": totals(4, 1, 2), "4": totals(7, 2, 3)}
EXPECTED_LOWER_PLAYERS = {"1": totals(3, 1, 1), "7": totals(3, 1, 1)}


class TestRebuildPlayerTotals:
    async def test_preview_changes_nothing(self, cog, guild, settings_path):
        on_disk = settings_path.read_bytes()
        in_memory = {q.id: copy.deepcopy(cog.scoreboard.queue_players(guild, q.id)) for q in cog.queues[guild]}

        record = await cog._rebuild_player_totals(guild, apply=False)

        assert set(record["server"]) == {"3", "4", "5"}
        assert settings_path.read_bytes() == on_disk
        assert {q.id: cog.scoreboard.queue_players(guild, q.id) for q in cog.queues[guild]} == in_memory

    async def test_applies_exactly_the_expected_changes_to_disk(self, cog, guild, settings_path):
        await cog._rebuild_player_totals(guild, apply=True)
        saved = read_guild(settings_path, guild)

        assert saved["Players"] == EXPECTED_SERVER_PLAYERS
        assert saved["QueueStats"][str(GENERAL)]["Players"] == EXPECTED_GENERAL_PLAYERS
        assert saved["QueueStats"][str(LOWER)]["Players"] == EXPECTED_LOWER_PLAYERS

    async def test_leaves_everything_else_identical(self, cog, guild, settings_path, history):
        before = read_guild(settings_path, guild)

        await cog._rebuild_player_totals(guild, apply=True)
        after = read_guild(settings_path, guild)

        assert after["Scores"] == before["Scores"] == json.loads(json.dumps(history))
        assert after["GamesPlayed"] == before["GamesPlayed"] == 1234
        assert after["Queues"] == before["Queues"]
        for queue_id, queue in before["QueueStats"].items():
            assert {k: v for k, v in after["QueueStats"][queue_id].items() if k != "Players"} == {k: v for k, v in queue.items() if k != "Players"}
        assert after["QueueStats"][str(GENERAL)]["GamesPlayed"] == 400
        assert after["QueueStats"][str(LOWER)]["GamesPlayed"] == 12
        assert set(after) == set(before)

    async def test_record_has_before_and_after_for_every_change(self, cog, guild):
        record = await cog._rebuild_player_totals(guild, apply=True)

        assert record == {
            "server": {
                "3": {"before": None, "after": totals(4, 1, 2)},
                "4": {"before": totals(1, 0, 1), "after": totals(7, 2, 3)},
                "5": {"before": None, "after": totals(3, 1, 1)},
            },
            "queues": {
                str(GENERAL): {
                    "name": "General",
                    "players": {
                        "3": {"before": None, "after": totals(4, 1, 2)},
                        "4": {"before": {"GamesPlayed": 1, "Points": 1, "Wins": 0}, "after": totals(7, 2, 3)},
                    },
                },
                str(LOWER): {"name": "Lower", "players": {"1": {"before": None, "after": totals(3, 1, 1)}}},
            },
        }

    async def test_record_is_not_changed_by_later_games(self, cog, guild):
        record = await cog._rebuild_player_totals(guild, apply=True)
        snapshot = copy.deepcopy(record)

        give_points(cog.scoreboard.queue_players(guild, GENERAL), score(4, AFTER + 5))

        assert record == snapshot

    async def test_survives_a_reload(self, cog, guild):
        await cog._rebuild_player_totals(guild, apply=True)

        await cog.cog_load()

        assert cog.scoreboard.queue_players(guild, GENERAL) == EXPECTED_GENERAL_PLAYERS
        assert cog.scoreboard.queue_players(guild, LOWER) == EXPECTED_LOWER_PLAYERS
        assert await cog.scoreboard.players(guild) == EXPECTED_SERVER_PLAYERS

    async def test_running_again_changes_nothing(self, cog, guild, settings_path):
        await cog._rebuild_player_totals(guild, apply=True)
        on_disk = settings_path.read_bytes()

        record = await cog._rebuild_player_totals(guild, apply=True)

        assert record == {"server": {}, "queues": {}}
        assert settings_path.read_bytes() == on_disk

    async def test_leaderboards_use_rebuilt_totals(self, cog, guild):
        await cog._rebuild_player_totals(guild, apply=True)

        sorted_players = sort_players(await cog.scoreboard.players(guild))

        assert [pid for pid, _ in sorted_players] == ["6", "4", "2", "1", "3", "5"]


class TestRebuildAlongsideGames:
    async def test_fixed_scoring_then_rebuild_gives_full_history(self, cog, guild):
        """Player 3 finishes a game under the fixed code before an admin runs the rebuild."""
        queue = next(q for q in cog.queues[guild] if q.id == GENERAL)
        members = [make_member(i, guild) for i in (3, 8, 9, 10, 11, 12)]
        game = build_game(queue, members, game_id=42)
        cog.games[guild] = [game]
        cog._save_games = AsyncMock()

        with patch("sixMans.sixMans.asyncio.sleep", new=AsyncMock()):
            await cog._finish_game(guild, game, queue, Winner.BLUE)

        # The fix records the new game, but only that game
        assert (await cog.scoreboard.players(guild))["3"] == totals(3, 1, 1)

        await cog._rebuild_player_totals(guild, apply=True)

        players = await cog.scoreboard.players(guild)
        assert players["3"] == totals(7, 2, 3)  # 2 earlier games plus the one just played
        assert cog.scoreboard.queue_player(guild, GENERAL, 3) == totals(7, 2, 3)
        # Brand new players are recorded by the fix itself and need nothing rebuilt
        for pid in ("8", "9"):
            assert players[pid] == cog.scoreboard.queue_players(guild, GENERAL)[pid] == totals(3, 1, 1)
        for pid in ("10", "11", "12"):
            assert players[pid] == cog.scoreboard.queue_players(guild, GENERAL)[pid] == totals(1, 0, 1)
        assert players["1"] == totals(4, 1, 2)
        assert players["6"] == totals(30, 10, 20)

    @pytest.mark.parametrize("game_first", [True, False])
    async def test_game_scored_mid_rebuild_is_not_lost(self, cog, guild, settings_path, game_first):
        """Pause whichever starts first halfway through its writes, then let the other run.

        Without the lock, the second one finishes in that gap and the first then saves totals it
        read beforehand, silently undoing the other's changes.
        """
        queue = next(q for q in cog.queues[guild] if q.id == GENERAL)
        game = build_game(queue, [make_member(i, guild) for i in (3, 8, 9, 10, 11, 12)], game_id=42)
        cog.games[guild] = [game]
        cog._remove_game = AsyncMock()

        paused, resume = asyncio.Event(), asyncio.Event()
        save_scores, save_players = cog.scoreboard._save_scores, cog.scoreboard._save_players

        async def pause_once(save, *args):
            if not paused.is_set():
                paused.set()
                await resume.wait()
            await save(*args)

        if game_first:
            cog.scoreboard._save_scores = lambda *args: pause_once(save_scores, *args)
            first = asyncio.create_task(cog._finish_game(guild, game, queue, Winner.BLUE))
        else:
            cog.scoreboard._save_players = lambda *args: pause_once(save_players, *args)
            first = asyncio.create_task(cog._rebuild_player_totals(guild, apply=True))
        await asyncio.wait_for(paused.wait(), 1)

        second = asyncio.create_task(cog._rebuild_player_totals(guild, apply=True) if game_first else cog._finish_game(guild, game, queue, Winner.BLUE))
        done, _ = await asyncio.wait({second}, timeout=0.2)
        assert not done, "Second writer ran while the first was mid-write"

        resume.set()
        await asyncio.wait_for(asyncio.gather(first, second), 1)

        saved = read_guild(settings_path, guild)
        assert saved["Players"]["3"] == saved["QueueStats"][str(GENERAL)]["Players"]["3"] == totals(7, 2, 3)
        assert saved["Players"]["4"] == saved["QueueStats"][str(GENERAL)]["Players"]["4"] == totals(7, 2, 3)
        assert saved["Players"]["8"] == totals(3, 1, 1)
        assert saved["Players"]["5"] == totals(3, 1, 1)
        assert len(saved["Scores"]) == 12 + 6
        assert saved["GamesPlayed"] == 1235


# ---------------------------------------------------------------------------
# The command
# ---------------------------------------------------------------------------


@pytest.fixture
def ctx(guild):
    ctx = MagicMock()
    ctx.guild = guild
    ctx.author = make_member(99, guild)
    ctx.send = AsyncMock()
    return ctx


def answer(ctx, yes: bool | None):
    """Make the confirmation prompt resolve as yes, no, or time out (None)."""

    async def wait_for(_event, check, **_kwargs):
        if yes is None:
            raise TimeoutError
        check.result = yes

    ctx.bot.wait_for = wait_for


async def run_command(cog, ctx):
    with patch("sixMans.scoreboard.commands.start_adding_reactions"), patch("sixMans.scoreboard.commands.ReactionPredicate.yes_or_no", return_value=MagicMock()):
        await cog.rebuildPlayerTotals.callback(cog, ctx)


class TestRebuildCommand:
    async def test_confirmed_rebuild_applies_and_attaches_the_changes(self, cog, ctx, guild, settings_path):
        answer(ctx, yes=True)

        await run_command(cog, ctx)

        assert read_guild(settings_path, guild)["Players"] == EXPECTED_SERVER_PLAYERS
        prompt = ctx.send.await_args_list[0].args[0]
        assert "**Server totals:** 2 added, 1 updated" in prompt
        assert "**General:** 1 added, 1 updated" in prompt
        assert "**Lower:** 1 added, 0 updated" in prompt
        done = ctx.send.await_args_list[-1]
        assert done.args[0].startswith("Done.")
        attached = json.loads(done.kwargs["file"].fp.read())
        assert attached["server"]["4"] == {"before": totals(1, 0, 1), "after": totals(7, 2, 3)}

    async def test_game_finished_while_confirming_is_kept(self, cog, ctx, guild, settings_path):
        """The preview is stale once a game finishes. Applying it would wipe out that game."""
        queue = next(q for q in cog.queues[guild] if q.id == GENERAL)
        game = build_game(queue, [make_member(i, guild) for i in (4, 8, 9, 10, 11, 12)], game_id=42)
        cog.games[guild] = [game]
        cog._remove_game = AsyncMock()

        async def wait_for(_event, check, **_kwargs):
            await cog._finish_game(guild, game, queue, Winner.BLUE)
            check.result = True

        ctx.bot.wait_for = wait_for

        await run_command(cog, ctx)

        saved = read_guild(settings_path, guild)
        assert saved["Players"]["4"] == saved["QueueStats"][str(GENERAL)]["Players"]["4"] == totals(10, 3, 4)
        attached = json.loads(ctx.send.await_args_list[-1].kwargs["file"].fp.read())
        assert attached["server"]["4"] == {"before": totals(4, 1, 2), "after": totals(10, 3, 4)}

    @pytest.mark.parametrize("yes", [False, None])
    async def test_declined_or_timed_out_changes_nothing(self, cog, ctx, settings_path, yes):
        on_disk = settings_path.read_bytes()
        answer(ctx, yes=yes)

        await run_command(cog, ctx)

        assert settings_path.read_bytes() == on_disk
        assert "**not** changed" in ctx.send.await_args_list[-1].args[0]

    async def test_nothing_to_rebuild_skips_the_prompt(self, cog, ctx):
        await cog._rebuild_player_totals(ctx.guild, apply=True)
        ctx.bot.wait_for = AsyncMock()

        await run_command(cog, ctx)

        ctx.bot.wait_for.assert_not_awaited()
        ctx.send.assert_awaited_once_with("No player totals need rebuilding.")
