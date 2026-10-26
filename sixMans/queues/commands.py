import logging
from typing import TYPE_CHECKING

import discord
from discord.ext.commands import Context
from redbot.core import checks, commands

from sixMans.embeds import BlueEmbed, ErrorEmbed, QueueNotFoundEmbed, SuccessEmbed
from sixMans.enums import GameMode
from sixMans.queue import SixMansQueue
from sixMans.queues.embeds import queue_info_embed, queue_players_embed
from sixMans.queues.state import QueueState
from sixMans.strings import Strings

if TYPE_CHECKING:
    from sixMans.scoreboard.scoreboard import Scoreboard
    from sixMans.types import QueueBan

log = logging.getLogger("red.sixMans.queues")


class QueueCommands(QueueState):
    """Queue setup, joining and leaving, and helper queue commands, mixed into the SixMans cog."""

    if TYPE_CHECKING:
        scoreboard: Scoreboard
        queues_enabled: dict[discord.Guild, bool]

        async def has_perms(self, member: discord.Member) -> bool: ...
        async def _get_queue_max_size(self, guild: discord.Guild) -> int: ...
        async def _save_queues_enabled(self, guild: discord.Guild, enabled: bool): ...
        async def check_banned(self, guild: discord.Guild, player: discord.Member) -> QueueBan | None: ...
        async def _pop_queue(self, ctx: Context, six_mans_queue: SixMansQueue) -> bool: ...

    @commands.guild_only()
    @commands.command()
    @checks.admin_or_permissions(manage_guild=True)
    async def addNewQueue(
        self,
        ctx: Context,
        name,
        points_per_play: int,
        points_per_win: int,
        *channels: discord.TextChannel,
    ):
        if not ctx.guild:
            return

        # Make sure queue name does not exist
        if self.get_queue_by_name(ctx.guild, name):
            return await ctx.send(embed=ErrorEmbed(description=f"There is already a queue set up with the name: {name}"))

        # Validate queue channel
        queue_channels = []
        for c in channels:
            if not isinstance(c, discord.TextChannel):
                return await ctx.send(embed=ErrorEmbed(description=f"{c} is not a valid text channel."))
            if self.get_queue_by_text_channel(c):
                return await ctx.send(embed=ErrorEmbed(description=f"{c.mention} is attached to another queue."))
            queue_channels.append(c)

        queue_max_size = await self._get_queue_max_size(ctx.guild)
        points = {
            Strings.PP_PLAY_KEY: points_per_play,
            Strings.PP_WIN_KEY: points_per_win,
        }
        team_selection = await self._team_selection(ctx.guild)
        six_mans_queue = SixMansQueue(
            name,
            ctx.guild,
            queue_channels,
            points,
            queue_max_size,
            teamSelection=team_selection,
            category=await self._category(ctx.guild),
        )
        self.queues[ctx.guild].append(six_mans_queue)
        await self._save_queues(ctx.guild, self.queues[ctx.guild])
        await ctx.send("Done")

    @commands.guild_only()
    @commands.command()
    @checks.admin_or_permissions(manage_guild=True)
    async def editQueue(
        self,
        ctx: Context,
        current_name: str,
        new_name: str,
        points_per_play: int,
        points_per_win: int,
        *channels: discord.TextChannel,
    ):
        if not ctx.guild:
            return

        # Validate queue name
        six_mans_queue = self.get_queue_by_name(ctx.guild, current_name)
        if six_mans_queue is None:
            return await ctx.send(embed=QueueNotFoundEmbed(current_name))

        # Validate queue channels
        queue_channels = []
        for c in channels:
            if not isinstance(c, discord.TextChannel):
                return await ctx.send(embed=ErrorEmbed(description=f"{c} is not a valid text channel."))
            qc = self.get_queue_by_text_channel(c)
            if qc and qc.name != current_name:
                return await ctx.send(embed=ErrorEmbed(description=f"{c.mention} is attached to another queue."))
            queue_channels.append(c)

        six_mans_queue.name = new_name
        six_mans_queue.points = {
            Strings.PP_PLAY_KEY: points_per_play,
            Strings.PP_WIN_KEY: points_per_win,
        }
        six_mans_queue.channels = queue_channels
        await self._save_queues(ctx.guild, self.queues[ctx.guild])
        await ctx.send("Done")

    @commands.guild_only()
    @commands.command()
    @checks.admin_or_permissions(manage_guild=True)
    async def removeQueue(self, ctx: Context, *, queue_name: str):
        if not ctx.guild:
            return

        queue = self.get_queue_by_name(ctx.guild, queue_name)
        if not queue:
            return await ctx.send(embed=QueueNotFoundEmbed(queue_name))

        self.queues[ctx.guild].remove(queue)
        await self._save_queues(ctx.guild, self.queues[ctx.guild])
        await self.scoreboard.mark_queue_deleted(ctx.guild, queue)
        await ctx.send("Done")

    @commands.guild_only()
    @commands.command(aliases=["setQTS", "setQueueTeamSelection", "sqts"])
    @checks.admin_or_permissions()
    async def setQueueTS(self, ctx: Context, queue_name: str, *, team_selection: GameMode):
        """Sets the team selection mode for a specific queue"""
        if not ctx.guild:
            return

        if not isinstance(ctx.author, discord.Member):
            return

        if not await self.has_perms(ctx.author):
            return

        invalid_embed = ErrorEmbed()

        # Validate queue name
        six_mans_queue = self.get_queue_by_name(ctx.guild, queue_name)
        if six_mans_queue is None:
            return await ctx.send(embed=QueueNotFoundEmbed(queue_name))

        # Validate queue size
        if six_mans_queue.maxSize == 2:
            invalid_embed.description = "Queue with max size of 2 cannot change team selection method."
            return await ctx.send(embed=invalid_embed)

        # Set team selection method
        try:
            await six_mans_queue.set_team_selection(team_selection)
            await self._save_queues(ctx.guild, self.queues[ctx.guild])
            ts_embed = SuccessEmbed(
                description=f"Queue default mode has been set to **{team_selection}**",
            )
            await ctx.send(embed=ts_embed)
        except ValueError:
            invalid_embed.description = f"**{team_selection}** is an invalid team selection mode"
            await ctx.send(embed=invalid_embed)

    @commands.guild_only()
    @commands.command(aliases=["getQTS", "getQueueTeamSelection", "gqts"])
    @checks.admin_or_permissions()
    async def getQueueTS(self, ctx: Context, queue_name: str):
        """Gets the team selection mode for a specific queue"""
        if not ctx.guild:
            return

        if not isinstance(ctx.author, discord.Member):
            return

        if not await self.has_perms(ctx.author):
            return

        six_mans_queue = self.get_queue_by_name(ctx.guild, queue_name)
        if six_mans_queue is None:
            return await ctx.send(embed=QueueNotFoundEmbed(queue_name))

        await ctx.send(
            embed=BlueEmbed(
                title=f"{six_mans_queue.name} Team Selection",
                description=f"Team selection method is currently set to **{six_mans_queue.teamSelection}**.",
            )
        )

    @commands.guild_only()
    @commands.command(aliases=["setQueueSize", "setQMaxSize", "setQMS", "sqms"])
    @checks.admin_or_permissions()
    async def setQueueMaxSize(self, ctx: Context, queue_name: str, *, max_size: int):
        """Sets the max size for a queue (Default: 6)"""
        if not ctx.guild:
            return

        six_mans_queue = self.get_queue_by_name(ctx.guild, queue_name)
        if six_mans_queue is None:
            return await ctx.send(embed=QueueNotFoundEmbed(queue_name))

        if max_size % 2 == 1:
            return await ctx.send(embed=ErrorEmbed(description="Queues sizes must be configured for an even number of players."))

        six_mans_queue.maxSize = max_size

        if max_size == 2:
            await six_mans_queue.set_team_selection(GameMode.RANDOM)

        await self._save_queues(ctx.guild, self.queues[ctx.guild])
        await ctx.send("Done")

    @commands.guild_only()
    @commands.command(aliases=["getQMaxSize", "getQMS", "gqms", "qms"])
    @checks.admin_or_permissions()
    async def getQueueMaxSize(self, ctx: Context, queue_name: str):
        """Gets the max size for a specific queue"""
        if not ctx.guild:
            return

        queue = self.get_queue_by_name(ctx.guild, queue_name)
        if not queue:
            return await ctx.send(embed=QueueNotFoundEmbed(queue_name))

        await ctx.send(
            embed=BlueEmbed(
                title=f"{queue.name} Queue Size",
                description=f"Current queue size: **{queue.maxSize}**",
            )
        )

    @commands.guild_only()
    @commands.command(aliases=["qn"])
    async def getQueueNames(self, ctx: Context):
        if not ctx.guild:
            return

        queue_names = ""
        for queue in self.queues[ctx.guild]:
            if queue.guild == ctx.guild:
                queue_names += f"{queue.name}\n"
        await ctx.send(f"```Queues set up in server:\n{queue_names}```")

    @commands.guild_only()
    @commands.command(aliases=["qi"])
    async def getQueueInfo(self, ctx: Context, *, queue_name=None):
        if not ctx.guild:
            return

        if not isinstance(ctx.channel, discord.TextChannel):
            return

        if queue_name:
            for queue in self.queues[ctx.guild]:
                if queue.name.lower() == queue_name.lower():
                    await ctx.send(embed=await self._queue_info_embed(ctx.guild, queue))
                    return
            await ctx.send(f":x: No queue set up with name: {queue_name}")
            return

        six_mans_queue = self.get_queue_by_text_channel(ctx.channel)
        if not six_mans_queue:
            await ctx.send(":x: No queue set up in this channel")
            return

        await ctx.send(embed=await self._queue_info_embed(ctx.guild, six_mans_queue))

    @commands.guild_only()
    @commands.command(aliases=["cq", "status"])
    async def checkQueue(self, ctx: Context):
        if not isinstance(ctx.channel, discord.TextChannel):
            return

        six_mans_queue = self.get_queue_by_text_channel(ctx.channel)
        if not six_mans_queue:
            await ctx.send(":x: No queue set up in this channel")
            return
        await ctx.send(embed=queue_players_embed(six_mans_queue))

    @commands.guild_only()
    @commands.command(aliases=["q"])
    async def queue(self, ctx: Context):
        """Add yourself to the queue"""
        if not ctx.guild:
            return

        if not isinstance(ctx.channel, discord.TextChannel):
            return

        if not isinstance(ctx.author, discord.Member):
            return

        if not self.queues_enabled[ctx.guild]:
            return await ctx.send(":x: Queueing is currently disabled.")

        q = self.get_queue_by_text_channel(ctx.channel)
        if not q:
            return

        banned = await self.check_banned(ctx.guild, ctx.author)
        if banned:
            expires = int(banned["expires"])
            # Do not display reason for everyone to see
            msg = f":x: You are banned from queueing until <t:{expires}:F> (<t:{expires}:R>)."
            return await ctx.send(msg, ephemeral=True)

        player = ctx.author
        if player in q.queue.queue:
            return await ctx.send(f":x: You are already in the {q.name} queue")

        for game in self.games[ctx.guild]:
            if player in game:
                return await ctx.send(":x: You are already in a game")

        await self._add_to_queue(player, q)
        if q.queue_full():
            await self._pop_queue(ctx, q)

    @commands.guild_only()
    @commands.command(aliases=["dq", "lq", "leaveq", "leaveQ", "unqueue", "unq", "uq"])
    async def dequeue(self, ctx: Context):
        """Remove yourself from the queue"""
        if not isinstance(ctx.channel, discord.TextChannel):
            return

        player = ctx.author
        if not isinstance(player, discord.Member):
            return

        six_mans_queue = self.get_queue_by_text_channel(ctx.channel)
        if not six_mans_queue:
            return

        if player not in six_mans_queue.queue:
            return await ctx.send(f":x: You're not in the {six_mans_queue.name} queue")

        await self._remove_from_queue(player, six_mans_queue)

    @commands.guild_only()
    @commands.command(aliases=["kq", "fdq"])
    async def kickQueue(self, ctx: Context, player: discord.Member):
        """Remove someone else from the queue"""
        if not isinstance(ctx.channel, discord.TextChannel):
            return

        if not isinstance(ctx.author, discord.Member):
            return

        if not await self.has_perms(ctx.author):
            return

        # Get queue from context channel
        queue = self.get_queue_by_text_channel(ctx.channel)
        if not queue:
            return await ctx.send(embed=ErrorEmbed(description="Not a valid queue channel."))

        # Check if player in queue
        if player not in queue.queue:
            return await ctx.send(embed=ErrorEmbed(description=f"{player.display_name} is not in queue."))

        await self._remove_from_queue(player, queue)

    @commands.guild_only()
    @commands.command(aliases=["clrq"])
    async def clearQueue(self, ctx: Context):
        """Clear the queue"""
        if not isinstance(ctx.channel, discord.TextChannel):
            return

        if not isinstance(ctx.author, discord.Member):
            return

        if not await self.has_perms(ctx.author):
            return

        queue = self.get_queue_by_text_channel(ctx.channel)
        if not queue:
            return await ctx.send(embed=ErrorEmbed(description="Not a valid queue channel."))

        try:
            log.debug(f"Clearing queue: {queue.name}")
            queue.clear()
            await ctx.send("Queue cleared.")
        except Exception as exc:
            log.debug(f"Error clearing queue: {exc}")
            await ctx.send("Error clearing queue.")

    @commands.guild_only()
    @commands.command(aliases=["qm", "queueAll", "qa", "forceQueue", "fq"])
    @checks.admin_or_permissions(manage_guild=True)
    async def queueMultiple(self, ctx: Context, *members: discord.Member):
        """Mass queueing for testing purposes"""
        if not isinstance(ctx.channel, discord.TextChannel):
            return

        q = self.get_queue_by_text_channel(ctx.channel)
        if not q:
            return await ctx.send(embed=ErrorEmbed(description="Not a valid queue channel."))

        for member in members:
            if member in q.queue.queue:
                await ctx.send(embed=ErrorEmbed(description=f"{member.display_name} is already in queue. Skipping..."))
                continue
            await self._add_to_queue(member, q)
            if q.queue_full():
                await self._pop_queue(ctx, q)

    @commands.guild_only()
    @commands.command(aliases=["eq"])
    async def enableQueues(self, ctx: Context):
        """Enable queueing for the guild."""
        if not ctx.guild:
            return

        if not isinstance(ctx.author, discord.Member):
            return

        if not await self.has_perms(ctx.author):
            return

        await self._save_queues_enabled(ctx.guild, True)
        self.queues_enabled[ctx.guild] = True

        await ctx.send("Queueing has been enabled.")

    @commands.guild_only()
    @commands.command(aliases=["stopQueue", "sq"])
    async def disableQueues(self, ctx: Context):
        """Disable queueing for the guild."""
        if not ctx.guild:
            return

        if not isinstance(ctx.author, discord.Member):
            return

        if not await self.has_perms(ctx.author):
            return

        await self._save_queues_enabled(ctx.guild, False)
        self.queues_enabled[ctx.guild] = False

        await ctx.send("Queueing has been disabled.")

    async def _queue_info_embed(self, guild: discord.Guild, queue: SixMansQueue) -> discord.Embed:
        games_played = self.scoreboard.queue_games_played(queue.guild, queue.id)
        unique_players = len(self.scoreboard.queue_players(queue.guild, queue.id))
        return queue_info_embed(queue, games_played, unique_players, await self._get_q_lobby_vc(guild))
