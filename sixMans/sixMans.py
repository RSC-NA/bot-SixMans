import asyncio
import contextlib
import datetime
import logging
from collections.abc import Callable

import discord
from discord.ext.commands import Context
from redbot.core import Config, checks, commands

from sixMans.constants import CHANNEL_SLEEP_TIME, MINIMUM_GAME_TIME, PLAYER_TIMEOUT_TIME
from sixMans.embeds import (
    BlueEmbed,
    ErrorEmbed,
    ExceptionErrorEmbed,
    QueueNotFoundEmbed,
    SuccessEmbed,
    WarningEmbed,
)
from sixMans.enums import GameMode, GameState, Winner
from sixMans.game import Game
from sixMans.models.game import GameData
from sixMans.models.queue import QueueData
from sixMans.queue import SixMansQueue
from sixMans.scoreboard.commands import ScoreboardCommands
from sixMans.scoreboard.scoreboard import Scoreboard
from sixMans.settings.commands import SettingsCommands
from sixMans.strings import Strings
from sixMans.types import PlayerStats, QueueBan, SixMansConfig
from sixMans.views.cancel import CancelView, ForceCancelView
from sixMans.views.score import ForceResultView, ScoreReportView

log = logging.getLogger("red.sixMans")

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
    QueueStats={},
    ScoreboardSchema=0,
)


class SixMans(SettingsCommands, ScoreboardCommands, commands.Cog):
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
        # Strong refs to detached game tasks so they aren't GC'd mid-flight
        self._background_tasks: set[asyncio.Task] = set()
        self.scoreboard = Scoreboard(self.config)

    @commands.Cog.listener()
    async def on_ready(self):
        """Load saved game data on startup"""
        log.debug("In on_ready()")
        await self._load_guild_data()
        await self._load_scoreboard()
        await self._load_queues()
        await self._load_games()

    async def cog_load(self):
        """Load saved game data on startup"""
        log.debug("In cog_load()")
        await self._load_guild_data()
        await self._load_scoreboard()
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
            await self._save_games(guild, self.games.get(guild, []))

    # region listeners
    @commands.Cog.listener("on_guild_channel_delete")
    async def on_guild_channel_delete(self, channel):
        """
        If a queue channel is deleted, removes it from the queue class instance.

        If the last queue channel is deleted, the channel is replaced.
        """
        # TODO: Error catch if Q Lobby VC is deleted
        if not isinstance(channel, discord.TextChannel):
            return

        # A game's own channel being deleted out of band leaves its selection
        # view alive and pointed at a channel that no longer exists.
        for game in self.games.get(channel.guild, []):
            if game.textChannel and game.textChannel.id == channel.id:
                log.warning(f"Game channel for {game.id} was deleted. Aborting team selection.")
                game.abort()
                game.textChannel = None
                break

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
        helper_ping = f" {helper_role.mention}" if helper_role else ""
        await clone.send(f":grey_exclamation:{helper_ping} This channel has been created because the last textChannel for the **{queue.name}** queue has been deleted.")
        queue.channels.append(clone)
        await self._save_queues(channel.guild, self.queues[channel.guild])

    @commands.Cog.listener("on_member_remove")
    async def on_member_remove(self, member: discord.Member):
        """Remove a departing member from any queue they're waiting in.

        A member who has left can't be given channel permission overwrites, which would otherwise
        break game creation when the queue pops.
        """
        for queue in self.queues.get(member.guild, []):
            if member in queue.queue:
                log.info(f"[{member.guild.name}] Removing {member.id} from the {queue.name} queue. They left the server.")
                await self._remove_from_queue(member, queue)

        for game in self.games.get(member.guild, []):
            if member not in game or not game.textChannel:
                continue

            log.info(f"[{member.guild.name}] {member.id} left the server during game {game.id}.")
            helper_role = await self._helper_role(member.guild)
            helper_ping = f" {helper_role.mention}" if helper_role else ""
            with contextlib.suppress(discord.HTTPException, discord.Forbidden, discord.NotFound):
                await game.textChannel.send(f":warning:{helper_ping} **{member.display_name}** has left the server. This game may need to be cancelled with `{game.prefix}fcg`.")

    # endregion

    # region commands

    # region admin commands

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

        if not game.textChannel:
            return await ctx.send(embed=ErrorEmbed(description=f"Game **{game.id}** no longer has a text channel."))

        await game.textChannel.send(f"Processing Forced Team Selection: {mode}")
        await game.process_team_selection_method(team_selection=mode, force=True)

    @commands.guild_only()
    @commands.max_concurrency(1, commands.BucketType.channel, wait=False)
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

        live_game = self.revalidate_game(ctx.guild, game)
        if live_game is None:
            return await ctx.send(embed=ErrorEmbed(description="This game is no longer active."))
        game = live_game

        game.state = GameState.CANCELLED
        await self._remove_game(ctx.guild, game)

    @commands.guild_only()
    @commands.max_concurrency(1, commands.BucketType.channel, wait=False)
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

        live_game = self.revalidate_game(ctx.guild, game)
        if live_game is None:
            return await ctx.send(embed=ErrorEmbed(description="This game is no longer active. The score was not recorded."))
        game = live_game

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
    @commands.max_concurrency(1, commands.BucketType.channel, wait=False)
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

        live_game = self.revalidate_game(ctx.guild, game)
        if live_game is None:
            return await ctx.send(embed=ErrorEmbed(description="This game is no longer active."))
        game = live_game

        game.state = GameState.CANCELLED
        await self._remove_game(ctx.guild, game)

    @commands.guild_only()
    @commands.max_concurrency(1, commands.BucketType.channel, wait=False)
    @commands.command(aliases=["sr", "reportScore"])
    async def scoreReport(self, ctx: Context):
        """Report which team won the series. Can only be used in a game channel.
        Only valid after 10 minutes have passed since the game started. Both teams will need to verify the results.

        `winning_team` must be either `Blue` or `Orange`"""

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

        # The prompt above can block for two minutes. Re-fetch before scoring: the game may have
        # been cancelled, reported by a competing prompt, or replaced by a reload in that window.
        live_game = self.revalidate_game(ctx.guild, game)
        if live_game is None:
            return await ctx.send(embed=ErrorEmbed(description="This game is no longer active. The score was not recorded."))
        game = live_game

        if game.winner != Winner.PENDING:
            return await ctx.send(
                embed=BlueEmbed(
                    title="Already Reported",
                    description=f"The game result has already been reported.\n\nWinner: {game.winner}",
                )
            )

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

        # Don't leave the timeout task sleeping for the rest of its duration. `_auto_remove_from_queue`
        # calls this from inside its own timeout task, which must not cancel itself.
        task = self.timeout_tasks.get(player, {}).get(six_mans_queue)
        if task and task is not asyncio.current_task():
            task.cancel()

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
        # Scoring is not idempotent: every call inserts a fresh score row per player and bumps
        # GamesPlayed. Two reports racing for the same game (two `!sr` prompts, or `!sr` against
        # `!fr`) would silently double credit everyone, so only the call that still sees the game
        # in the active list is allowed through.
        live = self.get_game_by_id(guild, game.id)
        if live is None:
            log.warning(f"[{guild.name}] Refusing to finish game {game.id}. It is no longer an active game.")
            return
        if live is not game:
            log.info(f"[{guild.name}] Game {game.id} was reloaded mid-report. Scoring the live object.")
            game = live

        # `_load_queues()` also rebuilds queue objects, so the caller may be holding one that is no
        # longer the object `_save_queues` persists. Re-resolve by id or the win would be dropped.
        live_queue = next((q for q in self.queues.get(guild, []) if q.id == six_mans_queue.id), None)
        if live_queue is not None:
            six_mans_queue = live_queue

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

        await self.scoreboard.record_game(guild, six_mans_queue, game.id, winning_players, losing_players)

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
                await member.move_to(vc)

    async def _remove_game(self, guild: discord.Guild, game: Game):
        """Remove game from active games and delete channels.

        Removal is keyed on `game.id` rather than object identity. `Game` defines no `__eq__`, and
        `_load_games()` rebuilds every `Game` from config on reconnect, so a command that captured a
        reference before an `await` can easily be holding an object that is no longer the one in
        `self.games[guild]`. Matching on id removes the live entry instead of raising.

        Also idempotent: if no active game carries this id, the teardown is already done (or in
        flight) and we return without repeating the 30 second sleep and channel deletes.
        """
        # Unblock and disarm any pending selection view before its channel goes
        # away. Done first so a coroutine parked in `view.wait()` resumes now
        # rather than after the sleep below -- or, for the untimed captains and
        # self-pick views, rather than never.
        game.abort()

        active = self.games.setdefault(guild, [])
        live = next((g for g in active if g.id == game.id), None)
        if live is None:
            log.warning(f"[{guild.name}] Game {game.id} is not in active games. Nothing to remove.")
            return

        if live is not game:
            log.info(f"[{guild.name}] Game {game.id} was reloaded since it was fetched. Tearing down the live object.")
            live.abort()

        self.games[guild] = [g for g in active if g.id != game.id]
        await self._save_games(guild, self.games[guild])

        # Sleep before removal
        await asyncio.sleep(CHANNEL_SLEEP_TIME)
        q_lobby_vc = await self._get_q_lobby_vc(guild)

        # Delete game text channel
        text_channel = live.textChannel or game.textChannel
        if text_channel:
            try:
                await text_channel.delete()
            except discord.NotFound:
                log.debug(f"Game channel {text_channel} was already deleted.")
            except Exception as exc:
                log.exception(f"Error deleting game channel {text_channel}", exc_info=exc)
            live.textChannel = None
            game.textChannel = None

        for vc in live.voiceChannels or game.voiceChannels:
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
            except discord.NotFound:
                log.debug(f"Game voice channel {vc.name} was already deleted.")
            except (discord.Forbidden, discord.HTTPException) as exc:
                log.exception(f"Error deleting game voice channel {vc.name}", exc_info=exc)

        live.voiceChannels = []
        game.voiceChannels = []

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

    async def _get_departed_players(self, guild: discord.Guild, six_mans_queue: SixMansQueue) -> list[discord.Member]:
        """Return the players at the front of the queue who are no longer in the guild."""
        departed: list[discord.Member] = []
        for player in six_mans_queue._peek(six_mans_queue.maxSize):
            if guild.get_member(player.id):
                continue

            # Cache miss. Confirm against the API before removing anyone, otherwise a cold member
            # cache would make every player look like they had left the server.
            try:
                await guild.fetch_member(player.id)
            except discord.NotFound:
                departed.append(player)
            except (discord.HTTPException, discord.Forbidden) as exc:
                log.warning(f"[{guild.name}] Unable to verify whether {player.id} is still in the guild.", exc_info=exc)

        return departed

    async def create_game(self, guild: discord.Guild, six_mans_queue: SixMansQueue, prefix="?"):
        if not six_mans_queue.queue_full():
            return None

        # Players sit in the queue as Member objects for up to PLAYER_TIMEOUT_TIME. Anyone who left
        # the guild while waiting can no longer be given channel permission overwrites (Discord
        # returns 404 Unknown Overwrite), so drop them before the queue is popped.
        missing = await self._get_departed_players(guild, six_mans_queue)
        if missing:
            log.warning(f"[{guild.name}] Removing players no longer in the guild from the {six_mans_queue.name} queue: {[p.id for p in missing]}")
            for player in missing:
                await self._remove_from_queue(player, six_mans_queue)

            names = ", ".join(player.display_name for player in missing)
            verb = "are" if len(missing) > 1 else "is"
            description = (
                f"**{names}** {verb} no longer in the server and cannot be added to a game.\n\n"
                f"The **{six_mans_queue.name}** queue is now at **{six_mans_queue.queue.qsize()}/{six_mans_queue.maxSize}**."
            )
            await six_mans_queue.send_message(embed=WarningEmbed(title="Queue Not Popped", description=description))
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
            stats_lookup=self._queue_stats_lookup(guild),
        )
        try:
            await game.create_game_channels(await self._category(guild))
        except (discord.HTTPException, discord.Forbidden) as exc:
            log.exception(f"[{guild.name}] Error creating game channels for queue: {six_mans_queue.name}", exc_info=exc)
            # Put everyone back in the queue in their original order. `_get()` never touched their
            # timeout tasks, so those are still running and must not be recreated here.
            for player in players:
                six_mans_queue._put(player)
            await six_mans_queue.send_message(
                embed=ErrorEmbed(
                    title="Game Creation Failed",
                    description="Something went wrong while creating the game channels. Everyone has been returned to the queue.",
                )
            )
            return None

        log.debug(f"Saving game: {game.id} Players: {game.players}")
        self.games[guild].append(game)
        await self._save_games(guild, self.games[guild])

        await game.process_team_selection_method()
        # Save again once teams are selected
        await self._save_games(guild, self.games[guild])
        return game

    def _queue_stats_lookup(self, guild: discord.Guild) -> Callable[[int, int], PlayerStats | None]:
        return lambda queue_id, player_id: self.scoreboard.queue_player(guild, queue_id, player_id)

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

    def get_game_by_id(self, guild: discord.Guild, game_id: int) -> Game | None:
        log.debug(f"Fetching Game ID: {game_id}")
        for active_game in self.games.get(guild, []):
            if active_game.id == game_id:
                return active_game
        return None

    def revalidate_game(self, guild: discord.Guild, game: Game) -> Game | None:
        """Re-fetch a game after awaiting on a view.

        Commands hold a `Game` reference across a prompt that can block for minutes. In that window
        the game may have been cancelled, finished by a competing report, or replaced wholesale by
        `_load_games()`. Returns the live object for this game id, or `None` if it is gone or
        already finished.
        """
        live = self.get_game_by_id(guild, game.id)
        if live is None:
            log.info(f"[{guild.name}] Game {game.id} is no longer active.")
            return None
        if live.state in (GameState.COMPLETE, GameState.CANCELLED):
            log.info(f"[{guild.name}] Game {game.id} is already {live.state}.")
            return None
        return live

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

        embed.add_field(name="Games Played", value=f"{self.scoreboard.queue_games_played(queue.guild, queue.id)}\n", inline=False)
        embed.add_field(
            name="Unique Players All-Time",
            value=f"{len(self.scoreboard.queue_players(queue.guild, queue.id))}\n",
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
                value="\n".join([f"{game.id!s}\n{', '.join([player.mention for player in game.players])}" for game in games]),
                inline=False,
            )
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
            self.games.setdefault(guild, [])

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

    async def _load_scoreboard(self):
        for guild in self.bot.guilds:
            await self.scoreboard.load(guild)

    async def _load_queues(self):
        log.info("Preloading existing queues...")
        # await self.bot.wait_until_ready()
        self.queues = {}

        for guild in self.bot.guilds:
            log.debug(f"Getting queues for guild: {guild}")
            self.queues[guild] = []
            self.games.setdefault(guild, [])

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
                    legacy_games_played=q.GamesPlayed,
                    legacy_players=player_dict,
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
        """Load persisted games into memory, keeping any `Game` objects already there.

        This runs from `cog_load()` but also from the `on_ready` listener, which fires on every
        gateway IDENTIFY -- i.e. after any reconnect, not just at startup. Rebuilding every `Game`
        unconditionally would invalidate references held by commands that are parked in a view's
        `wait()`, so games already in memory are reused by id and only genuinely new ids are
        constructed.
        """
        log.info("Preloading existing games...")

        for guild in self.bot.guilds:
            log.debug(f"Getting games for guild: {guild}")
            existing = {g.id: g for g in self.games.get(guild, [])}
            self.games.setdefault(guild, [])

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

                # A game whose channel is gone cannot be resumed -- restarting
                # team selection for it would only crash in a detached task.
                if not text_channel:
                    log.warning(f"Dropping game {key}. Its text channel no longer exists.")
                    continue

                known = existing.get(int(key))
                if known is not None:
                    log.debug(f"Game {key} is already loaded. Reusing the in-memory object.")
                    # `_load_queues()` rebuilt the queue objects, so the reused game would
                    # otherwise keep scoring against a SixMansQueue that is no longer saved.
                    known.queue = queue
                    game_list.append(known)
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
                    stats_lookup=self._queue_stats_lookup(guild),
                )

                log.debug(f"Guild: {guild.name} ID: {game.id} game.textChannel: {game.textChannel} State: {game.state} Mode: {game.teamSelection}")
                game_list.append(game)
            log.debug(f"Preloaded Games: {[g.id for g in game_list]}")
            self.games[guild] = game_list
            await self._save_games(guild, self.games[guild])

            # Start games again if needed. Games that were already in memory have a selection or
            # info task in flight already -- respawning would give them a second one.
            for eg in self.games[guild]:
                if eg.id in existing:
                    continue
                if eg.state == GameState.NEW or eg.state == GameState.SELECTION:
                    self._spawn_game_task(eg.process_team_selection_method(), eg)
                elif eg.state == GameState.ONGOING:
                    self._spawn_game_task(eg.send_game_info(), eg)

    def _spawn_game_task(self, coro, game: Game):
        """Run a game coroutine detached, logging failures instead of dropping them.

        A bare `asyncio.create_task` leaves any exception unretrieved, which
        surfaces only as an asyncio warning with no context about the game.
        """

        def _log_result(task: asyncio.Task):
            if task.cancelled():
                return
            exc = task.exception()
            if exc:
                log.error(f"Background task failed for game {game.id}", exc_info=exc)

        task = asyncio.create_task(coro)
        task.add_done_callback(_log_result)
        self._background_tasks.add(task)
        task.add_done_callback(self._background_tasks.discard)
        return task

    async def _clear_all_data(self, guild: discord.Guild):
        await self._save_games(guild, [])
        await self._save_queues(guild, [])
        await self.scoreboard.clear(guild)
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
