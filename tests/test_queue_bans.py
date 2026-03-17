import datetime
from unittest.mock import AsyncMock, MagicMock, patch
import pytest
import discord

from sixMans.sixMans import SixMans


# Helpers to build mock objects


def make_guild(guild_id=1):
    guild = MagicMock(spec=discord.Guild)
    guild.id = guild_id
    guild.name = "Test Guild"
    return guild


def make_member(member_id=100, guild=None, display_name="TestPlayer"):
    member = MagicMock(spec=discord.Member)
    member.id = member_id
    member.display_name = display_name
    member.mention = f"<@{member_id}>"
    member.guild = guild
    member.send = AsyncMock()
    member.__eq__ = lambda self, other: isinstance(other, MagicMock) and self.id == other.id
    member.__hash__ = lambda self: hash(self.id)
    return member


def make_queue_with_player(player):
    """Create a mock SixMansQueue that contains the given player."""
    q = MagicMock()
    q.queue = MagicMock()
    q.queue.__contains__ = lambda self, p: p.id == player.id
    q.name = "TestQueue"
    return q


def make_queue_empty():
    """Create a mock SixMansQueue with no players."""
    q = MagicMock()
    q.queue = MagicMock()
    q.queue.__contains__ = lambda self, p: False
    q.name = "EmptyQueue"
    return q


def make_config_bans(bans_dict):
    """Create a mock config accessor for QueueBans."""
    bans_accessor = AsyncMock(return_value=bans_dict)
    bans_accessor.set = AsyncMock()
    return bans_accessor


def make_ctx(guild, author, channel=None):
    ctx = AsyncMock()
    ctx.guild = guild
    ctx.author = author
    ctx.message = MagicMock()
    ctx.message.author = author
    ctx.message.channel = channel or MagicMock()
    ctx.channel = channel or ctx.message.channel
    ctx.send = AsyncMock()
    return ctx


@pytest.fixture
def guild():
    return make_guild()


@pytest.fixture
def cog(guild):
    """Instantiate a real SixMans cog with mocked bot and config."""
    bot = MagicMock()
    with patch("sixMans.sixMans.Config.get_conf") as mock_conf, patch("sixMans.sixMans.asyncio.create_task"):
        # Set up config mock
        mock_conf.return_value.register_guild = MagicMock()

        cog = SixMans(bot)

    # Override config with our controllable mock
    guild_config = MagicMock()
    queue_bans = make_config_bans({})
    guild_config.QueueBans = queue_bans
    cog.config = MagicMock()
    cog.config.guild = MagicMock(return_value=guild_config)

    # Set up guild state
    cog.queues = {guild: []}
    cog.games = {guild: []}
    cog.queues_enabled = {guild: True}
    cog._remove_from_queue = AsyncMock()
    cog._add_to_queue = AsyncMock()

    return cog


def set_bans(cog, guild, bans_dict):
    """Helper to configure the ban state on a cog."""
    queue_bans = make_config_bans(bans_dict)
    guild_config = MagicMock()
    guild_config.QueueBans = queue_bans
    cog.config.guild = MagicMock(return_value=guild_config)


# ─── Ban check logic tests ───


class TestBanCheckInQueue:
    """Test the ban-check logic that runs inside the queue command."""

    @pytest.mark.asyncio
    async def test_active_ban_blocks_queue(self, cog, guild):
        """A player with an active ban should be blocked from queueing."""
        player = make_member(100, guild)
        future_ts = datetime.datetime.now(datetime.timezone.utc).timestamp() + 3600

        set_bans(
            cog,
            guild,
            {
                str(player.id): {
                    "expires": future_ts,
                    "reason": "toxicity",
                    "banned_by": 999,
                }
            },
        )

        ctx = make_ctx(guild, player)
        q = make_queue_empty()
        q.textChannel = ctx.channel
        cog.queues[guild] = [q]
        cog._get_queue_by_text_channel = MagicMock(return_value=q)

        await cog.queue.callback(cog, ctx)

        ctx.send.assert_called_once()
        msg = ctx.send.call_args[0][0]
        assert ":x: You are banned from queueing" in msg
        assert "toxicity" in msg

    @pytest.mark.asyncio
    async def test_expired_ban_allows_queue(self, cog, guild):
        """A player whose ban has expired should have it cleaned up."""
        player = make_member(100, guild)
        past_ts = datetime.datetime.now(datetime.timezone.utc).timestamp() - 3600

        bans_dict = {
            str(player.id): {
                "expires": past_ts,
                "reason": "left match",
                "banned_by": 999,
            }
        }
        set_bans(cog, guild, bans_dict)

        ctx = make_ctx(guild, player)
        q = make_queue_empty()
        q.textChannel = ctx.channel
        q.queue.queue = []
        q._queue_full = MagicMock(return_value=False)
        cog.queues[guild] = [q]
        cog.games[guild] = []
        cog._get_queue_by_text_channel = MagicMock(return_value=q)

        await cog.queue.callback(cog, ctx)

        # Expired ban should have been deleted from the dict
        assert str(player.id) not in bans_dict
        # The set should have been called to persist the cleanup
        cog.config.guild(guild).QueueBans.set.assert_called()

    @pytest.mark.asyncio
    async def test_ban_message_includes_reason(self, cog, guild):
        """The ban message should include the reason when one is provided."""
        player = make_member(100, guild)
        future_ts = datetime.datetime.now(datetime.timezone.utc).timestamp() + 3600

        set_bans(
            cog,
            guild,
            {
                str(player.id): {
                    "expires": future_ts,
                    "reason": "toxicity",
                    "banned_by": 999,
                }
            },
        )

        ctx = make_ctx(guild, player)
        q = make_queue_empty()
        cog._get_queue_by_text_channel = MagicMock(return_value=q)

        await cog.queue.callback(cog, ctx)

        msg = ctx.send.call_args[0][0]
        assert "toxicity" in msg

    @pytest.mark.asyncio
    async def test_ban_message_no_reason(self, cog, guild):
        """The ban message should not include a reason line when none is provided."""
        player = make_member(100, guild)
        future_ts = datetime.datetime.now(datetime.timezone.utc).timestamp() + 3600

        set_bans(
            cog,
            guild,
            {
                str(player.id): {
                    "expires": future_ts,
                    "reason": None,
                    "banned_by": 999,
                }
            },
        )

        ctx = make_ctx(guild, player)
        q = make_queue_empty()
        cog._get_queue_by_text_channel = MagicMock(return_value=q)

        await cog.queue.callback(cog, ctx)

        msg = ctx.send.call_args[0][0]
        assert "Reason:" not in msg


# ─── Command behavior tests ───


class TestQueueBanCommand:
    """Test the queueBan command behavior."""

    @pytest.mark.asyncio
    async def test_ban_kicks_from_all_queues(self, cog, guild):
        """Banning a player should kick them from all queues they're in."""
        player = make_member(100, guild)
        admin = make_member(999, guild)
        q1 = make_queue_with_player(player)
        q2 = make_queue_with_player(player)
        q3 = make_queue_empty()
        cog.queues[guild] = [q1, q2, q3]

        ctx = make_ctx(guild, admin)

        await cog.queueBan.callback(cog, ctx, player, 30, reason="test")

        assert cog._remove_from_queue.call_count == 2

    @pytest.mark.asyncio
    async def test_ban_stores_correct_expiry(self, cog, guild):
        """The expiry timestamp should be now + duration_minutes * 60."""
        player = make_member(100, guild)
        admin = make_member(999, guild)
        ctx = make_ctx(guild, admin)

        before = datetime.datetime.now(datetime.timezone.utc).timestamp()
        await cog.queueBan.callback(cog, ctx, player, 30, reason="test")
        after = datetime.datetime.now(datetime.timezone.utc).timestamp()

        set_call = cog.config.guild(guild).QueueBans.set
        set_call.assert_called_once()
        stored_bans = set_call.call_args[0][0]
        expires = stored_bans[str(player.id)]["expires"]
        assert before + 1800 <= expires <= after + 1800

    @pytest.mark.asyncio
    async def test_ban_stores_reason(self, cog, guild):
        """The ban should store the provided reason."""
        player = make_member(100, guild)
        admin = make_member(999, guild)
        ctx = make_ctx(guild, admin)

        await cog.queueBan.callback(cog, ctx, player, 30, reason="toxic behavior")

        stored_bans = cog.config.guild(guild).QueueBans.set.call_args[0][0]
        assert stored_bans[str(player.id)]["reason"] == "toxic behavior"

    @pytest.mark.asyncio
    async def test_ban_sends_confirmation(self, cog, guild):
        """The command should send a confirmation message."""
        player = make_member(100, guild)
        admin = make_member(999, guild)
        ctx = make_ctx(guild, admin)

        await cog.queueBan.callback(cog, ctx, player, 30, reason="test")

        ctx.send.assert_called_once()
        msg = ctx.send.call_args[0][0]
        assert ":white_check_mark:" in msg
        assert player.mention in msg

    @pytest.mark.asyncio
    async def test_ban_dm_failure_is_silent(self, cog, guild):
        """If DM fails with HTTPException, the command should still succeed."""
        player = make_member(100, guild)
        player.send = AsyncMock(side_effect=discord.Forbidden(MagicMock(), "Cannot send"))
        admin = make_member(999, guild)
        ctx = make_ctx(guild, admin)

        await cog.queueBan.callback(cog, ctx, player, 30, reason="test")

        # Command should still have sent the confirmation
        ctx.send.assert_called_once()

    @pytest.mark.asyncio
    async def test_ban_zero_duration_rejected(self, cog, guild):
        """Duration of 0 should be rejected."""
        player = make_member(100, guild)
        admin = make_member(999, guild)
        ctx = make_ctx(guild, admin)

        await cog.queueBan.callback(cog, ctx, player, 0, reason="test")

        ctx.send.assert_called_once()
        assert ctx.send.call_args is not None
        assert len(ctx.send.call_args) > 0

        embed = ctx.send.call_args[1].get("embed")
        assert embed is not None
        assert "greater than 0 minutes" in embed.description

    @pytest.mark.asyncio
    async def test_ban_negative_duration_rejected(self, cog, guild):
        """Negative duration should be rejected."""
        player = make_member(100, guild)
        admin = make_member(999, guild)
        ctx = make_ctx(guild, admin)

        await cog.queueBan.callback(cog, ctx, player, -5, reason="test")

        ctx.send.assert_called_once()
        assert ctx.send.call_args is not None
        assert len(ctx.send.call_args) > 0

        embed = ctx.send.call_args[1].get("embed")
        assert embed is not None
        assert "greater than 0 minutes" in embed.description


class TestQueueUnbanCommand:
    """Test the queueUnban command behavior."""

    @pytest.mark.asyncio
    async def test_unban_removes_entry(self, cog, guild):
        """Unbanning should remove the player's ban entry and send confirmation."""
        player = make_member(100, guild)
        admin = make_member(999, guild)
        bans_dict = {
            str(player.id): {
                "expires": datetime.datetime.now(datetime.timezone.utc).timestamp() + 3600,
                "reason": "test",
                "banned_by": 999,
            }
        }
        set_bans(cog, guild, bans_dict)
        ctx = make_ctx(guild, admin)

        await cog.queueUnban.callback(cog, ctx, player)

        ctx.send.assert_called_once()
        msg = ctx.send.call_args[0][0]
        assert ":white_check_mark:" in msg
        assert player.mention in msg
        # Ban should have been persisted without the player
        stored = cog.config.guild(guild).QueueBans.set.call_args[0][0]
        assert str(player.id) not in stored

    @pytest.mark.asyncio
    async def test_unban_nonexistent_player(self, cog, guild):
        """Unbanning a player who isn't banned should report that."""
        player = make_member(100, guild)
        admin = make_member(999, guild)
        ctx = make_ctx(guild, admin)

        await cog.queueUnban.callback(cog, ctx, player)

        ctx.send.assert_called_once()
        msg = ctx.send.call_args[0][0]
        assert "not currently banned" in msg


class TestListQueueBansCommand:
    """Test the listQueueBans command behavior."""

    @pytest.mark.asyncio
    async def test_expired_bans_cleaned(self, cog, guild):
        """Expired bans should be cleaned up when listing."""
        now = datetime.datetime.now(datetime.timezone.utc).timestamp()
        bans_dict = {
            "100": {"expires": now - 3600, "reason": "expired", "banned_by": 999},
            "200": {"expires": now + 3600, "reason": "active", "banned_by": 999},
            "300": {"expires": now - 1, "reason": "just expired", "banned_by": 999},
        }
        set_bans(cog, guild, bans_dict)

        member_200 = make_member(200, guild, "ActivePlayer")
        guild.get_member = MagicMock(return_value=member_200)

        ctx = make_ctx(guild, make_member(999, guild))

        await cog.listQueueBans.callback(cog, ctx)

        # Expired bans should have been removed
        assert "100" not in bans_dict
        assert "300" not in bans_dict
        assert "200" in bans_dict

    @pytest.mark.asyncio
    async def test_no_active_bans(self, cog, guild):
        """When no bans exist, should report no active bans."""
        ctx = make_ctx(guild, make_member(999, guild))

        await cog.listQueueBans.callback(cog, ctx)

        ctx.send.assert_called_once()
        msg = ctx.send.call_args[0][0]
        assert "No active queue bans" in msg
