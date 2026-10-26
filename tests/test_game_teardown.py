"""Tests for game teardown and scoring idempotency.

Production hit `ValueError: list.remove(x): x not in list` in `_remove_game` because removal was an
identity match on a list that `_load_games()` rebuilds wholesale on every gateway reconnect, and
because nothing stopped `_finish_game` from running twice for one game. The second path is the more
damaging one: it awarded a full set of points before the exception surfaced.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import discord
import pytest

from sixMans.enums import GameState, Winner
from sixMans.game import Game
from sixMans.queue import SixMansQueue
from sixMans.scoreboard.scoreboard import Scoreboard
from sixMans.sixMans import SixMans

from .scoreboard_env import make_config


def make_guild(guild_id=1):
    guild = MagicMock(spec=discord.Guild)
    guild.id = guild_id
    guild.name = "Test Guild"
    guild.default_role = MagicMock(spec=discord.Role)
    return guild


def make_member(member_id, guild=None):
    member = MagicMock(spec=discord.Member)
    member.id = member_id
    member.display_name = f"Player{member_id}"
    member.mention = f"<@{member_id}>"
    member.guild = guild
    member.__eq__ = lambda self, other: getattr(other, "id", None) == self.id  # ty: ignore[invalid-assignment]
    member.__hash__ = lambda self: hash(self.id)  # ty: ignore[invalid-assignment]
    return member


def make_text_channel(channel_id=100):
    channel = MagicMock(spec=discord.TextChannel)
    channel.id = channel_id
    channel.name = "123 Test Queue 6 Mans"
    channel.send = AsyncMock()
    channel.delete = AsyncMock()
    return channel


def make_voice_channel(channel_id=200):
    vc = MagicMock(spec=discord.VoiceChannel)
    vc.id = channel_id
    vc.name = f"vc-{channel_id}"
    vc.members = []
    vc.delete = AsyncMock()
    return vc


@pytest.fixture
def guild():
    return make_guild()


@pytest.fixture
def players(guild):
    return [make_member(i, guild) for i in range(1, 7)]


@pytest.fixture
def queue(guild):
    """A real SixMansQueue, scored for real through the cog's Scoreboard."""
    channel = MagicMock(spec=discord.TextChannel)
    channel.send = AsyncMock()
    return SixMansQueue(
        name="Test Queue",
        guild=guild,
        channels=[channel],
        points={"Play": 1, "Win": 3},
        maxSize=6,
        id=555,
    )


@pytest.fixture
def cog(guild, queue, tmp_path):
    bot = MagicMock()
    bot.guilds = [guild]
    with patch("sixMans.sixMans.Config.get_conf") as mock_conf, patch("sixMans.sixMans.asyncio.create_task"):
        mock_conf.return_value.register_guild = MagicMock()
        cog = SixMans(bot)

    cog.config = MagicMock()
    cog.queues = {guild: [queue]}
    cog.games = {guild: []}
    cog.queues_enabled = {guild: True}
    cog._save_games = AsyncMock()
    cog.scoreboard = Scoreboard(make_config(tmp_path))
    cog._save_queues = AsyncMock()
    cog._helper_role = AsyncMock(return_value=None)
    cog._get_automove = AsyncMock(return_value=False)
    cog._get_q_lobby_vc = AsyncMock(return_value=None)
    cog._category = AsyncMock(return_value=None)
    return cog


def build_game(queue, players, game_id=42, state=GameState.ONGOING):
    """A real Game so `.id`, `.abort()` and the lack of `__eq__` behave as in production."""
    return Game(
        queue=queue,
        players=players,
        blue=players[:3],
        orange=players[3:],
        captains=[players[0], players[3]],
        id=game_id,
        state=state,
        text_channel=make_text_channel(),
        voice_channels=[make_voice_channel(201), make_voice_channel(202)],
    )


# ---------------------------------------------------------------------------
# _remove_game
# ---------------------------------------------------------------------------


class TestRemoveGame:
    """`Game` has no `__eq__`, so removal must key on `game.id`, not object identity."""

    async def test_removes_reloaded_game_with_same_id(self, cog, guild, queue, players):
        """The production traceback: the caller holds a pre-reload object.

        `_load_games()` rebuilt the guild's games while a score report prompt was open, so the
        object the command captured is no longer in the list. `list.remove()` raised; matching on
        id removes the live entry instead.
        """
        live = build_game(queue, players, game_id=42)
        cog.games[guild] = [live]

        # Same game, rebuilt by _load_games() while the command was awaiting its view
        stale = build_game(queue, players, game_id=42)
        assert stale is not live
        assert stale != live  # no __eq__: identity only

        with patch("sixMans.sixMans.asyncio.sleep", new=AsyncMock()):
            await cog._remove_game(guild, stale)

        assert cog.games[guild] == []
        cog._save_games.assert_awaited_once_with(guild, [])

    async def test_tears_down_live_objects_channels(self, cog, guild, queue, players):
        live = build_game(queue, players, game_id=42)
        live_channel = live.textChannel
        cog.games[guild] = [live]

        stale = build_game(queue, players, game_id=42)

        with patch("sixMans.sixMans.asyncio.sleep", new=AsyncMock()):
            await cog._remove_game(guild, stale)

        live_channel.delete.assert_awaited_once()
        assert live.textChannel is None
        assert live.voiceChannels == []

    async def test_second_removal_is_a_noop(self, cog, guild, queue, players):
        """A double report must not run the 30s sleep and channel deletes twice."""
        game = build_game(queue, players, game_id=42)
        cog.games[guild] = [game]
        channel = game.textChannel

        with patch("sixMans.sixMans.asyncio.sleep", new=AsyncMock()):
            await cog._remove_game(guild, game)
            await cog._remove_game(guild, game)

        channel.delete.assert_awaited_once()
        assert cog._save_games.await_count == 1

    async def test_unknown_guild_does_not_raise(self, cog, queue, players):
        """A guild with no entry in `self.games` used to KeyError."""
        other_guild = make_guild(guild_id=99)
        game = build_game(queue, players, game_id=42)

        with patch("sixMans.sixMans.asyncio.sleep", new=AsyncMock()):
            await cog._remove_game(other_guild, game)

        cog._save_games.assert_not_awaited()


# ---------------------------------------------------------------------------
# _finish_game
# ---------------------------------------------------------------------------


class TestFinishGame:
    """Scoring inserts rows and bumps counters, so it must run at most once per game."""

    async def test_refuses_when_game_is_no_longer_active(self, cog, guild, queue, players):
        game = build_game(queue, players, game_id=42)
        cog.games[guild] = []  # already removed by a cancel or a competing report

        await cog._finish_game(guild, game, queue, Winner.BLUE)

        assert await cog.scoreboard.scores(guild) == []
        assert await cog.scoreboard.games_played(guild) == 0
        assert cog.scoreboard.queue_games_played(guild, queue.id) == 0

    async def test_awards_points_exactly_once(self, cog, guild, queue, players):
        """Two captains each opening a report prompt used to double credit everyone."""
        game = build_game(queue, players, game_id=42)
        cog.games[guild] = [game]

        with patch("sixMans.sixMans.asyncio.sleep", new=AsyncMock()):
            await cog._finish_game(guild, game, queue, Winner.BLUE)
            await cog._finish_game(guild, game, queue, Winner.BLUE)

        assert cog.scoreboard.queue_games_played(guild, queue.id) == 1
        assert await cog.scoreboard.games_played(guild) == 1
        # One score row per player, not two
        assert len(await cog.scoreboard.scores(guild)) == len(players)

    async def test_scores_the_live_object_after_a_reload(self, cog, guild, queue, players):
        live = build_game(queue, players, game_id=42)
        cog.games[guild] = [live]
        stale = build_game(queue, players, game_id=42)

        with patch("sixMans.sixMans.asyncio.sleep", new=AsyncMock()):
            await cog._finish_game(guild, stale, queue, Winner.ORANGE)

        assert cog.scoreboard.queue_games_played(guild, queue.id) == 1
        assert cog.games[guild] == []

    async def test_uses_the_live_queue_object_after_a_reload(self, cog, guild, players):
        """`_load_queues()` rebuilds queues too, so a held object can have stale settings like points."""
        stale_queue = SixMansQueue(
            name="Test Queue",
            guild=guild,
            channels=[MagicMock(spec=discord.TextChannel)],
            points={"Play": 100, "Win": 300},
            maxSize=6,
            id=555,
        )
        live_queue = cog.queues[guild][0]
        assert live_queue.id == stale_queue.id

        game = build_game(live_queue, players, game_id=42)
        cog.games[guild] = [game]

        with patch("sixMans.sixMans.asyncio.sleep", new=AsyncMock()):
            await cog._finish_game(guild, game, stale_queue, Winner.BLUE)

        assert cog.scoreboard.queue_games_played(guild, live_queue.id) == 1
        # Winners get the live queue's 1 + 3 points, not the stale 100 + 300
        assert {s["Points"] for s in await cog.scoreboard.scores(guild)} == {1, 4}


# ---------------------------------------------------------------------------
# revalidate_game
# ---------------------------------------------------------------------------


class TestRevalidateGame:
    async def test_returns_live_object_for_a_stale_reference(self, cog, guild, queue, players):
        live = build_game(queue, players, game_id=42)
        cog.games[guild] = [live]
        stale = build_game(queue, players, game_id=42)

        assert cog.revalidate_game(guild, stale) is live

    async def test_returns_none_when_removed(self, cog, guild, queue, players):
        game = build_game(queue, players, game_id=42)
        cog.games[guild] = []

        assert cog.revalidate_game(guild, game) is None

    @pytest.mark.parametrize("state", [GameState.COMPLETE, GameState.CANCELLED])
    async def test_returns_none_when_already_finished(self, cog, guild, queue, players, state):
        game = build_game(queue, players, game_id=42, state=state)
        cog.games[guild] = [game]

        assert cog.revalidate_game(guild, game) is None


# ---------------------------------------------------------------------------
# _load_games
# ---------------------------------------------------------------------------


class TestLoadGamesPreservesObjects:
    """`on_ready` fires on every reconnect. Rebuilding games orphans in-flight references."""

    async def test_existing_game_object_is_reused(self, cog, guild, queue, players):
        game = build_game(queue, players, game_id=42)
        cog.games[guild] = [game]

        guild.get_member = MagicMock(side_effect=lambda pid: next((p for p in players if p.id == pid), None))
        guild.get_channel = MagicMock(side_effect=lambda cid: game.textChannel if cid == game.textChannel.id else None)
        cog._games = AsyncMock(return_value={str(game.id): game._to_dict()})

        spawn = MagicMock()
        cog._spawn_game_task = spawn

        await cog._load_games()

        assert len(cog.games[guild]) == 1
        assert cog.games[guild][0] is game
        # No duplicate selection/info task for a game that already has one in flight
        spawn.assert_not_called()
