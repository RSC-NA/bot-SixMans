import datetime
import logging
from typing import TYPE_CHECKING

import discord
from discord.ext.commands import Context
from redbot.core import checks, commands

from sixMans.embeds import ErrorEmbed
from sixMans.types import QueueBan

if TYPE_CHECKING:
    from redbot.core import Config

    from sixMans.queue import SixMansQueue

log = logging.getLogger("red.sixMans.queues")


class QueueBanCommands:
    """Queue ban commands and ban storage, mixed into the SixMans cog."""

    if TYPE_CHECKING:
        config: Config
        queues: dict[discord.Guild, list[SixMansQueue]]

        async def has_perms(self, member: discord.Member) -> bool: ...
        async def _remove_from_queue(self, player: discord.Member, six_mans_queue: SixMansQueue): ...

    @commands.guild_only()
    @commands.command(aliases=["qban"])
    @checks.admin_or_permissions(kick_members=True)
    async def queueBan(self, ctx: Context, player: discord.Member, duration_minutes: int, *, reason: str | None = None):
        """Ban a player from queueing for a specified number of minutes.

        Format: `[p]queueBan <player> <minutes> [reason]`"""
        if not ctx.guild:
            return

        if not isinstance(ctx.author, discord.Member):
            return

        if not await self.has_perms(ctx.author):
            return

        if duration_minutes <= 0:
            return await ctx.send(embed=ErrorEmbed(description="Duration must be greater than 0 minutes."), ephemeral=True)

        if not reason:
            reason = "None provided."

        if len(reason) > 1500:
            return await ctx.send(embed=ErrorEmbed(description="Reason must be 1500 characters or less."), ephemeral=True)

        expires = datetime.datetime.now(datetime.UTC).timestamp() + (duration_minutes * 60)
        ban_details = QueueBan(
            expires=expires,
            reason=reason,
            banned_by=ctx.author.id,
        )
        await self._add_queue_ban(ctx.guild, player.id, ban_details)

        # Kick from all queues in guild
        for six_mans_queue in self.queues[ctx.guild]:
            if player in six_mans_queue.queue:
                await self._remove_from_queue(player, six_mans_queue)

        expires_int = int(expires)
        msg = f":white_check_mark: {player.mention} has been banned from queueing until <t:{expires_int}:F> (<t:{expires_int}:R>)."
        if reason:
            msg += f"\nReason: {reason}"
        await ctx.send(msg, ephemeral=True)

        # DM the player
        try:
            dm_msg = f"You have been banned from queueing in **{ctx.guild.name}** until <t:{expires_int}:F> (<t:{expires_int}:R>)."
            if reason:
                dm_msg += f"\nReason: {reason}"
            await player.send(dm_msg)
        except (discord.HTTPException, discord.Forbidden):
            pass

    @commands.guild_only()
    @commands.command(aliases=["qunban"])
    @checks.admin_or_permissions(kick_members=True)
    async def queueUnban(self, ctx: Context, player: discord.Member):
        """Remove a queue ban from a player.

        Format: `[p]queueUnban <player>`"""
        if not ctx.guild:
            return

        if not isinstance(ctx.author, discord.Member):
            return

        if not await self.has_perms(ctx.author):
            return

        banned = await self.check_banned(ctx.guild, player)
        if banned:
            await self._remove_queue_ban(ctx.guild, player.id)
            await ctx.send(f":white_check_mark: {player.mention} has been unbanned from queueing.")
        else:
            await ctx.send(f"{player.display_name} is not currently banned from queueing.")

    @commands.guild_only()
    @commands.command(aliases=["qbans"])
    @checks.admin_or_permissions(kick_members=True)
    async def listQueueBans(self, ctx: Context):
        """List all active queue bans."""

        if not ctx.guild:
            return

        if not isinstance(ctx.author, discord.Member):
            return

        if not await self.has_perms(ctx.author):
            return

        # Clear expired bans
        await self.expire_bans(ctx.guild)

        bans = await self._get_queue_bans(ctx.guild)
        if not bans:
            return await ctx.send("No active queue bans.")

        embed = discord.Embed(title="Active Queue Bans", color=discord.Color.red())
        for player_id, ban in bans.items():
            expires_int = int(ban["expires"])
            reason = ban.get("reason") or "No reason provided"
            member = ctx.guild.get_member(int(player_id))
            name = member.display_name if member else f"Unknown ({player_id})"
            embed.add_field(
                name=name,
                value=f"Expires: <t:{expires_int}:F> (<t:{expires_int}:R>)\nReason: {reason}",
                inline=False,
            )
        await ctx.send(embed=embed)

    async def check_banned(self, guild: discord.Guild, player: discord.Member) -> QueueBan | None:
        bans = await self._get_queue_bans(guild)
        ban = bans.get(str(player.id))
        if not ban:
            return None

        now = datetime.datetime.now(datetime.UTC).timestamp()
        if ban["expires"] <= now:
            await self._remove_queue_ban(guild, player.id)
            return None

        return ban

    async def expire_bans(self, guild: discord.Guild):
        log.debug("Expiring all bans for guild: %d", guild.id)
        bans = await self._get_queue_bans(guild)

        # Clean expired bans
        now = datetime.datetime.now(datetime.UTC).timestamp()
        expired = [pid for pid, ban in bans.items() if ban["expires"] <= now]
        for pid in expired:
            await self._remove_queue_ban(guild, int(pid))

    async def _get_queue_bans(self, guild: discord.Guild) -> dict[str, QueueBan]:
        return await self.config.guild(guild).QueueBans()

    async def _add_queue_ban(self, guild: discord.Guild, member: int, queue_ban: QueueBan):
        log.debug(f"Adding queue ban. Guild: {guild.id} Member: {member} Ban: {queue_ban}")
        queue_bans = await self._get_queue_bans(guild)
        member_fmt = str(member)
        queue_bans[member_fmt] = queue_ban
        await self.config.guild(guild).QueueBans.set(queue_bans)

    async def _remove_queue_ban(self, guild: discord.Guild, member: int):
        queue_bans = await self._get_queue_bans(guild)
        member_fmt = str(member)
        if member_fmt in queue_bans:
            del queue_bans[member_fmt]
            await self.config.guild(guild).QueueBans.set(queue_bans)
