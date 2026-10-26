import asyncio
import contextlib
import logging

import discord
from redbot.core import Config, commands

from sixMans.constants import PLAYER_TIMEOUT_TIME
from sixMans.enums import GameMode
from sixMans.game import Game
from sixMans.games.commands import GameCommands
from sixMans.queue import SixMansQueue
from sixMans.queues.bans import QueueBanCommands
from sixMans.queues.commands import QueueCommands
from sixMans.scoreboard.commands import ScoreboardCommands
from sixMans.scoreboard.scoreboard import Scoreboard
from sixMans.settings.commands import SettingsCommands
from sixMans.types import SixMansConfig

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


class SixMans(SettingsCommands, QueueCommands, QueueBanCommands, GameCommands, ScoreboardCommands, commands.Cog):
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

    # endregion
