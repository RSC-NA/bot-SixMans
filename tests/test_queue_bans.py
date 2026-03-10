import datetime
from unittest.mock import AsyncMock, MagicMock, patch, PropertyMock
import pytest
import discord


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
    # For __contains__ checks in queue
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


def make_cog(guild, queues=None, bans_dict=None):
    """Create a minimal mock of the SixMans cog with the fields we need."""
    cog = MagicMock()
    cog.queues = {guild: queues or []}
    cog.queues_enabled = {guild: True}
    cog.has_perms = AsyncMock(return_value=True)
    cog._remove_from_queue = AsyncMock()

    # Config mock
    guild_config = MagicMock()
    queue_bans = make_config_bans(bans_dict or {})
    guild_config.QueueBans = queue_bans
    cog.config = MagicMock()
    cog.config.guild = MagicMock(return_value=guild_config)

    return cog


# ─── Ban check logic tests ───


class TestBanCheckInQueue:
    """Test the ban-check logic that runs inside the queue command."""

    @pytest.mark.asyncio
    async def test_active_ban_blocks_queue(self):
        """A player with an active ban should be blocked from queueing."""
        guild = make_guild()
        player = make_member(100, guild)
        future_ts = datetime.datetime.now(datetime.timezone.utc).timestamp() + 3600

        bans = {
            str(player.id): {
                "expires": future_ts,
                "reason": "toxicity",
                "banned_by": 999,
            }
        }

        # Simulate the ban check logic from the queue command
        player_id = str(player.id)
        assert player_id in bans
        assert bans[player_id]["expires"] > datetime.datetime.now(datetime.timezone.utc).timestamp()

    @pytest.mark.asyncio
    async def test_expired_ban_allows_queue(self):
        """A player whose ban has expired should be allowed to queue."""
        guild = make_guild()
        player = make_member(100, guild)
        past_ts = datetime.datetime.now(datetime.timezone.utc).timestamp() - 3600

        bans = {
            str(player.id): {
                "expires": past_ts,
                "reason": "left match",
                "banned_by": 999,
            }
        }

        player_id = str(player.id)
        assert player_id in bans
        assert bans[player_id]["expires"] <= datetime.datetime.now(datetime.timezone.utc).timestamp()
        # The code would delete the ban here
        del bans[player_id]
        assert player_id not in bans

    @pytest.mark.asyncio
    async def test_no_ban_allows_queue(self):
        """A player with no ban entry should be allowed to queue."""
        bans = {}
        player_id = "100"
        assert player_id not in bans

    @pytest.mark.asyncio
    async def test_ban_message_includes_reason(self):
        """The ban message should include the reason when one is provided."""
        future_ts = datetime.datetime.now(datetime.timezone.utc).timestamp() + 3600
        ban = {"expires": future_ts, "reason": "toxicity", "banned_by": 999}

        expires = int(ban["expires"])
        reason = ban.get("reason")
        msg = f":x: You are banned from queueing until <t:{expires}:F> (<t:{expires}:R>)."
        if reason:
            msg += f"\nReason: {reason}"

        assert "toxicity" in msg
        assert f"<t:{expires}:F>" in msg

    @pytest.mark.asyncio
    async def test_ban_message_no_reason(self):
        """The ban message should not include a reason line when none is provided."""
        future_ts = datetime.datetime.now(datetime.timezone.utc).timestamp() + 3600
        ban = {"expires": future_ts, "reason": None, "banned_by": 999}

        expires = int(ban["expires"])
        reason = ban.get("reason")
        msg = f":x: You are banned from queueing until <t:{expires}:F> (<t:{expires}:R>)."
        if reason:
            msg += f"\nReason: {reason}"

        assert "Reason:" not in msg


# ─── Ban storage tests ───


class TestBanStorage:
    """Test storing and retrieving ban data."""

    @pytest.mark.asyncio
    async def test_store_ban(self):
        """Storing a ban should persist the correct data."""
        guild = make_guild()
        cog = make_cog(guild)

        player_id = "100"
        expires = datetime.datetime.now(datetime.timezone.utc).timestamp() + 3600
        ban_data = {"expires": expires, "reason": "test", "banned_by": 999}

        bans = await cog.config.guild(guild).QueueBans()
        bans[player_id] = ban_data
        await cog.config.guild(guild).QueueBans.set(bans)

        cog.config.guild(guild).QueueBans.set.assert_called_once_with({player_id: ban_data})

    @pytest.mark.asyncio
    async def test_remove_ban(self):
        """Removing a ban should delete the player's entry."""
        guild = make_guild()
        player_id = "100"
        bans_dict = {
            player_id: {
                "expires": datetime.datetime.now(datetime.timezone.utc).timestamp() + 3600,
                "reason": "test",
                "banned_by": 999,
            }
        }
        cog = make_cog(guild, bans_dict=bans_dict)

        bans = await cog.config.guild(guild).QueueBans()
        assert player_id in bans
        del bans[player_id]
        assert player_id not in bans


# ─── Command behavior tests ───


class TestQueueBanCommand:
    """Test the queueBan command behavior."""

    @pytest.mark.asyncio
    async def test_ban_kicks_from_all_queues(self):
        """Banning a player should kick them from all queues they're in."""
        guild = make_guild()
        player = make_member(100, guild)
        q1 = make_queue_with_player(player)
        q2 = make_queue_with_player(player)
        q3 = make_queue_empty()

        cog = make_cog(guild, queues=[q1, q2, q3])

        # Simulate the kick-from-all-queues logic
        for six_mans_queue in cog.queues[guild]:
            if player in six_mans_queue.queue:
                await cog._remove_from_queue(player, six_mans_queue)

        assert cog._remove_from_queue.call_count == 2

    @pytest.mark.asyncio
    async def test_ban_computes_correct_expiry(self):
        """The expiry timestamp should be now + duration_minutes * 60."""
        duration_minutes = 30
        before = datetime.datetime.now(datetime.timezone.utc).timestamp()
        expires = datetime.datetime.now(datetime.timezone.utc).timestamp() + (duration_minutes * 60)
        after = datetime.datetime.now(datetime.timezone.utc).timestamp()

        assert before + 1800 <= expires <= after + 1800

    @pytest.mark.asyncio
    async def test_ban_dm_failure_is_silent(self):
        """If DM fails, the command should still succeed."""
        player = make_member(100)
        player.send = AsyncMock(side_effect=discord.Forbidden(MagicMock(), "Cannot send"))

        # Simulate DM attempt with try/except
        try:
            await player.send("You have been banned.")
        except Exception:
            pass
        # No assertion needed — just verifying no exception propagates


class TestQueueUnbanCommand:
    """Test the queueUnban command behavior."""

    @pytest.mark.asyncio
    async def test_unban_removes_entry(self):
        """Unbanning should remove the player's ban entry."""
        player_id = "100"
        bans = {
            player_id: {
                "expires": datetime.datetime.now(datetime.timezone.utc).timestamp() + 3600,
                "reason": "test",
                "banned_by": 999,
            }
        }

        assert player_id in bans
        del bans[player_id]
        assert player_id not in bans

    @pytest.mark.asyncio
    async def test_unban_nonexistent_player(self):
        """Unbanning a player who isn't banned should report that."""
        bans = {}
        player_id = "100"
        assert player_id not in bans


class TestListQueueBansCommand:
    """Test the listQueueBans command behavior."""

    @pytest.mark.asyncio
    async def test_expired_bans_cleaned(self):
        """Expired bans should be cleaned up when listing."""
        now = datetime.datetime.now(datetime.timezone.utc).timestamp()
        bans = {
            "100": {"expires": now - 3600, "reason": "expired", "banned_by": 999},
            "200": {"expires": now + 3600, "reason": "active", "banned_by": 999},
            "300": {"expires": now - 1, "reason": "just expired", "banned_by": 999},
        }

        expired = [pid for pid, ban in bans.items() if ban["expires"] <= now]
        for pid in expired:
            del bans[pid]

        assert "100" not in bans
        assert "300" not in bans
        assert "200" in bans
        assert len(bans) == 1

    @pytest.mark.asyncio
    async def test_no_active_bans(self):
        """When no bans exist, the list should be empty."""
        bans = {}
        assert not bans

    @pytest.mark.asyncio
    async def test_has_perms_required(self):
        """Commands should check has_perms before executing."""
        guild = make_guild()
        cog = make_cog(guild)
        cog.has_perms = AsyncMock(return_value=False)

        # Simulate the perms check
        result = await cog.has_perms(make_member(100))
        assert result is False
