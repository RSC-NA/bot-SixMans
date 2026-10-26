import asyncio
import contextlib
import logging
from collections.abc import Callable
from typing import TYPE_CHECKING

import discord
from discord.ext.commands import Context

from sixMans.constants import CHANNEL_SLEEP_TIME
from sixMans.embeds import ErrorEmbed, WarningEmbed
from sixMans.enums import GameState, Winner
from sixMans.game import Game
from sixMans.models.game import GameData
from sixMans.queue import SixMansQueue
from sixMans.types import PlayerStats

if TYPE_CHECKING:
    from redbot.core import Config
    from redbot.core.bot import Red

    from sixMans.scoreboard.scoreboard import Scoreboard

log = logging.getLogger("red.sixMans.games")


class GameLifecycle:
    """Active games: popping a queue into a game, finding and finishing games, teardown, and loading and saving them."""

    if TYPE_CHECKING:
        bot: Red
        config: Config
        scoreboard: Scoreboard
        queues: dict[discord.Guild, list[SixMansQueue]]
        games: dict[discord.Guild, list[Game]]
        queueMaxSize: dict[discord.Guild, int]
        _background_tasks: set[asyncio.Task]

        async def _helper_role(self, guild: discord.Guild) -> discord.Role | None: ...
        async def _category(self, guild: discord.Guild) -> discord.CategoryChannel | None: ...
        async def _get_automove(self, guild: discord.Guild) -> bool: ...
        async def _get_q_lobby_vc(self, guild: discord.Guild) -> discord.VoiceChannel | None: ...
        async def _remove_from_queue(self, player: discord.Member, six_mans_queue: SixMansQueue): ...

    def get_game_by_id(self, guild: discord.Guild, game_id: int) -> Game | None:
        log.debug(f"Fetching Game ID: {game_id}")
        for active_game in self.games.get(guild, []):
            if active_game.id == game_id:
                return active_game
        return None

    def get_game_by_text_channel(self, channel: discord.TextChannel) -> Game | None:
        log.debug(f"Games: {self.games}")
        for game in self.games.get(channel.guild, []):
            if game.textChannel == channel:
                return game
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

    async def _games(self, guild: discord.Guild):
        return await self.config.guild(guild).Games()

    async def _save_games(self, guild: discord.Guild, games: list[Game]):
        log.debug(f"Saving games. Guild: {guild.id} Game: {[g.id for g in games]}")
        game_dict = {}
        for game in games:
            game_dict[game.id] = game._to_dict()
        await self.config.guild(guild).Games.set(game_dict)
