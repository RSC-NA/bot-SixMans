import asyncio
import contextlib
import logging
from typing import TYPE_CHECKING

import discord

from sixMans.constants import PLAYER_TIMEOUT_TIME
from sixMans.enums import GameMode
from sixMans.models.queue import QueueData
from sixMans.queue import SixMansQueue
from sixMans.queues.embeds import player_added_embed, player_removed_embed

if TYPE_CHECKING:
    from redbot.core import Config
    from redbot.core.bot import Red

    from sixMans.game import Game

log = logging.getLogger("red.sixMans.queues")


class QueueState:
    """Each guild's queues: lookup, joining and leaving, queue timeouts, and loading and saving them."""

    if TYPE_CHECKING:
        bot: Red
        config: Config
        queues: dict[discord.Guild, list[SixMansQueue]]
        games: dict[discord.Guild, list[Game]]
        queueMaxSize: dict[discord.Guild, int]
        player_timeout_time: dict[discord.Guild, int]
        timeout_tasks: dict[discord.Member, dict[SixMansQueue, asyncio.Task]]

        async def _team_selection(self, guild: discord.Guild) -> GameMode: ...
        async def _category(self, guild: discord.Guild) -> discord.CategoryChannel | None: ...
        async def _get_q_lobby_vc(self, guild: discord.Guild) -> discord.VoiceChannel | None: ...

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

    async def _add_to_queue(self, player: discord.Member, six_mans_queue: SixMansQueue):
        six_mans_queue._put(player)
        embed = player_added_embed(player, six_mans_queue)
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
        embed = player_removed_embed(player, six_mans_queue)
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

    async def _queues(self, guild: discord.Guild):
        return await self.config.guild(guild).Queues()

    async def _save_queues(self, guild: discord.Guild, queues: list[SixMansQueue]):
        queue_dict = {}
        for queue in queues:
            if queue.guild == guild:
                queue_dict[queue.id] = queue._to_dict()
        await self.config.guild(guild).Queues.set(queue_dict)
