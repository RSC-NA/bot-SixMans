"""Tests for queue popping and game channel creation.

Covers the failure modes around a queued player leaving the guild: Discord returns
404 Unknown Overwrite when granting channel permissions to a non-member, which used to
abort game creation and leave orphaned channels behind.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import discord
import pytest

from sixMans.game import Game
from sixMans.queue import SixMansQueue
from sixMans.sixMans import SixMans


def make_guild(guild_id=1):
    guild = MagicMock(spec=discord.Guild)
    guild.id = guild_id
    guild.name = "Test Guild"
    guild.default_role = MagicMock(spec=discord.Role)
    return guild


def make_member(member_id, guild=None, display_name=None):
    member = MagicMock(spec=discord.Member)
    member.id = member_id
    member.display_name = display_name or f"Player{member_id}"
    member.mention = f"<@{member_id}>"
    member.guild = guild
    member.send = AsyncMock()
    member.__eq__ = lambda self, other: getattr(other, "id", None) == self.id  # ty: ignore[invalid-assignment]
    member.__hash__ = lambda self: hash(self.id)  # ty: ignore[invalid-assignment]
    return member


def make_queue(guild, players=None, max_size=6):
    """A real SixMansQueue so peek/get/put ordering is exercised for real."""
    channel = MagicMock(spec=discord.TextChannel)
    channel.send = AsyncMock()
    q = SixMansQueue(
        name="Test Queue",
        guild=guild,
        channels=[channel],
        points={},
        maxSize=max_size,
    )
    for player in players or []:
        q._put(player)
    return q


@pytest.fixture
def guild():
    return make_guild()


@pytest.fixture
def players(guild):
    return [make_member(i, guild) for i in range(1, 7)]


@pytest.fixture
def cog(guild):
    bot = MagicMock()
    with patch("sixMans.sixMans.Config.get_conf") as mock_conf, patch("sixMans.sixMans.asyncio.create_task"):
        mock_conf.return_value.register_guild = MagicMock()
        cog = SixMans(bot)

    cog.config = MagicMock()
    cog.queues = {guild: []}
    cog.games = {guild: []}
    cog.queues_enabled = {guild: True}
    cog._save_games = AsyncMock()
    cog._helper_role = AsyncMock(return_value=None)
    cog._get_automove = AsyncMock(return_value=False)
    cog._category = AsyncMock(return_value=None)
    return cog


class TestCreateGameValidatesMembers:
    """A player who left the guild must not crash or half-create a game."""

    async def test_missing_player_aborts_pop_and_keeps_others_queued(self, cog, guild, players):
        q = make_queue(guild, players)
        cog.queues[guild] = [q]

        # Player 3 left the server while waiting in the queue
        gone = players[2]
        guild.get_member = MagicMock(side_effect=lambda pid: None if pid == gone.id else players[pid - 1])
        guild.fetch_member = AsyncMock(side_effect=discord.NotFound(MagicMock(status=404), "Unknown Member"))

        with patch.object(Game, "create_game_channels", new=AsyncMock()) as create_channels:
            game = await cog.create_game(guild, q)

        assert game is None
        create_channels.assert_not_called()
        assert cog.games[guild] == []

        # Only the departed player was removed. The rest keep their place in line.
        assert q.queue.qsize() == 5
        assert list(q.queue.queue) == [p for p in players if p.id != gone.id]

    async def test_cache_miss_is_confirmed_against_the_api(self, cog, guild, players):
        """A cold member cache must not look like the whole queue left the server."""
        q = make_queue(guild, players)
        cog.queues[guild] = [q]
        # Nothing is cached, but every player is still really in the guild
        guild.get_member = MagicMock(return_value=None)
        guild.fetch_member = AsyncMock(side_effect=lambda pid: players[pid - 1])

        with (
            patch.object(Game, "create_game_channels", new=AsyncMock()),
            patch.object(Game, "process_team_selection_method", new=AsyncMock()),
        ):
            game = await cog.create_game(guild, q)

        assert game is not None
        assert guild.fetch_member.await_count == 6
        assert q.queue.qsize() == 0

    async def test_unverifiable_player_stays_in_queue(self, cog, guild, players):
        """If the API can't confirm a departure, don't remove anyone."""
        q = make_queue(guild, players)
        cog.queues[guild] = [q]
        guild.get_member = MagicMock(side_effect=lambda pid: None if pid == players[2].id else players[pid - 1])
        guild.fetch_member = AsyncMock(side_effect=discord.HTTPException(MagicMock(status=500), "boom"))

        with (
            patch.object(Game, "create_game_channels", new=AsyncMock()),
            patch.object(Game, "process_team_selection_method", new=AsyncMock()),
        ):
            game = await cog.create_game(guild, q)

        assert game is not None
        assert game.players == set(players)

    async def test_all_players_present_creates_game(self, cog, guild, players):
        q = make_queue(guild, players)
        cog.queues[guild] = [q]
        guild.get_member = MagicMock(side_effect=lambda pid: players[pid - 1])

        with (
            patch.object(Game, "create_game_channels", new=AsyncMock()),
            patch.object(Game, "process_team_selection_method", new=AsyncMock()),
        ):
            game = await cog.create_game(guild, q)

        assert game is not None
        assert q.queue.qsize() == 0
        assert cog.games[guild] == [game]
        assert game.players == set(players)


class TestCreateGameRollback:
    """Channel creation failures must not strand players or leave orphan channels."""

    async def test_channel_failure_returns_players_to_queue(self, cog, guild, players):
        q = make_queue(guild, players)
        cog.queues[guild] = [q]
        guild.get_member = MagicMock(side_effect=lambda pid: players[pid - 1])

        boom = discord.HTTPException(MagicMock(status=500), "boom")
        with (
            patch.object(Game, "create_game_channels", new=AsyncMock(side_effect=boom)),
            patch.object(Game, "process_team_selection_method", new=AsyncMock()) as team_selection,
        ):
            game = await cog.create_game(guild, q)

        assert game is None
        team_selection.assert_not_called()
        assert cog.games[guild] == []

        # Everyone is back in the queue, in their original order
        assert q.queue.qsize() == 6
        assert list(q.queue.queue) == players

    async def test_rollback_does_not_duplicate_timeout_tasks(self, cog, guild, players):
        """Popped players keep their original timeout task, so requeueing must not add another."""
        q = make_queue(guild, players)
        cog.queues[guild] = [q]
        guild.get_member = MagicMock(side_effect=lambda pid: players[pid - 1])
        cog._add_to_queue = AsyncMock()
        cog.create_timeout_task = AsyncMock()

        boom = discord.HTTPException(MagicMock(status=500), "boom")
        with patch.object(Game, "create_game_channels", new=AsyncMock(side_effect=boom)):
            await cog.create_game(guild, q)

        cog._add_to_queue.assert_not_called()
        cog.create_timeout_task.assert_not_called()


class TestCreateGameChannels:
    """Game.create_game_channels error handling."""

    def build_game(self, guild, players, channel_factory):
        q = make_queue(guild, players)
        guild.create_text_channel = AsyncMock(side_effect=channel_factory("text"))
        guild.create_voice_channel = AsyncMock(side_effect=channel_factory("voice"))
        return Game(queue=q, players=players)

    def make_channel(self, kind):
        def factory(*args, **kwargs):
            channel = MagicMock(spec=discord.TextChannel if kind == "text" else discord.VoiceChannel)
            channel.name = kwargs.get("name", args[0] if args else kind)
            channel.set_permissions = AsyncMock()
            channel.send = AsyncMock()
            channel.delete = AsyncMock()
            return channel

        return factory

    async def test_unknown_overwrite_for_one_player_is_not_fatal(self, guild, players):
        """A 404 Unknown Overwrite for a single player must not abort the game."""
        not_found = discord.NotFound(MagicMock(status=404), {"code": 10009, "message": "Unknown Overwrite"})
        departed = players[2]

        async def set_permissions(target, **kwargs):
            if getattr(target, "id", None) == departed.id:
                raise not_found

        text_factory = self.make_channel("text")

        def text_channel_factory(kind):
            def factory(*args, **kwargs):
                channel = text_factory(*args, **kwargs)
                channel.set_permissions.side_effect = set_permissions
                return channel

            return factory if kind == "text" else self.make_channel(kind)

        game = self.build_game(guild, players, text_channel_factory)

        await game.create_game_channels()

        assert game.textChannel is not None
        assert len(game.voiceChannels) == 3
        # Warning posted naming the player who couldn't be given access
        sent = " ".join(str(call.args[0]) for call in game.textChannel.send.call_args_list)
        assert departed.display_name in sent

    async def test_channel_failure_deletes_partial_channels(self, guild, players):
        """If a voice channel fails, everything already created is torn down."""
        game = self.build_game(guild, players, lambda kind: self.make_channel(kind))

        created = []
        text_factory = self.make_channel("text")
        voice_factory = self.make_channel("voice")

        async def create_text(*args, **kwargs):
            channel = text_factory(*args, **kwargs)
            created.append(channel)
            return channel

        async def create_voice(*args, **kwargs):
            if len(created) >= 3:
                raise discord.HTTPException(MagicMock(status=500), "boom")
            channel = voice_factory(*args, **kwargs)
            created.append(channel)
            return channel

        guild.create_text_channel = AsyncMock(side_effect=create_text)
        guild.create_voice_channel = AsyncMock(side_effect=create_voice)

        with pytest.raises(discord.HTTPException):
            await game.create_game_channels()

        assert len(created) == 3
        for channel in created:
            channel.delete.assert_awaited_once()
        assert game.textChannel is None
        assert game.voiceChannels == []


class TestOnMemberRemove:
    """Departing members are dropped from queues before the queue can pop."""

    async def test_member_removed_from_all_queues(self, cog, guild, players):
        leaver = players[0]
        q1 = make_queue(guild, players[:3])
        q2 = make_queue(guild, [players[0], players[3]])
        cog.queues[guild] = [q1, q2]
        cog._remove_from_queue = AsyncMock()

        await cog.on_member_remove(leaver)

        assert cog._remove_from_queue.await_count == 2
        assert {call.args[1] for call in cog._remove_from_queue.await_args_list} == {q1, q2}

    async def test_unknown_guild_does_not_raise(self, cog, players):
        """A guild the cog hasn't loaded must not KeyError."""
        other_guild = make_guild(guild_id=999)
        member = make_member(50, other_guild)
        cog._remove_from_queue = AsyncMock()

        await cog.on_member_remove(member)

        cog._remove_from_queue.assert_not_called()

    async def test_member_in_active_game_warns_channel(self, cog, guild, players):
        cog.queues[guild] = []
        q = make_queue(guild)
        game = Game(queue=q, players=players)
        game.textChannel = MagicMock(spec=discord.TextChannel)
        game.textChannel.send = AsyncMock()
        cog.games[guild] = [game]
        cog._helper_role = AsyncMock(return_value=None)

        await cog.on_member_remove(players[0])

        game.textChannel.send.assert_awaited_once()
        await_args = game.textChannel.send.await_args
        assert await_args is not None
        assert players[0].display_name in await_args.args[0]
