import asyncio
import contextlib
import datetime
import logging
import random

import discord
from discord.ext.commands import Context
from redbot.core import Config, checks, commands
from redbot.core.utils.menus import start_adding_reactions
from redbot.core.utils.predicates import ReactionPredicate

from sixMans.embeds import (
    BlueEmbed,
    ErrorEmbed,
    ExceptionErrorEmbed,
    QueueNotFoundEmbed,
    SuccessEmbed,
)
from sixMans.enums import GameMode, GameState, Winner
from sixMans.game import Game
from sixMans.models.game import GameData
from sixMans.models.queue import QueueData
from sixMans.queue import SixMansQueue
from sixMans.strings import Strings
from sixMans.types import PlayerScore, PlayerStats, SixMansConfig, QueueBan
from sixMans.views.cancel import CancelView, ForceCancelView
from sixMans.views.score import ForceResultView, ScoreReportView

log = logging.getLogger("red.sixMans")

DEBUG = False
MINIMUM_GAME_TIME = 300  # Seconds (5 Minutes)
PLAYER_TIMEOUT_TIME = 10 if DEBUG else 1800  # How long players can be in a queue in seconds (4 Hours)
LOOP_TIME = 5  # How often to check the queues in seconds
VERIFY_TIMEOUT = 30  # How long someone has to react to a prompt (seconds)
CHANNEL_SLEEP_TIME = 5 if DEBUG else 30  # How long channels will persist after a game's score has been reported (seconds)


defaults = SixMansConfig(
    CategoryChannel=None,
    HelperRole=None,
    AutoMove=False,
    ReactToVote=True,
    QLobby=None,
    DefaultTeamSelection=GameMode.VOTE,
    DefaultQueueMaxSize=6,
    PlayerTimeout=PLAYER_TIMEOUT_TIME,
    Games={},
    Queues={},
    GamesPlayed=0,
    Players={},
    Scores=[],
    QueuesEnabled=True,
    QueueBans={},
)


class SixMans(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.config = Config.get_conf(self, identifier=1234567896, force_registration=True)
        self.config.register_guild(**defaults)
        self.queues: dict[discord.Guild, list[SixMansQueue]] = {}
        self.games: dict[discord.Guild, list[Game]] = {}
        self.queueMaxSize: dict[discord.Guild, int] = {}
        self.player_timeout_time: dict[discord.Guild, int] = {}
        self.queues_enabled: dict[discord.Guild, bool] = {}

        self.timeout_tasks = {}

    @commands.Cog.listener()
    async def on_ready(self):
        """Load saved game data on startup"""
        log.debug("In on_ready()")
        await self._load_guild_data()
        await self._load_queues()
        await self._load_games()

    async def cog_load(self):
        """Load saved game data on startup"""
        log.debug("In cog_load()")
        await self._load_guild_data()
        await self._load_queues()
        await self._load_games()

    async def cog_unload(self):
        """Clean up when cog shuts down."""
        log.debug("In cog_unload()")
        for tasks in self.timeout_tasks.values():
            for timeout_task in tasks.values():
                timeout_task.cancel()
        for guild in self.bot.guilds:
            log.info(f"[{guild.name}] Saving games")
            await self._save_games(guild, self.games[guild])

    # region listeners
    @commands.Cog.listener("on_guild_channel_delete")
    async def on_guild_channel_delete(self, channel):
        """
        If a queue channel is deleted, removes it from the queue class instance.

        If the last queue channel is deleted, the channel is replaced.
        """  # noqa: E501
        # TODO: Error catch if Q Lobby VC is deleted
        if not isinstance(channel, discord.TextChannel):
            return
        queue = None

        for q in self.queues[channel.guild]:
            if channel in q.channels:
                q.channels.remove(channel)
                queue = q
                break

        # No queue related to channel
        if not queue:
            return

        if queue.channels:
            return

        clone = await channel.clone()
        helper_role = await self._helper_role(channel.guild)
        helper_ping = " {}".format(helper_role.mention) if helper_role else ""
        await clone.send(f":grey_exclamation:{helper_ping} This channel has been created because the last textChannel for the **{queue.name}** queue has been deleted.")
        queue.channels.append(clone)
        await self._save_queues(channel.guild, self.queues[channel.guild])

    # endregion

    # region commands

    # region admin commands
    @commands.guild_only()
    @commands.command()
    @checks.admin_or_permissions(manage_guild=True)
    async def clearSixMansData(self, ctx: Context):
        if not ctx.guild:
            return

        msg = await ctx.send(f"{ctx.author.mention} Please verify that you wish to clear **all** of the {self.queueMaxSize[ctx.guild]} Mans data for the guild.")
        start_adding_reactions(msg, ReactionPredicate.YES_OR_NO_EMOJIS)

        pred = ReactionPredicate.yes_or_no(msg, ctx.author)
        await ctx.bot.wait_for("reaction_add", check=pred)
        if pred.result:
            # await self.config.clear_all_guilds()
            await self._clear_all_data(ctx.guild)
            await ctx.send("Done")
        else:
            await ctx.send(":x: Data **not** cleared.")

    @commands.guild_only()
    @commands.command()
    @checks.admin_or_permissions(manage_guild=True)
    async def preLoadData(self, ctx: Context):
        """Reloads all data for the 6mans cog"""
        await self._load_guild_data()
        await self._load_queues()
        await self._load_games()
        await ctx.send("Done")

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
                return ctx.send(embed=ErrorEmbed(description=f"{c} is not a valid text channel."))
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
            {},
            0,
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
        """Sets the team selection mode for a specific queue"""
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
    @commands.command(aliases=["setQTimeout", "setQTO", "sqto"])
    @checks.admin_or_permissions()
    async def setQueueTimeout(self, ctx: Context, minutes: int):
        """Sets the player timeout in seconds for queues in the guild (Default: 30m) ."""
        if not ctx.guild:
            return

        seconds = minutes * 60
        await self._save_player_timeout(ctx.guild, seconds)
        self.player_timeout_time[ctx.guild] = seconds
        s_if_plural = "" if minutes == 1 else "s"
        await ctx.send(
            embed=BlueEmbed(
                title="Queue Timeout",
                description=f"Players in Six Mans Queues will now be timed out after **{minutes} minute{s_if_plural}**.",
            )
        )

    @commands.guild_only()
    @commands.command(aliases=["getQTO", "gqto", "qto"])
    async def getQueueTimeout(self, ctx: Context):
        """Gets the player timeout in minutes for queues in the guild (Default: 240)."""
        if not ctx.guild:
            return

        seconds = await self._player_timeout(ctx.guild)
        minutes = seconds // 60
        s_if_plural = "" if minutes == 1 else "s"
        await ctx.send(
            embed=BlueEmbed(
                title="Queue Timeout",
                description=f"Players in Six Mans Queues are timed out after **{minutes} minute{s_if_plural}**.",
            )
        )

    @commands.guild_only()
    @commands.command(
        aliases=[
            "setDefaultQueueSize",
            "setDefaultQMaxSize",
            "setDefaultQMS",
            "setDQMS",
            "sdqms",
        ]
    )
    @checks.admin_or_permissions()
    async def setDefaultQueueMaxSize(self, ctx: Context, max_size: int):
        """
        Sets the default queue max size for the guild.

        This will not change the queue max size for any queues. (Default: 6)
        """  # noqa: E501
        if not ctx.guild:
            return

        if max_size <= 2:
            return await ctx.send(embed=ErrorEmbed(description="Queues sizes must be 2 or more players."))

        if max_size % 2 == 1:
            return await ctx.send(embed=ErrorEmbed(description="Queues sizes must be configured for an even number of players."))

        await self._save_queue_max_size(ctx.guild, max_size)

        if max_size == 2:
            await self._save_team_selection(ctx.guild, GameMode.RANDOM)

        await ctx.send("Done")

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
    @commands.command(aliases=["getDQMaxSize", "getDQMS", "gdqms", "dqms"])
    @checks.admin_or_permissions()
    async def getDefaultQueueMaxSize(self, ctx: Context):
        """Gets the max size for all queues in the guild. (Default: 6)"""
        if not ctx.guild:
            return

        guild_queue_size = await self._get_queue_max_size(ctx.guild)
        await ctx.send(
            embed=BlueEmbed(
                title="Default Queue Size",
                description=f"Current default queue size: **{guild_queue_size}**",
            )
        )

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
        await ctx.send("Done")

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

        expires = datetime.datetime.now(datetime.timezone.utc).timestamp() + (duration_minutes * 60)
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

        banned = self.check_banned(ctx.guild, player)
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

    # team selection
    @commands.guild_only()
    @commands.command(aliases=["fts"])
    async def forceTeamSelection(self, ctx: Context, mode: GameMode, game_id: int | None = None):
        """Forces a popped queue to restart a specified team selection.

        Format: `[p]fts <team_selection> [game_id]`"""
        if not ctx.guild:
            return

        if not isinstance(ctx.author, discord.Member):
            return

        if not isinstance(ctx.channel, discord.TextChannel):
            return

        if not await self.has_perms(ctx.author):
            return

        log.debug(f"Game Mode: {mode}")
        log.debug(f"Game ID: {game_id}")
        if game_id:
            game = self.get_game_by_id(ctx.guild, game_id)
            if not game:
                return await ctx.send(embed=ErrorEmbed(description=f"No active game found with ID: **{game_id}**"))
        else:
            game = self.get_game_by_text_channel(ctx.channel)
            if not game:
                return await ctx.send(embed=ErrorEmbed(description="No active game in this channel."))

        await game.textChannel.send(f"Processing Forced Team Selection: {mode}")
        await game.process_team_selection_method(team_selection=mode, force=True)

    @commands.guild_only()
    @commands.command(aliases=["fcg"])
    async def forceCancelGame(self, ctx: Context, gameId: int | None = None):
        """Cancel the current game. Can only be used in a game channel unless a gameId is given.
        The game will end with no points given to any of the players. The players with then be allowed to queue again.
        """
        if not ctx.guild:
            return

        if not isinstance(ctx.author, discord.Member):
            return

        if not isinstance(ctx.channel, discord.TextChannel):
            return

        if not await self.has_perms(ctx.author):
            return

        # game: Game | None = None
        if gameId:
            game = self.get_game_by_id(ctx.guild, gameId)
            if not game:
                return await ctx.send(embed=ErrorEmbed(description=f"No active game found with ID: **{gameId}**"))
        else:
            game = self.get_game_by_text_channel(ctx.channel)
            if not game:
                return await ctx.send(embed=ErrorEmbed(description="No active game in this channel."))

        cancel_view = ForceCancelView(author=ctx.author, game=game)
        await cancel_view.prompt()

        if await cancel_view.wait():
            return

        if not cancel_view.result:
            return

        game.state = GameState.CANCELLED
        await self._remove_game(ctx.guild, game)

    @commands.guild_only()
    @commands.command(aliases=["fr"])
    async def forceResult(self, ctx: Context):
        if not ctx.guild:
            return

        if not isinstance(ctx.author, discord.Member):
            return

        if not await self.has_perms(ctx.author):
            return

        game, six_mans_queue = await self.get_info(ctx)
        if game is None or six_mans_queue is None:
            return

        report_view = ForceResultView(author=ctx.author, game=game)
        await report_view.prompt()
        if await report_view.wait():
            return

        if report_view.cancelled:
            return

        if report_view.result == Winner.PENDING:
            return await ctx.send(embed=ErrorEmbed(description="Error reporting game result. Winner was not selected. Please reach out for support."))

        await game.report_winner(report_view.result)
        await self._finish_game(ctx.guild, game, six_mans_queue, report_view.result)

    # endregion

    # region player commands
    @commands.guild_only()
    @commands.command(aliases=["smMove", "moveme"])
    async def moveMe(self, ctx: Context):
        if not ctx.guild:
            return

        player = ctx.author
        if not isinstance(player, discord.Member):
            return

        if not isinstance(ctx.channel, discord.TextChannel):
            return

        if not isinstance(ctx.message.channel, discord.TextChannel):
            return

        if ctx.message.channel.category != await self._category(ctx.guild):
            return False

        game = self.get_game_by_text_channel(ctx.channel)
        if not game:
            return await ctx.send(
                f"{player.mention}, you are not in a game or must run this command from the lobby channel.",
                allowed_mentions=discord.AllowedMentions(users=True),
            )

        if not player.voice:
            return await ctx.send(
                f"{player.mention}, you must be connected to a voice channel to be moved to your team channel.",
                allowed_mentions=discord.AllowedMentions(users=True),
            )

        try:
            if player in game.blue:
                await player.move_to(game.voiceChannels[0])
            else:
                await player.move_to(game.voiceChannels[1])
        except (
            discord.Forbidden,
            discord.HTTPException,
            discord.NotFound,
            TypeError,
        ) as exc:
            await ctx.send(embed=ExceptionErrorEmbed(exc_message=str(exc)))

    @commands.guild_only()
    @commands.command(aliases=["li", "gameInfo", "gi"])
    async def lobbyInfo(self, ctx: Context):
        """Gets lobby info for the series that you are involved in"""
        if not ctx.guild:
            return

        if not isinstance(ctx.channel, discord.TextChannel):
            return

        if ctx.channel.category != await self._category(ctx.guild):
            return False

        game = self.get_game_by_text_channel(ctx.channel)
        if game:
            await game.post_lobby_info()

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
    @commands.command(aliases=["cg"])
    async def cancelGame(self, ctx: Context):
        """Cancel the current game. Can only be used in a game channel.
        The game will end with no points given to any of the players. The players with then be allowed to queue again.
        """
        if not ctx.guild:
            return

        if not isinstance(ctx.channel, discord.TextChannel):
            return

        if not isinstance(ctx.author, discord.Member):
            return

        game = self.get_game_by_text_channel(ctx.channel)
        if game is None:
            return await ctx.send(embed=ErrorEmbed(description="This command can only be used in a private game channel."))

        cancel_view = CancelView(game=game)
        await cancel_view.prompt()
        if await cancel_view.wait():
            return

        if not cancel_view.result:
            return

        await self._remove_game(ctx.guild, game)

    @commands.guild_only()
    @commands.command(aliases=["sr", "reportScore"])
    async def scoreReport(self, ctx: Context):
        """Report which team won the series. Can only be used in a game channel.
        Only valid after 10 minutes have passed since the game started. Both teams will need to verify the results.

        `winning_team` must be either `Blue` or `Orange`"""  # noqa: E501

        if not ctx.guild:
            return

        if not isinstance(ctx.channel, discord.TextChannel):
            return

        msg_created_at = ctx.message.created_at
        channel_created_at = ctx.channel.created_at
        game_time = msg_created_at - channel_created_at

        if game_time.seconds < MINIMUM_GAME_TIME:
            await ctx.send(
                f":x: You can't report a game outcome until at least **5 minutes** have passed since the game was created.\nCurrent time that's passed = **{game_time.seconds // 60} minute(s)**"
            )
            return

        game, six_mans_queue = await self.get_info(ctx)
        if game is None or six_mans_queue is None:
            return

        if game.winner != Winner.PENDING:
            return await ctx.send(
                embed=BlueEmbed(
                    title="Already Reported",
                    description=f"The game result has already been reported.\n\nWinner: {game.winner}",
                )
            )

        if ctx.author not in game.captains:
            return await ctx.send(embed=ErrorEmbed(description="Only game captains can report the score."))

        # Prompt for winner
        report_view = ScoreReportView(game=game)
        await report_view.prompt()
        if await report_view.wait():
            return

        if report_view.cancelled:
            return

        winner = report_view.result
        log.debug(f"Game Winner: {winner}")

        # Something went wrong during reporting.
        if winner == Winner.PENDING:
            log.error(f"[{game.id}] Game winner was confirmed as PENDING.")
            helper_role = await self._helper_role(ctx.guild)
            if helper_role:
                desc = f"Score report vote did not succeed. If you believe this is an error, please ping {helper_role.mention}"
            else:
                desc = "Score report vote did not succeed. If you believe this is an error, please reach out for support."
            return await ctx.reply(embed=ErrorEmbed(description=desc))

        await game.report_winner(winner)
        await self._finish_game(ctx.guild, game, six_mans_queue, winner)

    @commands.guild_only()
    @commands.command(aliases=["moreinfo", "mi"])
    async def moreInfo(self, ctx: Context):
        """Provides more in-depth information regarding the Six Mans series"""
        if not ctx.guild:
            return

        if not isinstance(ctx.channel, discord.TextChannel):
            return

        game = self.get_game_by_text_channel(ctx.channel)
        if game is None:
            return await ctx.send(embed=ErrorEmbed(description="Not a valid game channel."))
        await game.post_more_lobby_info()

    # region leaderboard commands

    @commands.guild_only()
    @commands.group(aliases=["qlb"])
    async def queueLeaderBoard(self, ctx: Context):
        """
        Get the top ten players in points for the specific queue.

        If no queue name is given the list will be the top ten players across all queues.
        If you're not in the top ten your name and rank will be shown at the bottom of the list.
        """  # noqa: E501

    @commands.guild_only()
    @queueLeaderBoard.command(aliases=["all-time", "alltime"])
    async def overall(self, ctx: Context, *, queue_name: str | None = None):
        """All-time leader board"""
        if not ctx.guild:
            return

        players = None
        queue = self.get_queue_by_name(ctx.guild, queue_name) if queue_name else None
        queue_name = queue.name if queue else ctx.guild.name

        if queue:
            players = queue.players
            games_played = queue.gamesPlayed
        else:
            players = await self._players(ctx.guild)
            games_played = await self._games_played(ctx.guild)

        if games_played == 0:
            await ctx.send(f":x: No games have been played in {queue_name}")
            return

        if not players:
            await ctx.send(f":x: Queue leaderboard not available for {queue_name}")
            return

        sorted_players = self._sort_player_dict(players)
        await ctx.send(embed=await self.embed_leaderboard(ctx, sorted_players, queue_name, games_played, "All-time"))

    @commands.guild_only()
    @queueLeaderBoard.command(aliases=["daily"])
    async def day(self, ctx: Context, *, queue_name: str | None = None):
        """Daily leader board. All games from the last 24 hours will count"""
        if not ctx.guild:
            return

        scores = await self._scores(ctx.guild)

        queue = None
        if queue_name:
            queue = self.get_queue_by_name(ctx.guild, queue_name)

        queue_id = queue.id if queue else None
        queue_name = queue.name if queue else ctx.guild.name
        day_ago = datetime.datetime.now() - datetime.timedelta(days=1)
        players, games_played = self._filter_scores(ctx.guild, scores, day_ago, queue_id)

        if games_played == 0:
            await ctx.send(f":x: No games have been played in {queue_name}")
            return

        if not players:
            await ctx.send(f":x: Queue leaderboard not available for {queue_name}")
            return

        sorted_players = self._sort_player_dict(players)
        await ctx.send(embed=await self.embed_leaderboard(ctx, sorted_players, queue_name, games_played, "Daily"))

    @commands.guild_only()
    @queueLeaderBoard.command(aliases=["weekly", "wk"])
    async def week(self, ctx: Context, *, queue_name: str | None = None):
        """Weekly leader board. All games from the last week will count"""
        if not ctx.guild:
            return

        scores = await self._scores(ctx.guild)

        queue = self.get_queue_by_name(ctx.guild, queue_name) if queue_name else None
        queue_id = queue.id if queue else None
        week_ago = datetime.datetime.now() - datetime.timedelta(weeks=1)
        players, games_played = self._filter_scores(ctx.guild, scores, week_ago, queue_id)

        if games_played == 0:
            await ctx.send(f":x: No games have been played in {queue_name}")
            return

        if not players:
            await ctx.send(f":x: Queue leaderboard not available for {queue_name}")
            return

        queue_name = queue.name if queue else ctx.guild.name
        sorted_players = self._sort_player_dict(players)
        await ctx.send(embed=await self.embed_leaderboard(ctx, sorted_players, queue_name, games_played, "Weekly"))

    @commands.guild_only()
    @queueLeaderBoard.command(aliases=["monthly", "mnth"])
    async def month(self, ctx: Context, *, queue_name: str | None = None):
        """Monthly leader board. All games from the last 30 days will count"""
        if not ctx.guild:
            return

        scores = await self._scores(ctx.guild)

        queue = self.get_queue_by_name(ctx.guild, queue_name) if queue_name else None
        queue_id = queue.id if queue else None
        month_ago = datetime.datetime.now() - datetime.timedelta(days=30)
        players, games_played = self._filter_scores(ctx.guild, scores, month_ago, queue_id)

        if games_played == 0:
            await ctx.send(f":x: No games have been played in {queue_name}")
            return

        if not players:
            await ctx.send(f":x: Queue leaderboard not available for {queue_name}")
            return

        queue_name = queue.name if queue else ctx.guild.name
        sorted_players = self._sort_player_dict(players)
        await ctx.send(embed=await self.embed_leaderboard(ctx, sorted_players, queue_name, games_played, "Monthly"))

    @commands.guild_only()
    @queueLeaderBoard.command(aliases=["yearly", "yr"])
    async def year(self, ctx: Context, *, queue_name: str | None = None):
        """Yearly leader board. All games from the last 365 days will count"""
        if not ctx.guild:
            return

        scores = await self._scores(ctx.guild)

        queue = self.get_queue_by_name(ctx.guild, queue_name) if queue_name else None
        queue_id = queue.id if queue else None
        year_ago = datetime.datetime.now() - datetime.timedelta(days=365)
        players, games_played = self._filter_scores(ctx.guild, scores, year_ago, queue_id)

        if games_played == 0:
            await ctx.send(f":x: No games have been played in {queue_name}")
            return

        if not players:
            await ctx.send(f":x: Queue leaderboard not available for {queue_name}")
            return

        queue_name = queue.name if queue else ctx.guild.name
        sorted_players = self._sort_player_dict(players)
        await ctx.send(embed=await self.embed_leaderboard(ctx, sorted_players, queue_name, games_played, "Yearly"))

    # endregion

    # region rank commands

    @commands.guild_only()
    @commands.group(aliases=["rnk", "playerCard", "pc"])
    async def rank(self, ctx: Context):
        """
        Get your rank in points, wins, and games played for the specific queue.

        If no queue name is given it will show your overall rank across all queues.
        """  # noqa: E501

    @commands.guild_only()
    @rank.command(aliases=["all-time", "overall"])
    async def alltime(
        self,
        ctx: Context,
        player: discord.Member | None = None,
        *,
        queue_name: str | None = None,
    ):
        """All-time ranks"""
        if not ctx.guild:
            return

        if not isinstance(ctx.author, discord.Member):
            return

        queue = None
        if queue_name:
            queue = self.get_queue_by_name(ctx.guild, queue_name)
            players = queue.players
        else:
            players = await self._players(ctx.guild)
            queue_name = ctx.guild.name

        if not players:
            await ctx.send(f":x: Player ranks not available for {queue_name}")
            return

        queue_max_size = queue.maxSize if queue else self.queueMaxSize[ctx.guild]
        sorted_players = self._sort_player_dict(players)
        player = player if player else ctx.author
        await ctx.send(embed=self.embed_rank(player, sorted_players, queue_name, queue_max_size, "All-time"))

    @commands.guild_only()
    @rank.command(aliases=["day"])
    async def daily(
        self,
        ctx: Context,
        player: discord.Member | None = None,
        *,
        queue_name: str | None = None,
    ):
        """Daily ranks. All games from the last 24 hours will count"""
        if not ctx.guild:
            return

        if not isinstance(ctx.author, discord.Member):
            return

        scores = await self._scores(ctx.guild)

        queue = self.get_queue_by_name(ctx.guild, queue_name) if queue_name else None
        queue_id = queue.id if queue else None
        day_ago = datetime.datetime.now() - datetime.timedelta(days=1)
        players = self._filter_scores(ctx.guild, scores, day_ago, queue_id)[0]
        queue_name = queue.name if queue else ctx.guild.name

        if not players:
            await ctx.send(f":x: Player ranks not available for {queue_name}")
            return

        queue_max_size = queue.maxSize if queue else self.queueMaxSize[ctx.guild]
        sorted_players = self._sort_player_dict(players)
        player = player if player else ctx.author
        await ctx.send(embed=self.embed_rank(player, sorted_players, queue_name, queue_max_size, "Daily"))

    @commands.guild_only()
    @rank.command(aliases=["week", "wk"])
    async def weekly(
        self,
        ctx: Context,
        player: discord.Member | None = None,
        *,
        queue_name: str | None = None,
    ):
        """Weekly ranks. All games from the last week will count"""
        if not ctx.guild:
            return

        if not isinstance(ctx.author, discord.Member):
            return

        scores = await self._scores(ctx.guild)

        queue = self.get_queue_by_name(ctx.guild, queue_name) if queue_name else None
        queue_id = queue.id if queue else None
        week_ago = datetime.datetime.now() - datetime.timedelta(weeks=1)
        players = self._filter_scores(ctx.guild, scores, week_ago, queue_id)[0]
        queue_name = queue.name if queue else ctx.guild.name

        if not players:
            await ctx.send(f":x: Player ranks not available for {queue_name}")
            return

        queue_max_size = queue.maxSize if queue else self.queueMaxSize[ctx.guild]
        sorted_players = self._sort_player_dict(players)
        player = player if player else ctx.author
        await ctx.send(embed=self.embed_rank(player, sorted_players, queue_name, queue_max_size, "Weekly"))

    @commands.guild_only()
    @rank.command(aliases=["month", "mnth"])
    async def monthly(
        self,
        ctx: Context,
        player: discord.Member | None = None,
        *,
        queue_name: str | None = None,
    ):
        """Monthly ranks. All games from the last 30 days will count"""
        if not ctx.guild:
            return

        if not isinstance(ctx.author, discord.Member):
            return

        scores = await self._scores(ctx.guild)

        queue = self.get_queue_by_name(ctx.guild, queue_name) if queue_name else None
        queue_id = queue.id if queue else None
        month_ago = datetime.datetime.now() - datetime.timedelta(days=30)
        players = self._filter_scores(ctx.guild, scores, month_ago, queue_id)[0]
        queue_name = queue.name if queue else ctx.guild.name

        if not players:
            await ctx.send(f":x: Player ranks not available for {queue_name}")
            return

        queue_max_size = queue.maxSize if queue else self.queueMaxSize[ctx.guild]
        sorted_players = self._sort_player_dict(players)
        player = player if player else ctx.author
        await ctx.send(embed=self.embed_rank(player, sorted_players, queue_name, queue_max_size, "Monthly"))

    @commands.guild_only()
    @rank.command(aliases=["year", "yr"])
    async def yearly(
        self,
        ctx: Context,
        player: discord.Member | None = None,
        *,
        queue_name: str | None = None,
    ):
        """Yearly ranks. All games from the last 365 days will count"""
        if not ctx.guild:
            return

        if not isinstance(ctx.author, discord.Member):
            return

        scores = await self._scores(ctx.guild)

        queue = self.get_queue_by_name(ctx.guild, queue_name) if queue_name else None
        queue_id = queue.id if queue else None
        year_ago = datetime.datetime.now() - datetime.timedelta(days=365)
        players = self._filter_scores(ctx.guild, scores, year_ago, queue_id)[0]
        queue_name = queue.name if queue else ctx.guild.name

        if not players:
            await ctx.send(f":x: Player ranks not available for {queue_name}")
            return

        queue_max_size = queue.maxSize if queue else self.queueMaxSize[ctx.guild]
        sorted_players = self._sort_player_dict(players)
        player = player if player else ctx.author
        await ctx.send(embed=self.embed_rank(player, sorted_players, queue_name, queue_max_size, "Yearly"))

    # endregion

    # region get and set commands

    @commands.guild_only()
    @commands.command(aliases=["cq", "status"])
    async def checkQueue(self, ctx: Context):
        if not isinstance(ctx.channel, discord.TextChannel):
            return

        six_mans_queue = self.get_queue_by_text_channel(ctx.channel)
        if not six_mans_queue:
            await ctx.send(":x: No queue set up in this channel")
            return
        await ctx.send(embed=self.embed_queue_players(six_mans_queue))

    @commands.guild_only()
    @commands.command(aliases=["setQLobby", "setQVC"])
    @checks.admin_or_permissions(manage_guild=True)
    async def setQueueLobby(self, ctx: Context, lobby_voice: discord.VoiceChannel):
        # TODO: Consider having the queues save the Queue Lobby VC
        if not ctx.guild:
            return

        for queue in self.queues[ctx.guild]:
            queue.lobby_vc = lobby_voice
        await self._save_q_lobby_vc(ctx.guild, lobby_voice.id)
        await self._save_queues(ctx.guild, self.queues[ctx.guild])
        await ctx.send("Done")

    @commands.guild_only()
    @commands.command(aliases=["unsetQueueLobby, unsetQLobby", "clearQLobby"])
    @checks.admin_or_permissions(manage_guild=True)
    async def clearQueueLobby(self, ctx: Context):
        if not ctx.guild:
            return

        await self._save_q_lobby_vc(ctx.guild, None)
        await ctx.send("Done")

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
                    await ctx.send(embed=self.embed_queue_info(queue, await self._get_q_lobby_vc(ctx.guild)))
                    return
            await ctx.send(f":x: No queue set up with name: {queue_name}")
            return

        six_mans_queue = self.get_queue_by_text_channel(ctx.channel)
        if not six_mans_queue:
            await ctx.send(":x: No queue set up in this channel")
            return

        await ctx.send(embed=self.embed_queue_info(six_mans_queue, await self._get_q_lobby_vc(ctx.guild)))

    @commands.guild_only()
    @commands.command()
    @checks.admin_or_permissions(manage_guild=True)
    async def toggleAutoMove(self, ctx: Context):
        """Toggle whether or not bot moves members to their assigned team voice channel"""
        if not ctx.guild:
            return

        new_automove_status = not await self._get_automove(ctx.guild)
        await self._save_automove(ctx.guild, new_automove_status)

        action = "will move" if new_automove_status else "will not move"
        message = f"Popped {self.queueMaxSize[ctx.guild]} Mans queues **{action}** members to their team voice channel."
        await ctx.send(message)

    @commands.guild_only()
    @commands.command(aliases=["toggleReactToVote", "tvm", "trtv"])
    @checks.admin_or_permissions(manage_guild=True)
    async def toggleVoteMethod(self, ctx: Context):
        """Toggles team selection voting method between commands and reactions."""
        if not ctx.guild:
            return

        react_to_vote = not await self._is_react_to_vote(ctx.guild)
        await self._save_react_to_vote(ctx.guild, react_to_vote)

        action = "reactions" if react_to_vote else "commands"
        message = f"Members of popped {self.queueMaxSize[ctx.guild]} Mans queues will vote for team reactions with **{action}**."
        await ctx.send(message)

    @commands.guild_only()
    @commands.command(aliases=["setTeamSelection"])
    @checks.admin_or_permissions(manage_guild=True)
    async def setDefaultTeamSelection(self, ctx: Context, team_selection_method):
        """
        Set method for Six Mans team selection (Default: Vote)

        Valid team selection methods options:
        - **Random**: selects random teams
        - **Captains**: selects a captain for each team
        - **Vote**: players vote for team selection method after queue pops
        - **Balanced**: creates balanced teams from all participating players
        """  # noqa: E501
        # TODO: Support Captains [captains random, captains shuffle], Balanced
        if not ctx.guild:
            return

        if await self._get_queue_max_size(ctx.guild) == 2:
            return await ctx.send(":x: You may not change team selection method when default queue max size is 2.")

        try:
            ts = GameMode(team_selection_method)
            await self._save_team_selection(ctx.guild, ts)
            await ctx.send("Done.")
        except ValueError:
            return await ctx.send(f"**{team_selection_method}** is not a valid method of team selection.")

    @commands.guild_only()
    @commands.command(aliases=["getTeamSelection"])
    @checks.admin_or_permissions(manage_guild=True)
    async def getDefaultTeamSelection(self, ctx: Context):
        """Get method for Six Mans team selection (Default: Random)"""
        if not ctx.guild:
            return

        team_selection = await self._team_selection(ctx.guild)
        await ctx.send(f"Six Mans team selection is currently set to **{team_selection}**.")

    @commands.guild_only()
    @commands.command()
    @checks.admin_or_permissions(manage_guild=True)
    async def setCategory(self, ctx: Context, category_channel: discord.CategoryChannel):
        """Sets the category channel where all game channels will be created under"""
        if not ctx.guild:
            return

        for queue in self.queues[ctx.guild]:
            queue.category = category_channel
        await self._save_category(ctx.guild, category_channel.id)
        await self._save_queues(ctx.guild, self.queues[ctx.guild])
        await ctx.send("Done")

    @commands.guild_only()
    @commands.command()
    @checks.admin_or_permissions(manage_guild=True)
    async def getCategory(self, ctx: Context):
        """Gets the channel currently assigned as the transaction channel"""
        if not ctx.guild:
            return

        category = await self._category(ctx.guild)
        category_fmt = category.mention if category else "None"

        await ctx.send(f"{self.queueMaxSize[ctx.guild]} Mans category channel set to: {category_fmt}")

    @commands.guild_only()
    @commands.command()
    @checks.admin_or_permissions(manage_guild=True)
    async def unsetCategory(self, ctx: Context):
        """Unsets the category channel. Game channels will not be created if this is not set"""
        if not ctx.guild:
            return

        category = await self._category(ctx.guild)
        old_helper_role = await self._helper_role(ctx.guild)
        if old_helper_role and category:
            await category.set_permissions(old_helper_role, overwrite=None)
        await self._save_category(ctx.guild, None)
        await ctx.send("Done")

    @commands.guild_only()
    @commands.command()
    @checks.admin_or_permissions(manage_guild=True)
    async def setHelperRole(self, ctx: Context, helper_role: discord.Role):
        """Sets the 6 Mans helper role. Anyone with this role will be able to see all the game channels that are created"""
        if not ctx.guild:
            return

        await self._save_helper_role(ctx.guild, helper_role.id)
        category = await self._category(ctx.guild)

        if not category:
            await ctx.reply("Six mans category channel is not configured.")
            return

        await category.set_permissions(helper_role, read_messages=True, manage_channels=True, connect=True)
        await ctx.send("Done")

    @commands.guild_only()
    @commands.command()
    @checks.admin_or_permissions(manage_guild=True)
    async def getHelperRole(self, ctx: Context):
        """Gets the role currently assigned as the 6 Mans helper role"""
        if not ctx.guild:
            return

        try:
            await ctx.send(f"{self.queueMaxSize[ctx.guild]} Mans helper role set to: {(await self._helper_role(ctx.guild)).name}")
        except AttributeError:
            await ctx.send(f":x: {self.queueMaxSize[ctx.guild]} mans helper role not set")

    @commands.guild_only()
    @commands.command()
    @checks.admin_or_permissions(manage_guild=True)
    async def unsetHelperRole(self, ctx: Context):
        """Unsets the 6 Mans helper role."""
        if not ctx.guild:
            return

        category = await self._category(ctx.guild)
        old_helper_role = await self._helper_role(ctx.guild)
        if old_helper_role and category:
            await category.set_permissions(old_helper_role, overwrite=None)
        await self._save_helper_role(ctx.guild, None)
        await ctx.send("Done")

    @commands.guild_only()
    @commands.command(aliases=["cag"])
    async def checkActiveGames(self, ctx: Context):
        if not ctx.guild:
            return

        if not isinstance(ctx.author, discord.Member):
            return

        if not await self.has_perms(ctx.author):
            return

        queueGames: dict[int, list[Game]] = {}
        for game in self.games[ctx.guild]:
            queueGames.setdefault(game.queue.id, []).append(game)

        embed = self.embed_active_games(ctx.guild, queueGames)
        await ctx.channel.send(embed=embed)

    # endregion

    # endregion

    # region helper methods

    async def check_banned(self, guild: discord.Guild, player: discord.Member) -> QueueBan | None:
        bans = await self._get_queue_bans(guild)
        ban = bans.get(str(player.id))
        if not ban:
            return None

        now = datetime.datetime.now(datetime.timezone.utc).timestamp()
        if ban["expires"] <= now:
            await self._remove_queue_ban(guild, player.id)
            return None

        return ban

    async def expire_bans(self, guild: discord.Guild):
        log.debug("Expiring all bans for guild: %d", guild.id)
        bans = await self._get_queue_bans(guild)

        # Clean expired bans
        now = datetime.datetime.now(datetime.timezone.utc).timestamp()
        expired = [pid for pid, ban in bans.items() if ban["expires"] <= now]
        for pid in expired:
            await self._remove_queue_ban(guild, pid)

    async def has_perms(self, member: discord.Member):
        # Admins
        if member.guild_permissions.manage_guild:
            return True

        # Helpers
        helper_role = await self._helper_role(member.guild)
        if helper_role and helper_role in member.roles:
            return True

        # Default to no permissions
        return False

    async def _add_to_queue(self, player: discord.Member, six_mans_queue: SixMansQueue):
        six_mans_queue._put(player)
        embed = self.embed_player_added(player, six_mans_queue)
        try:
            await six_mans_queue.send_message(embed=embed)
        except Exception as exc:
            log.debug(f"Exception adding {player.name} to queue: {exc}")
            raise exc

        timeout = self.player_timeout_time.get(six_mans_queue.guild, PLAYER_TIMEOUT_TIME)

        await self.create_timeout_task(player, six_mans_queue, timeout)

    async def _remove_from_queue(self, player: discord.Member, six_mans_queue: SixMansQueue):
        with contextlib.suppress(ValueError):
            six_mans_queue._remove(player)
        embed = self.embed_player_removed(player, six_mans_queue)
        await six_mans_queue.send_message(embed=embed)
        await self.remove_timeout_task(player, six_mans_queue)

    async def get_visble_queue_channel(self, six_mans_queue: SixMansQueue, player: discord.Member):
        for channel in six_mans_queue.channels:
            if player in channel.members:
                return channel
        return None

    async def _auto_remove_from_queue(self, player: discord.Member, six_mans_queue: SixMansQueue):
        if player not in six_mans_queue.queue:
            return

        # Remove player from queue
        await self._remove_from_queue(player, six_mans_queue)

        # Send Player Message
        auto_remove_msg = f"You have been timed out from the **{six_mans_queue.name} {six_mans_queue.maxSize} Mans queue**. You'll need to use the queue command again if you wish to play some more."
        channel = await self.get_visble_queue_channel(six_mans_queue, player)

        try:
            invite_msg = f"\n\nYou may return to {channel.mention} to rejoin the queue!"
            embed = discord.Embed(
                title=f"{six_mans_queue.guild.name}: {six_mans_queue.maxSize} Mans Timeout",
                description=auto_remove_msg + invite_msg,
                color=discord.Color.red(),
            )
            if six_mans_queue.guild.icon:
                embed.set_thumbnail(url=six_mans_queue.guild.icon.url)
            await player.send(embed=embed)
        except (discord.HTTPException, discord.Forbidden) as exc:
            log.exception(f"Error sending message to player: {player.display_name}", exc_info=exc)
            pass

    async def create_timeout_task(
        self,
        player: discord.Member,
        six_mans_queue: SixMansQueue,
        time=PLAYER_TIMEOUT_TIME,
    ):
        self.timeout_tasks.setdefault(player, {})
        self.timeout_tasks[player][six_mans_queue] = asyncio.create_task(self.player_queue_timeout(player, six_mans_queue, time))

    async def player_queue_timeout(self, player: discord.Member, six_mans_queue: SixMansQueue, time=None):
        if not time:
            time = self.player_timeout_time[six_mans_queue.guild]

        await asyncio.sleep(time)
        await self._auto_remove_from_queue(player, six_mans_queue)

    async def cancel_timeout_task(self, player: discord.Member, six_mans_queue: SixMansQueue):
        with contextlib.suppress(KeyError):
            self.timeout_tasks[player][six_mans_queue].cancel()

        await self.remove_timeout_task(player, six_mans_queue)

    async def remove_timeout_task(self, player: discord.Member, six_mans_queue: SixMansQueue):
        with contextlib.suppress(KeyError):
            del self.timeout_tasks[player][six_mans_queue]
            if not self.timeout_tasks[player]:
                del self.timeout_tasks[player]

    async def _finish_game(
        self,
        guild: discord.Guild,
        game: Game,
        six_mans_queue: SixMansQueue,
        winning_team: Winner,
    ):
        winning_players: set[discord.Member] = set()
        losing_players: set[discord.Member] = set()
        match winning_team:
            case Winner.BLUE:
                winning_players = game.blue
                losing_players = game.orange
            case Winner.ORANGE:
                winning_players = game.orange
                losing_players = game.blue
            case Winner.PENDING:
                raise RuntimeError("Invalid result for game winner.")

        _scores = await self._scores(guild)
        _players = await self._players(guild)
        _games_played = await self._games_played(guild)
        date_time = datetime.datetime.now().strftime("%d-%b-%Y (%H:%M:%S.%f)")
        for player in winning_players:
            score = self._create_player_score(six_mans_queue, game, player, 1, date_time)
            self._give_points(six_mans_queue.players, score)
            self._give_points(_players, score)
            _scores.insert(0, score)
        for player in losing_players:
            score = self._create_player_score(six_mans_queue, game, player, 0, date_time)
            self._give_points(six_mans_queue.players, score)
            self._give_points(_players, score)
            _scores.insert(0, score)

        _games_played += 1
        six_mans_queue.gamesPlayed += 1

        await self._save_scores(guild, _scores)
        await self._save_queues(guild, self.queues[guild])
        await self._save_players(guild, _players)
        await self._save_games_played(guild, _games_played)

        if await self._get_automove(guild):  # game.automove not working?
            qlobby_vc = await self._get_q_lobby_vc(guild)
            if qlobby_vc and (game.voiceChannels and len(game.voiceChannels) == 2):
                await self._move_to_voice(qlobby_vc, game.voiceChannels[0].members)
                await self._move_to_voice(qlobby_vc, game.voiceChannels[1].members)

        await self._remove_game(guild, game)

    async def _move_to_voice(self, vc: discord.VoiceChannel, members: list[discord.Member]):
        for member in members:
            with contextlib.suppress(
                discord.Forbidden,
                discord.HTTPException,
                discord.NotFound,
            ):
                pass
                await member.move_to(vc)

    async def _remove_game(self, guild: discord.Guild, game: Game):
        """Remove game from active games and delete channels."""
        with contextlib.suppress(ValueError):
            self.games[guild].remove(game)
        await self._save_games(guild, self.games[guild])

        # Sleep before removal
        await asyncio.sleep(CHANNEL_SLEEP_TIME)
        q_lobby_vc = await self._get_q_lobby_vc(guild)

        # Delete game text channel
        if game.textChannel:
            try:
                await game.textChannel.delete()
            except Exception as exc:
                log.exception(f"Error deleting game channel {game.textChannel}", exc_info=exc)
                raise

        for vc in game.voiceChannels:
            # move players in game VC to general lobby VC
            if q_lobby_vc:
                with contextlib.suppress(
                    discord.Forbidden,
                    discord.HTTPException,
                    discord.NotFound,
                ):
                    for player in vc.members:
                        await player.move_to(q_lobby_vc)

            # Delete game VC
            try:
                await vc.delete()
            except (discord.Forbidden, discord.NotFound, discord.HTTPException) as exc:
                log.exception(f"Error deleting game voice channel {vc.name}", exc_info=exc)
                raise

    def _get_opposing_captain(self, player: discord.Member, game: Game):
        opposing_captain = None
        if game.state == GameState.NEW:
            players = list(game.players)
            if player not in players:
                return None
            players.remove(player)
            return random.choice(players)

        opposing_captain = None

        if player in game.blue:
            opposing_captain = game.captains[1]  # Orange team captain
        elif player in game.orange:
            opposing_captain = game.captains[0]  # Blue team captain
        return opposing_captain

    def _swap_opposing_captain(self, game: Game, opposing_captain):
        if opposing_captain in game.blue:
            game.captains[0] = random.sample(list(game.blue), 1)[0]  # Swap Blue team captain
        elif opposing_captain in game.orange:
            game.captains[1] = random.sample(list(game.orange), 1)[0]  # Swap Orange team captain

    def _give_points(self, players_dict: dict[str, PlayerStats], score: PlayerScore):
        player_id = score["Player"]
        points_earned = score["Points"]
        win = score["Win"]

        new_player = PlayerStats(Points=0, Wins=0, GamesPlayed=0)

        player_score = players_dict.get(str(player_id), new_player)
        player_score["Points"] = player_score["Points"] + points_earned
        player_score["GamesPlayed"] = player_score["GamesPlayed"] + 1
        player_score["Wins"] = player_score["Wins"] + win

    def _create_player_score(
        self,
        six_mans_queue: SixMansQueue,
        game: Game,
        player: discord.Member,
        win: int,
        date_time: str,
    ) -> PlayerScore:
        points_dict = six_mans_queue.points
        if win:
            points_earned = points_dict[Strings.PP_PLAY_KEY] + points_dict[Strings.PP_WIN_KEY]
        else:
            points_earned = points_dict[Strings.PP_PLAY_KEY]
        return PlayerScore(
            Game=game.id,
            Queue=six_mans_queue.id,
            Player=player.id,
            Win=win,
            Points=points_earned,
            DateTime=date_time,
        )

    def _filter_scores(self, guild, scores, start_date, queue_id):
        players: dict[str, PlayerStats] = {}
        valid_scores = 0
        for score in scores:
            date_time = datetime.datetime.strptime(score["DateTime"], "%d-%b-%Y (%H:%M:%S.%f)")
            if date_time > start_date and (queue_id is None or score["Queue"] == queue_id):
                self._give_points(players, score)
                valid_scores += 1
            else:
                break
        games_played = valid_scores // self.queueMaxSize[guild]
        return players, games_played

    def _sort_player_dict(self, player_dict):
        sorted_players = sorted(
            player_dict.items(),
            key=lambda x: x[1][Strings.PLAYER_WINS_KEY],
            reverse=True,
        )
        return sorted(sorted_players, key=lambda x: x[1][Strings.PLAYER_POINTS_KEY], reverse=True)

    async def _pop_queue(self, ctx: Context, six_mans_queue: SixMansQueue) -> bool:
        """Pop Queue"""
        if not ctx.guild:
            return False

        log.debug(f"Creating game. Guild: {ctx.guild.id} Queue: {six_mans_queue.name}")
        game = await self.create_game(ctx.guild, six_mans_queue, prefix=ctx.prefix)
        if game is None:
            return False

        # Remove players from any other queue they were in
        for player in game.players:
            for queue in self.queues[ctx.guild]:
                if player in queue.queue:
                    await self._remove_from_queue(player, queue)

        return True

    async def create_game(self, guild: discord.Guild, six_mans_queue: SixMansQueue, prefix="?"):
        if not six_mans_queue.queue_full():
            return None
        players = [six_mans_queue._get() for _ in range(six_mans_queue.maxSize)]

        await six_mans_queue.send_message(message="**Queue is full! Game is being created.**")

        game = Game(
            queue=six_mans_queue,
            players=players,
            helper_role=await self._helper_role(guild),
            automove=await self._get_automove(guild),
            prefix=prefix,
            save_callback=lambda: self._save_games(guild, self.games[guild]),
        )
        await game.create_game_channels(await self._category(guild))

        log.debug(f"Saving game: {game.id} Players: {game.players}")
        self.games[guild].append(game)
        await self._save_games(guild, self.games[guild])

        await game.process_team_selection_method()
        # Save again once teams are selected
        await self._save_games(guild, self.games[guild])
        return game

    async def get_info(self, ctx: Context) -> tuple[Game | None, SixMansQueue | None]:
        if not ctx.guild:
            return None, None

        if not isinstance(ctx.channel, discord.TextChannel):
            return None, None

        game = self.get_game_by_text_channel(ctx.channel)
        if game is None:
            await ctx.send(f":x: This command can only be used in a {self.queueMaxSize[ctx.guild]} mans game channel.")
            return None, None

        for queue in self.queues[ctx.guild]:
            if queue.id == game.queue.id:
                return game, queue

        await ctx.send(":x: Queue not found for this channel, please message an Admin if you think this is a mistake.")
        return None, None

    def is_valid_ts(self, team_selection) -> bool:
        try:
            GameMode(team_selection)
            return True
        except ValueError:
            return False

    def get_game_and_queue(self, channel: discord.TextChannel) -> tuple[Game, SixMansQueue] | None:
        game = self.get_game_by_text_channel(channel)
        if game:
            return game, game.queue
        else:
            return None

    def get_game_by_id(self, guild: discord.Guild, game_id: int) -> Game | None:
        log.debug(f"Fetching Game ID: {game_id}")
        for active_game in self.games[guild]:
            if active_game.id == game_id:
                return active_game
        return None

    def get_game_by_text_channel(self, channel: discord.TextChannel) -> Game | None:
        log.debug(f"Games: {self.games}")
        for game in self.games.get(channel.guild, []):
            if game.textChannel == channel:
                return game
        return None

    def get_queue_by_text_channel(self, channel: discord.TextChannel) -> SixMansQueue | None:
        for six_mans_queue in self.queues[channel.guild]:
            for queuechannel in six_mans_queue.channels:
                if queuechannel == channel:
                    return six_mans_queue
        return None

    def get_queue_by_name(self, guild: discord.Guild, queue_name: str) -> SixMansQueue | None:
        for queue in self.queues[guild]:
            if queue.name == queue_name:
                return queue
        return None

    # endregion

    # region embed and string format methods

    def embed_player_added(self, player: discord.Member, six_mans_queue: SixMansQueue):
        player_list = self.format_player_list(six_mans_queue)
        embed = discord.Embed(color=discord.Colour.green())
        player_icon = player.display_avatar.url
        embed.set_author(
            name=f"{player.display_name} added to the {six_mans_queue.name} queue. ({six_mans_queue.queue.qsize()}/{six_mans_queue.maxSize})",
            icon_url=player_icon,
        )
        embed.add_field(name="Players in Queue", value=player_list, inline=False)
        return embed

    def embed_player_removed(self, player: discord.Member, six_mans_queue: SixMansQueue):
        player_list = self.format_player_list(six_mans_queue)
        embed = discord.Embed(color=discord.Colour.red())
        embed.set_author(
            name=f"{player.display_name} removed from the {six_mans_queue.name} queue. ({six_mans_queue.queue.qsize()}/{six_mans_queue.maxSize})",
            icon_url=player.display_avatar.url,
        )
        embed.add_field(name="Players in Queue", value=player_list, inline=False)
        return embed

    def embed_queue_info(self, queue: SixMansQueue, default_lobby_vc=None):
        log.debug("")
        embed = discord.Embed(
            title=f"{queue.name} {queue.maxSize} Mans Info",
            color=discord.Colour.blue(),
        )
        embed.add_field(name="Team Selection", value=queue.teamSelection, inline=False)
        embed.add_field(
            name="Channels",
            value=f"{', '.join([channel.mention for channel in queue.channels])}\n",
            inline=False,
        )
        embed.add_field(
            name="Queue Size",
            value=queue.maxSize,
            inline=False,
        )

        if queue.lobby_vc:
            embed.add_field(name="Lobby VC", value=queue.lobby_vc, inline=False)
        elif default_lobby_vc:
            embed.add_field(name="Lobby VC", value=default_lobby_vc, inline=False)

        embed.add_field(name="Games Played", value=f"{queue.gamesPlayed}\n", inline=False)
        embed.add_field(
            name="Unique Players All-Time",
            value=f"{len(queue.players)}\n",
            inline=False,
        )
        embed.add_field(
            name="Point Breakdown",
            value=f"**Per Series Played:** {queue.points[Strings.PP_PLAY_KEY]}\n**Per Series Win:** {queue.points[Strings.PP_WIN_KEY]}",
            inline=False,
        )
        return embed

    def embed_queue_players(self, queue: SixMansQueue):
        player_list = self.format_player_list(queue)
        embed = discord.Embed(
            title=f"{queue.name} {queue.maxSize} Mans Queue",
            color=discord.Colour.blue(),
        )
        embed.add_field(
            name=f"Players in Queue ({len(queue.queue.queue)}/{queue.maxSize})",
            value=player_list,
            inline=False,
        )
        return embed

    def embed_active_games(self, guild, queueGames: dict[int, list[Game]]):
        embed = discord.Embed(
            title=f"{self.queueMaxSize[guild]} Mans Active Games",
            color=discord.Colour.blue(),
        )
        for queueId in queueGames:
            games = queueGames[queueId]
            queueName = next(queue.name for queue in self.queues[guild] if queue.id == queueId)
            embed.add_field(
                name=f"{queueName}:",
                value="\n".join([f"{str(game.id)}\n{', '.join([player.mention for player in game.players])}" for game in games]),
                inline=False,
            )
        return embed

    async def embed_leaderboard(self, ctx: Context, sorted_players, queue_name, games_played, lb_format) -> discord.Embed:
        if not ctx.guild:
            raise ValueError("Guild is not available in context for creating leaderboard embed.")

        embed = discord.Embed(
            title=f"{queue_name} {self.queueMaxSize[ctx.guild]} Mans {lb_format} Leaderboard",
            color=discord.Colour.blue(),
        )
        embed.add_field(name="Games Played", value=f"{games_played}\n", inline=True)
        embed.add_field(name="Unique Players", value=f"{len(sorted_players)}\n", inline=True)
        embed.add_field(name="⠀", value="⠀", inline=True)  # Blank field added to push the Player and Stats fields to a new line

        playerStrings = []
        statStrings = []
        for idx, player in enumerate(sorted_players):
            try:
                member: discord.Member = await commands.MemberConverter().convert(ctx, player[0])
            except (
                commands.MemberNotFound,
                commands.CommandError,
            ):
                log.warning(f":x: Can't find player with id: {player[0]}")
                continue

            player_info = player[1]
            playerStrings.append("`{0}` **{1:25s}:**".format(idx + 1, member.display_name))
            try:
                player_wins = player_info[Strings.PLAYER_WINS_KEY]
                player_gp = player_info[Strings.PLAYER_GP_KEY]
                player_wp = round(player_wins / player_gp * 100, 1)
                player_wp = f"{player_wp}%" if player_wp != 100 else "100%"
            except ZeroDivisionError:
                player_wp = "N/A"

            statStrings.append(f"Points: `{player_info[Strings.PLAYER_POINTS_KEY]:4d}`  Wins: `{player_wins:3d}`  GP: `{player_gp:3d}` WP: `{player_wp:5s}`")

            if idx + 1 > 10:
                break

        author = ctx.author
        try:
            author_index = [y[0] for y in sorted_players].index(f"{author.id}")
            if author_index is not None and author_index > 9:
                author_info = sorted_players[author_index][1]
                playerStrings.append(f"\n`{author_index + 1}` **{author.display_name:25s}:**")
                try:
                    author_wins = author_info[Strings.PLAYER_WINS_KEY]
                    author_gp = author_info[Strings.PLAYER_GP_KEY]
                    author_wp = round(author_wins / author_gp * 100, 1)
                    author_wp = f"{author_wp}%" if author_wp != 100 else "100%"
                except ZeroDivisionError:
                    author_wp = "N/A"

                statStrings.append(f"\nPoints: `{author_info[Strings.PLAYER_POINTS_KEY]:4d}`  Wins: `{author_wins:3d}`  GP: `{author_gp:3d}` WP: `{author_wp:5s}`")
        except Exception:
            pass

        embed.add_field(name="Player", value="\n".join(playerStrings), inline=True)
        embed.add_field(name="Stats", value="\n".join(statStrings), inline=True)
        return embed

    def embed_rank(
        self,
        player: discord.Member,
        sorted_players,
        queue_name,
        queue_max_size,
        rank_format,
    ):
        try:
            num_players = len(sorted_players)
            points_index = [y[0] for y in sorted_players].index(f"{player.id}")
            player_info = sorted_players[points_index][1]
            points, wins, games_played = (
                player_info[Strings.PLAYER_POINTS_KEY],
                player_info[Strings.PLAYER_WINS_KEY],
                player_info[Strings.PLAYER_GP_KEY],
            )
            wins_index = [
                y[0]
                for y in sorted(
                    sorted_players,
                    key=lambda x: x[1][Strings.PLAYER_WINS_KEY],
                    reverse=True,
                )
            ].index(f"{player.id}")
            games_played_index = [
                y[0]
                for y in sorted(
                    sorted_players,
                    key=lambda x: x[1][Strings.PLAYER_GP_KEY],
                    reverse=True,
                )
            ].index(f"{player.id}")
            embed = discord.Embed(
                title=f"{player.display_name} {rank_format} Rank",
                description=f"Player rank data for {queue_name} queue ({queue_max_size} mans)",
                color=discord.Colour.blue(),
            )
            embed.set_thumbnail(url=player.display_avatar.url)
            embed.add_field(
                name="Category",
                value=f"Points: `{points_index + 1}/{num_players}`\nWins: `{wins_index + 1}/{num_players}`\nGames Played: `{games_played_index + 1}/{num_players}`",
                inline=True,
            )
            embed.add_field(
                name="Value",
                value=f"`{points:4d}`\n`{wins:4d}`\n`{games_played:4d}`",
                inline=True,
            )
        except ValueError:
            embed = discord.Embed(
                title=f"{player.display_name} {queue_name} {queue_max_size} Mans {rank_format} Rank",
                description=f"No stats yet to rank {player.mention}",
                color=discord.Colour.red(),
            )
            embed.set_thumbnail(url=player.display_avatar.url)
        return embed

    def format_player_list(self, queue: SixMansQueue):
        player_list = ", ".join([player.mention for player in queue.queue.queue])
        if player_list == "":
            player_list = "No players currently in the queue"
        return player_list

    # endregion

    # region load/save methods

    async def _load_guild_data(self):
        log.info("Loading guild settings...")
        for guild in self.bot.guilds:
            log.debug(f"Preloading data for guild: {guild}")
            self.queues[guild] = []
            self.games[guild] = []

            # Defaults
            self.queueMaxSize[guild] = await self._get_queue_max_size(guild)
            self.player_timeout_time[guild] = await self._player_timeout(guild)
            saved_queues_enabled = await self._get_queues_enabled(guild)
            if saved_queues_enabled is not None:
                self.queues_enabled[guild] = saved_queues_enabled
            else:
                self.queues_enabled[guild] = True

            log.debug(f"Guild Queues Enabled: {saved_queues_enabled}")
            log.debug(f"Guild Queue Max Size: {self.queueMaxSize[guild]}")
            log.debug(f"Guild Player Timeout: {self.player_timeout_time[guild]}")

    async def _load_queues(self):
        log.info("Preloading existing queues...")
        # await self.bot.wait_until_ready()
        self.queues = {}
        self.games = {}

        for guild in self.bot.guilds:
            log.debug(f"Getting queues for guild: {guild}")
            self.queues[guild] = []
            self.games[guild] = []

            # Queue settings
            default_team_selection = await self._team_selection(guild)
            default_queue_size = self.queueMaxSize[guild]
            default_category = await self._category(guild)
            default_lobby_vc = await self._get_q_lobby_vc(guild)
            log.debug(f"Default Team Selection: {default_team_selection}")
            log.debug(f"Default Queue Size: {default_queue_size}")
            log.debug(f"Default Category: {default_category}")
            log.debug(f"Default Lobby VC: {default_lobby_vc}")

            # Pre-load Queues
            queues = await self._queues(guild)

            for key, value in queues.items():
                q = QueueData(**value)
                queue_channels = q.guild_channels(guild)
                queue_size = q.MaxSize or default_queue_size
                category = q.guild_category(guild) or default_category
                lobby_vc = q.lobby_vc(guild) or default_lobby_vc
                player_dict = q.Players.model_dump()

                # Default Game Mode
                if q.TeamSelection:
                    # Backwards compatitiblity for game mode
                    mode = q.TeamSelection.lower().capitalize()
                    team_selection = GameMode(mode)
                else:
                    team_selection = default_team_selection

                log.debug(f"Preloading Queue: {q.Name}")
                log.debug(f"\tCategory: {category}")
                log.debug(f"\tQueue Channels: {queue_channels}")
                log.debug(f"\tQueue Size: {queue_size}")
                log.debug(f"\tTeam Selection: {team_selection}")
                log.debug(f"\tLobby VC: {lobby_vc}")
                log.debug(f"Player Total: {len(player_dict.keys())}")
                log.debug(f"Games Played: {q.GamesPlayed}")

                log.debug(f"Players: {q.Players}")
                log.debug(f"Player_Dict: {player_dict}")
                log.debug(f"Points: {dict(q.Points)}")

                six_mans_queue = SixMansQueue(
                    id=int(key),
                    name=q.Name,
                    guild=guild,
                    channels=queue_channels,
                    points=dict(q.Points),
                    gamesPlayed=q.GamesPlayed,
                    players=player_dict,
                    maxSize=queue_size,
                    teamSelection=team_selection,
                    category=category,
                    lobby_vc=lobby_vc,
                )

                six_mans_queue.id = int(key)

                exists = False
                for idx, gq in enumerate(self.queues[guild]):
                    if gq.id == int(key):
                        self.queues[guild][idx] = six_mans_queue
                        exists = True

                if not exists:
                    self.queues[guild].append(six_mans_queue)

    async def _load_games(self):
        log.info("Preloading existing games...")
        self.games = {}

        for guild in self.bot.guilds:
            log.debug(f"Getting games for guild: {guild}")
            self.games[guild] = []

            # Pre-load Games
            games = await self._games(guild)
            from pprint import pformat

            log.debug(f"Games: {pformat(games)}")
            game_list = []
            log.debug(f"Preloaded Games Length: {len(games)}")
            for key, value in games.items():
                g = GameData(**value)

                # Player Data
                players = g.get_player_members(guild)
                captains = g.get_captain_members(guild)
                blue = g.get_blue_members(guild)
                orange = g.get_orange_members(guild)

                # Queue Data
                text_channel = g.guild_text_channel(guild)
                voice_channels = g.guild_voice_channels(guild)
                queueId = g.QueueId

                # Find guild queue object
                queue = None
                for q in self.queues[guild]:
                    if q.id == queueId:
                        queue = q

                if not queue:
                    log.error(f"Unable to find queue associated with ID: {queueId}")
                    continue

                log.debug(f"Loading Game: {key}")
                log.debug(f"State: {g.State}")
                log.debug(f"Players: {players}")
                log.debug(f"Game Info: {g.RoomName}//{g.RoomPass}")
                log.debug(f"Players: {players}")
                log.debug(f"Orange: {orange}")
                log.debug(f"Blue: {blue}")
                log.debug(f"Prefix: {players}")

                game = Game(
                    players=players,
                    queue=queue,
                    id=int(key),
                    blue=blue,
                    orange=orange,
                    captains=captains,
                    roomName=g.RoomName,
                    roomPass=g.RoomPass,
                    state=g.State,
                    text_channel=text_channel,
                    voice_channels=voice_channels,
                    prefix=g.Prefix,
                    teamSelection=g.TeamSelection,
                    winner=g.Winner,
                    save_callback=lambda g=guild: self._save_games(g, self.games[g]),  # type: ignore[misc]
                )

                log.debug(f"Guild: {guild.name} ID: {game.id} game.textChannel: {game.textChannel} State: {game.state} Mode: {game.teamSelection}")
                game_list.append(game)
            log.debug(f"Preloaded Games: {[g.id for g in game_list]}")
            self.games[guild] = game_list
            await self._save_games(guild, self.games[guild])

            # Start games again if needed.
            for eg in self.games[guild]:
                if eg.state == GameState.NEW or eg.state == GameState.SELECTION:
                    asyncio.create_task(eg.process_team_selection_method())
                elif eg.state == GameState.ONGOING:
                    asyncio.create_task(eg.send_game_info())

    async def _clear_all_data(self, guild: discord.Guild):
        await self._save_games(guild, [])
        await self._save_queues(guild, [])
        await self._save_scores(guild, [])
        await self._save_games_played(guild, 0)
        await self._save_players(guild, {})
        await self._save_category(guild, None)
        await self._save_q_lobby_vc(guild, None)
        await self._save_queue_max_size(guild, 6)
        await self._save_player_timeout(guild, PLAYER_TIMEOUT_TIME)
        await self._save_helper_role(guild, None)
        await self._save_team_selection(guild, GameMode.VOTE)
        await self._save_react_to_vote(guild, True)
        await self._save_automove(guild, False)

    async def _games(self, guild: discord.Guild):
        return await self.config.guild(guild).Games()

    async def _save_games(self, guild: discord.Guild, games: list[Game]):
        log.debug(f"Saving games. Guild: {guild.id} Game: {[g.id for g in games]}")
        game_dict = {}
        for game in games:
            game_dict[game.id] = game._to_dict()
        await self.config.guild(guild).Games.set(game_dict)

    async def _queues(self, guild: discord.Guild):
        return await self.config.guild(guild).Queues()

    async def _save_queues(self, guild: discord.Guild, queues: list[SixMansQueue]):
        queue_dict = {}
        for queue in queues:
            if queue.guild == guild:
                queue_dict[queue.id] = queue._to_dict()
        await self.config.guild(guild).Queues.set(queue_dict)

    async def _scores(self, guild: discord.Guild) -> list[PlayerScore]:
        return await self.config.guild(guild).Scores()

    async def _save_scores(self, guild: discord.Guild, scores: list[PlayerScore]):
        await self.config.guild(guild).Scores.set(scores)

    async def _games_played(self, guild: discord.Guild):
        return await self.config.guild(guild).GamesPlayed()

    async def _save_games_played(self, guild: discord.Guild, games_played: int):
        await self.config.guild(guild).GamesPlayed.set(games_played)

    async def _player_timeout(self, guild: discord.Guild):
        return await self.config.guild(guild).PlayerTimeout()

    async def _save_player_timeout(self, guild: discord.Guild, time_seconds: int):
        await self.config.guild(guild).PlayerTimeout.set(time_seconds)

    async def _players(self, guild: discord.Guild) -> dict[str, PlayerStats]:
        return await self.config.guild(guild).Players()

    async def _save_players(self, guild: discord.Guild, players: dict[str, PlayerStats]):
        await self.config.guild(guild).Players.set(players)

    async def _get_automove(self, guild: discord.Guild):
        return await self.config.guild(guild).AutoMove()

    async def _save_automove(self, guild: discord.Guild, automove: bool):
        await self.config.guild(guild).AutoMove.set(automove)

    async def _is_react_to_vote(self, guild: discord.Guild):
        return await self.config.guild(guild).ReactToVote()

    async def _save_react_to_vote(self, guild: discord.Guild, automove: bool):
        await self.config.guild(guild).ReactToVote.set(automove)

    async def _category(self, guild: discord.Guild) -> discord.CategoryChannel | None:
        category_id = await self.config.guild(guild).CategoryChannel()
        if not category_id:
            return None
        category = guild.get_channel(category_id)
        if not isinstance(category, discord.CategoryChannel):
            log.error(f"[{guild.name}] 6 mans category is not actually a category.")
            return None
        return category

    async def _save_category(self, guild: discord.Guild, category: int | None):
        await self.config.guild(guild).CategoryChannel.set(category)

    async def _save_q_lobby_vc(self, guild: discord.Guild, vc: int | None):
        await self.config.guild(guild).QLobby.set(vc)

    async def _get_q_lobby_vc(self, guild: discord.Guild):
        log.debug(f"Guild: {guild}")
        lobby_voice = await self.config.guild(guild).QLobby()
        log.debug(f"lobby_voice: {lobby_voice}")
        for vc in guild.voice_channels:
            if vc.id == lobby_voice:
                return vc
        return None

    async def _get_queue_max_size(self, guild: discord.Guild):
        return await self.config.guild(guild).DefaultQueueMaxSize()

    async def _save_queue_max_size(self, guild: discord.Guild, max_size: int):
        await self.config.guild(guild).DefaultQueueMaxSize.set(max_size)
        self.queueMaxSize[guild] = max_size

    async def _helper_role(self, guild: discord.Guild):
        return guild.get_role(await self.config.guild(guild).HelperRole())

    async def _save_helper_role(self, guild: discord.Guild, helper_role):
        await self.config.guild(guild).HelperRole.set(helper_role)

    async def _save_team_selection(self, guild: discord.Guild, team_selection: GameMode):
        await self.config.guild(guild).DefaultTeamSelection.set(team_selection.value)

    async def _team_selection(self, guild: discord.Guild) -> GameMode:
        mode = await self.config.guild(guild).DefaultTeamSelection()
        # Backwards compatibilitgy
        if mode:
            mode = mode.lower().capitalize()
            return GameMode(mode)
        else:
            return GameMode.VOTE

    async def _save_queues_enabled(self, guild: discord.Guild, enabled: bool):
        return await self.config.guild(guild).QueuesEnabled.set(enabled)

    async def _get_queues_enabled(self, guild: discord.Guild):
        return await self.config.guild(guild).QueuesEnabled()

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


# endregion
