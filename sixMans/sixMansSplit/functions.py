import discord
import logging
import random
import asyncio
import datetime
from typing import Dict, List

from discord.ext.commands import Context
from redbot.core import commands

from sixMans.game import Game
from sixMans.queue import SixMansQueue
from sixMans.strings import Strings
from sixMans.views import GameMode, GameState


# region Functions from sixMans.py
log = logging.getLogger("red.RSC6Mans.sixMans")

DEBUG = True
MINIMUM_GAME_TIME = 600  # Seconds (10 Minutes)
PLAYER_TIMEOUT_TIME = (
    10 if DEBUG else 14400
)  # How long players can be in a queue in seconds (4 Hours)
LOOP_TIME = 5  # How often to check the queues in seconds
VERIFY_TIMEOUT = 15  # How long someone has to react to a prompt (seconds)
CHANNEL_SLEEP_TIME = (
    5 if DEBUG else 30
)  # How long channels will persist after a game's score has been reported (seconds)

defaults = {
    "CategoryChannel": None,
    "HelperRole": None,
    "AutoMove": False,
    "ReactToVote": True,
    "QLobby": None,
    "DefaultTeamSelection": GameMode.VOTE,
    "DefaultQueueMaxSize": 6,
    "PlayerTimeout": PLAYER_TIMEOUT_TIME,
    "Games": {},
    "Queues": {},
    "GamesPlayed": 0,
    "Players": {},
    "Scores": [],
    "QueuesEnabled": True,
}


# Functions from sixMans.py
# region load/save methods
async def _pre_load_data(self):
    await self.bot.wait_until_ready()
    self.queues = {}
    self.games = {}

    for guild in self.bot.guilds:
        self.queues[guild] = []
        self.games[guild] = []

        # Preload General Data
        saved_queues_enabled = await self._get_queues_enabled(guild)
        self.queues_enabled[guild] = (
            saved_queues_enabled if (saved_queues_enabled is not None) else True
        )
        self.queueMaxSize[guild] = await self._get_queue_max_size(guild)
        self.player_timeout_time[guild] = await self._player_timeout(
            guild
        )  ## if not DEBUG else PLAYER_TIMEOUT_TIME

        # Pre-load Queues
        queues = await self._queues(guild)
        default_team_selection = await self._team_selection(guild)
        default_queue_size = self.queueMaxSize[guild]
        default_category = await self._category(guild)
        default_lobby_vc = await self._get_q_lobby_vc(guild)
        for key, value in queues.items():
            queue_channels = [guild.get_channel(x) for x in value["Channels"]]
            queue_name = value["Name"]
            team_selection = value.setdefault("TeamSelection", default_team_selection)
            queue_size = value.setdefault("MaxSize", default_queue_size)
            if default_category:
                category = guild.get_channel(
                    value.setdefault("Category", default_category.id)
                )
            elif "Category" in value and value["Category"]:
                category = value["Category"]
            else:
                category = None

            if default_lobby_vc:
                lobby_vc = guild.get_channel(
                    value.setdefault("LobbyVC", default_lobby_vc.id)
                )
            elif "LobbyVC" in value and value["LobbyVC"]:
                lobby_vc = value["LobbyVC"]
            else:
                lobby_vc = None

            log.debug(f"Preloading Queue: {queue_name}")
            log.debug(f"\tGuild: {guild}")
            log.debug(f"\tQueue Channels: {queue_channels}")
            log.debug(f"\tQueue Size: {queue_size}")
            log.debug(f"\tTeam Selection: {team_selection}")
            log.debug(f"\tCategory: {category}")
            log.debug(f"\tLobby VC: {lobby_vc}")

            six_mans_queue = SixMansQueue(
                queue_name,
                guild,
                queue_channels,
                value["Points"],
                value["Players"],
                value["GamesPlayed"],
                queue_size,
                teamSelection=team_selection,
                category=category,
                lobby_vc=lobby_vc,
            )

            six_mans_queue.id = int(key)
            self.queues[guild].append(six_mans_queue)

        # Pre-load Games
        games = await self._games(guild)
        game_list = []
        log.debug(f"Preloaded Games Length: {len(games)}")
        for key, value in games.items():
            players = [guild.get_member(x) for x in value["Players"]]
            text_channel = guild.get_channel(value["TextChannel"])
            voice_channels = [guild.get_channel(x) for x in value["VoiceChannels"]]
            queueId = value["QueueId"]

            queue = None
            for q in self.queues[guild]:
                if q.id == queueId:
                    queue = q

            log.debug(f"Loading game players: {players}")
            game = Game(
                players,
                queue,
                text_channel=text_channel,
                voice_channels=voice_channels,
            )
            game.id = int(key)
            game.captains = [guild.get_member(x) for x in value["Captains"]]
            game.blue = set([guild.get_member(x) for x in value["Blue"]])
            game.orange = set([guild.get_member(x) for x in value["Orange"]])
            game.roomName = value["RoomName"]
            game.roomPass = value["RoomPass"]
            game.prefix = value["Prefix"]
            game.teamSelection = value["TeamSelection"]
            game.scoreReported = value["ScoreReported"]

            log.debug(
                f"Guild: {guild.id} ID: {game.id} game.textChannel: {game.textChannel} State: {game.state} Mode: {game.teamSelection}"
            )
            game_list.append(game)
        log.debug(f"Preloaded Games: {game_list}")
        self.games[guild] = game_list
        await self._save_games(guild, self.games[guild])

        # # Start games again if needed.
        # for g in self.games[guild]:
        #     if g.state == GameState.NEW:
        #         asyncio.create_task(g.process_team_selection_method())


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


async def _save_games(self, guild: discord.Guild, games: List[Game]):
    log.debug(f"Saving games. Guild: {guild.id} Game: {games}")
    game_dict = {}
    for game in games:
        game_dict[game.id] = game._to_dict()
    await self.config.guild(guild).Games.set(game_dict)


async def _queues(self, guild: discord.Guild):
    return await self.config.guild(guild).Queues()


async def _save_queues(self, guild: discord.Guild, queues: List[SixMansQueue]):
    queue_dict = {}
    for queue in queues:
        if queue.guild == guild:
            queue_dict[queue.id] = queue._to_dict()
    await self.config.guild(guild).Queues.set(queue_dict)


async def _scores(self, guild: discord.Guild):
    return await self.config.guild(guild).Scores()


async def _save_scores(self, guild: discord.Guild, scores):
    await self.config.guild(guild).Scores.set(scores)


async def _games_played(self, guild: discord.Guild):
    return await self.config.guild(guild).GamesPlayed()


async def _save_games_played(self, guild: discord.Guild, games_played: int):
    await self.config.guild(guild).GamesPlayed.set(games_played)


async def _player_timeout(self, guild: discord.Guild):
    return await self.config.guild(guild).PlayerTimeout()


async def _save_player_timeout(self, guild: discord.Guild, time_seconds: int):
    await self.config.guild(guild).PlayerTimeout.set(time_seconds)


async def _players(self, guild: discord.Guild):
    return await self.config.guild(guild).Players()


async def _save_players(self, guild: discord.Guild, players):
    await self.config.guild(guild).Players.set(players)


async def _get_automove(self, guild: discord.Guild):
    return await self.config.guild(guild).AutoMove()


async def _save_automove(self, guild: discord.Guild, automove: bool):
    await self.config.guild(guild).AutoMove.set(automove)


async def _is_react_to_vote(self, guild: discord.Guild):
    return await self.config.guild(guild).ReactToVote()


async def _save_react_to_vote(self, guild: discord.Guild, automove: bool):
    await self.config.guild(guild).ReactToVote.set(automove)


async def _category(self, guild: discord.Guild):
    return guild.get_channel(await self.config.guild(guild).CategoryChannel())


async def _save_category(self, guild: discord.Guild, category):
    await self.config.guild(guild).CategoryChannel.set(category)


async def _save_q_lobby_vc(self, guild: discord.Guild, vc):
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
    self.queueMaxSize[guild] = int


async def _helper_role(self, guild: discord.Guild):
    return guild.get_role(await self.config.guild(guild).HelperRole())


async def _save_helper_role(self, guild: discord.Guild, helper_role):
    await self.config.guild(guild).HelperRole.set(helper_role)


async def _save_team_selection(self, guild: discord.Guild, team_selection):
    await self.config.guild(guild).DefaultTeamSelection.set(team_selection)


async def _team_selection(self, guild: discord.Guild):
    return await self.config.guild(guild).DefaultTeamSelection()


async def _save_queues_enabled(self, guild: discord.Guild, enabled: bool):
    return await self.config.guild(guild).QueuesEnabled.set(enabled)


async def _get_queues_enabled(self, guild: discord.Guild):
    return await self.config.guild(guild).QueuesEnabled()


# endregion
# endregion


# region helper methods
async def has_perms(self, member: discord.Member):
    if member.guild_permissions.administrator:
        return True
    helper_role = await self._helper_role(member.guild)
    if helper_role and helper_role in member.roles:
        return True


async def _add_to_queue(self, player: discord.Member, six_mans_queue: SixMansQueue):
    six_mans_queue._put(player)
    embed = self.embed_player_added(player, six_mans_queue)
    try:
        await six_mans_queue.send_message(embed=embed)
    except Exception as exc:
        log.debug(f"Exception adding {player.name} to queue: {exc}")
        raise exc

    await self.create_timeout_task(
        player, six_mans_queue, self.player_timeout_time[six_mans_queue.guild]
    )


async def _remove_from_queue(
    self, player: discord.Member, six_mans_queue: SixMansQueue
):
    six_mans_queue._remove(player)
    embed = self.embed_player_removed(player, six_mans_queue)
    await six_mans_queue.send_message(embed=embed)
    await self.remove_timeout_task(player, six_mans_queue)


async def get_visble_queue_channel(
    self, six_mans_queue: SixMansQueue, player: discord.Member
):
    for channel in six_mans_queue.channels:
        if player in channel.members:
            return channel
    return None


async def _auto_remove_from_queue(
    self, player: discord.Member, six_mans_queue: SixMansQueue
):
    # Remove player from queue
    await self._remove_from_queue(player, six_mans_queue)

    # Send Player Message
    auto_remove_msg = (
        f"You have been timed out from the **{six_mans_queue.name} {six_mans_queue.maxSize} Mans queue**. You'll need to use the "
        + "queue command again if you wish to play some more."
    )
    channel = await self.get_visble_queue_channel(six_mans_queue, player)

    try:
        invite_msg = f"\n\nYou may return to {channel.mention} to rejoin the queue!"
        embed = discord.Embed(
            title=f"{six_mans_queue.guild.name}: {six_mans_queue.maxSize} Mans Timeout",
            description=auto_remove_msg + invite_msg,
            color=discord.Color.red(),
        )
        embed.set_thumbnail(url=six_mans_queue.guild.icon.url)
        await player.send(embed=embed)
    except:
        try:
            await player.send(auto_remove_msg)
        except:
            pass


async def create_timeout_task(
    self, player: discord.Member, six_mans_queue: SixMansQueue, time=None
):
    self.timeout_tasks.setdefault(player, {})
    self.timeout_tasks[player][six_mans_queue] = asyncio.create_task(
        self.player_queue_timeout(player, six_mans_queue, time)
    )


async def player_queue_timeout(
    self, player: discord.Member, six_mans_queue: SixMansQueue, time=None
):
    if not time:
        time = self.player_queue_timeout[six_mans_queue.guild]

    await asyncio.sleep(time)
    try:
        await self._auto_remove_from_queue(player, six_mans_queue)
    except:
        pass


async def cancel_timeout_task(
    self, player: discord.Member, six_mans_queue: SixMansQueue
):
    try:
        self.timeout_tasks[player][six_mans_queue].cancel()
        await self.remove_timeout_task(player, six_mans_queue)
    except:
        pass


async def remove_timeout_task(
    self, player: discord.Member, six_mans_queue: SixMansQueue
):
    try:
        del self.timeout_tasks[player][six_mans_queue]
        if not self.timeout_tasks[player]:
            del self.timeout_tasks[player]
    except:
        pass


async def _finish_game(
    self,
    guild: discord.Guild,
    game: Game,
    six_mans_queue: SixMansQueue,
    winning_team,
):
    winning_players = []
    losing_players = []
    if winning_team.lower() == "blue":
        winning_players = game.blue
        losing_players = game.orange
    else:
        winning_players = game.orange
        losing_players = game.blue

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
        if qlobby_vc:
            await self._move_to_voice(qlobby_vc, game.voiceChannels[0].members)
            await self._move_to_voice(qlobby_vc, game.voiceChannels[1].members)

    await self._remove_game(guild, game)


async def _move_to_voice(self, vc: discord.VoiceChannel, members: List[discord.Member]):
    for member in members:
        try:
            await member.move_to(vc)
        except:
            pass


async def _remove_game(self, guild: discord.Guild, game: Game):
    self.games[guild].remove(game)
    await self._save_games(guild, self.games[guild])
    await asyncio.sleep(CHANNEL_SLEEP_TIME)
    q_lobby_vc = await self._get_q_lobby_vc(guild)
    if not game.scoreReported:
        game.state = GameState.CANCELLED
    try:
        await game.textChannel.delete()
    except:
        pass
    for vc in game.voiceChannels:
        try:
            try:
                if q_lobby_vc:
                    for player in vc.members:
                        await player.move_to(q_lobby_vc)
            except:
                pass
            await vc.delete()
        except:
            pass


def _get_opposing_captain(self, player: discord.Member, game: Game):
    opposing_captain = None
    if game.state == GameState.NEW:
        players = list(game.players)
        players.remove(player)
        return random.choice(players)

    if player in game.blue:
        opposing_captain = game.captains[1]  # Orange team captain
    elif player in game.orange:
        opposing_captain = game.captains[0]  # Blue team captain
    return opposing_captain


def _swap_opposing_captain(self, game: Game, opposing_captain):
    if opposing_captain in game.blue:
        game.captains[0] = random.sample(list(game.blue), 1)[
            0
        ]  # Swap Blue team captain
    elif opposing_captain in game.orange:
        game.captains[1] = random.sample(list(game.orange), 1)[
            0
        ]  # Swap Orange team captain


def _give_points(self, players_dict, score):
    player_id = score["Player"]
    points_earned = score["Points"]
    win = score["Win"]

    player_dict = players_dict.setdefault(f"{player_id}", {})
    player_dict[Strings.PLAYER_POINTS_KEY] = (
        player_dict.get(Strings.PLAYER_POINTS_KEY, 0) + points_earned
    )
    player_dict[Strings.PLAYER_GP_KEY] = player_dict.get(Strings.PLAYER_GP_KEY, 0) + 1
    player_dict[Strings.PLAYER_WINS_KEY] = (
        player_dict.get(Strings.PLAYER_WINS_KEY, 0) + win
    )


def _create_player_score(
    self,
    six_mans_queue: SixMansQueue,
    game: Game,
    player: discord.Member,
    win,
    date_time,
):
    points_dict = six_mans_queue.points
    if win:
        points_earned = (
            points_dict[Strings.PP_PLAY_KEY] + points_dict[Strings.PP_WIN_KEY]
        )
    else:
        points_earned = points_dict[Strings.PP_PLAY_KEY]
    return {
        "Game": game.id,
        "Queue": six_mans_queue.id,
        "Player": player.id,
        "Win": win,
        "Points": points_earned,
        "DateTime": date_time,
    }


def _filter_scores(self, guild, scores, start_date, queue_id):
    players = {}
    valid_scores = 0
    for score in scores:
        date_time = datetime.datetime.strptime(
            score["DateTime"], "%d-%b-%Y (%H:%M:%S.%f)"
        )
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
    return sorted(
        sorted_players, key=lambda x: x[1][Strings.PLAYER_POINTS_KEY], reverse=True
    )


async def _pop_queue(self, ctx: Context, six_mans_queue: SixMansQueue) -> bool:
    """Pop Queue"""
    log.debug(f"Creating game. Guild: {ctx.guild.id} Queue: {six_mans_queue.name}")
    game = await self._create_game(ctx.guild, six_mans_queue, prefix=ctx.prefix)
    if game is None:
        return False

    # Remove players from any other queue they were in
    for player in game.players:
        for queue in self.queues[ctx.guild]:
            if player in queue.queue:
                await self._remove_from_queue(player, queue)

    return True


async def _create_game(
    self, guild: discord.Guild, six_mans_queue: SixMansQueue, prefix="?"
):
    if not six_mans_queue._queue_full():
        return None
    players = [six_mans_queue._get() for _ in range(six_mans_queue.maxSize)]

    await six_mans_queue.send_message(
        message="**Queue is full! Game is being created.**"
    )

    game = Game(
        players,
        six_mans_queue,
        helper_role=await self._helper_role(guild),
        automove=await self._get_automove(guild),
        prefix=prefix,
    )
    await game.create_game_channels(await self._category(guild))

    log.debug(f"Saving game: {game.id} Players: {game.players}")
    self.games[guild].append(game)
    await self._save_games(guild, self.games[guild])

    await game.process_team_selection_method()
    return game


async def _get_info(self, ctx: Context) -> tuple:
    game = self._get_game_by_text_channel(ctx.channel)
    if game is None:
        await ctx.send(
            f":x: This command can only be used in a {self.queueMaxSize[ctx.guild]} Mans game channel."
        )
        return None, None

    for queue in self.queues[ctx.guild]:
        if queue.id == game.queue.id:
            return game, queue

    await ctx.send(
        ":x: Queue not found for this channel, please message an Admin if you think this is a mistake."
    )
    return None, None


def is_valid_ts(self, team_selection):
    try:
        ts = GameMode(team_selection)
        return ts
    except ValueError:
        return None


def _get_game_and_queue(self, channel: discord.TextChannel):
    game = self._get_game_by_text_channel(channel)
    if game:
        return game, game.queue
    else:
        return None, None


def _get_game_by_text_channel(self, channel: discord.TextChannel):
    log.debug(f"Games: {self.games}")
    for game in self.games.get(channel.guild, []):
        if game.textChannel == channel:
            return game
    return None


def _get_queue_by_text_channel(self, channel: discord.TextChannel):
    try:
        target_queue = self.queues[channel.guild][channel.id]
        return target_queue
    except:
        return None


async def _get_queue_by_name(self, guild: discord.Guild, queue_name: str):
    for queue in self.queues[guild]:
        if queue.name == queue_name:
            return queue
    return None


async def process_six_mans_reaction_add(
    self,
    message: discord.Message,
    channel: discord.TextChannel,
    user: discord.User,
    emoji,
):
    # Note: This may be called TWICE both by on_reaction and/or on_raw_reaction
    if user.bot:
        return

    # on_raw_reaction_add
    if type(emoji) == discord.partial_emoji.PartialEmoji:
        emoji = emoji.name

    # Find Game
    game: Game = self._get_game_by_text_channel(channel)
    if not game:
        return False
    if message != game.info_message:
        return False

    match game.teamSelection:
        case GameMode.VOTE:
            await game.process_team_select_vote(emoji, user)
        case GameMode.CAPTAINS:
            await game.process_captains_pick(emoji, user)
        case GameMode.SELF_PICK:
            await game.process_self_picking_teams(emoji, user, True)


async def process_six_mans_reaction_removed(
    self, channel: discord.TextChannel, user: discord.User, emoji
):
    # Note: This may be called TWICE both by on_reaction and/or on_raw_reaction
    if user.bot:
        return

    # on_raw_reaction_add
    if type(emoji) == discord.partial_emoji.PartialEmoji:
        emoji = emoji.name
    try:
        game = self._get_game_by_text_channel(channel)
        game: Game
        if not game:
            return False

        if game.teamSelection == GameMode.VOTE:
            await game.process_team_select_vote(emoji, user, added=False)

        elif game.teamSelection == GameMode.SELF_PICK:
            await game.process_self_picking_teams(emoji, user, False)
    except:
        pass


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
    emoji = queue.get_ts_emoji()
    if emoji:
        embed.add_field(
            name="Team Selection",
            value=f"{emoji} {queue.teamSelection}",
            inline=False,
        )
    else:
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


def embed_active_games(self, guild, queueGames: Dict[int, List[Game]]):
    embed = discord.Embed(
        title=f"{self.queueMaxSize[guild]} Mans Active Games",
        color=discord.Colour.blue(),
    )
    for queueId in queueGames.keys():
        games = queueGames[queueId]
        queueName = next(
            queue.name for queue in self.queues[guild] if queue.id == queueId
        )
        embed.add_field(
            name=f"{queueName}:",
            value="\n".join(
                [
                    f"{str(game.id)}\n{', '.join([player.mention for player in game.players])}"
                    for game in games
                ]
            ),
            inline=False,
        )
    return embed


async def embed_leaderboard(
    self, ctx: Context, sorted_players, queue_name, games_played, lb_format
):
    embed = discord.Embed(
        title=f"{queue_name} {self.queueMaxSize[ctx.guild]} Mans {lb_format} Leaderboard",
        color=discord.Colour.blue(),
    )
    embed.add_field(name="Games Played", value=f"{games_played}\n", inline=True)
    embed.add_field(
        name="Unique Players", value=f"{len(sorted_players)}\n", inline=True
    )
    embed.add_field(
        name="⠀", value="⠀", inline=True
    )  # Blank field added to push the Player and Stats fields to a new line

    index = 1
    playerStrings = []
    statStrings = []
    for player in sorted_players:
        try:
            member: discord.Member = await commands.MemberConverter().convert(
                ctx, player[0]
            )
        except:
            await ctx.send(f":x: Can't find player with id: {player[0]}")
            continue

        player_info = player[1]
        playerStrings.append(f"`{index}` **{member.display_name:25s}:**")
        try:
            player_wins = player_info[Strings.PLAYER_WINS_KEY]
            player_gp = player_info[Strings.PLAYER_GP_KEY]
            player_wp = round(player_wins / player_gp * 100, 1)
            player_wp = f"{player_wp}%" if player_wp != 100 else "100%"
        except ZeroDivisionError:
            player_wp = "N/A"

        statStrings.append(
            f"Points: `{player_info[Strings.PLAYER_POINTS_KEY]:4d}`  Wins: `{player_wins:3d}`  GP: `{player_gp:3d}` WP: `{player_wp:5s}`"
        )

        index += 1
        if index > 10:
            break

    author = ctx.author
    try:
        author_index = [y[0] for y in sorted_players].index(f"{author.id}")
        if author_index is not None and author_index > 9:
            author_info = sorted_players[author_index][1]
            playerStrings.append(
                f"\n`{author_index + 1}` **{author.display_name:25s}:**"
            )
            try:
                author_wins = author_info[Strings.PLAYER_WINS_KEY]
                author_gp = author_info[Strings.PLAYER_GP_KEY]
                author_wp = round(author_wins / author_gp * 100, 1)
                author_wp = f"{author_wp}%" if author_wp != 100 else "100%"
            except ZeroDivisionError:
                author_wp = "N/A"

            statStrings.append(
                f"\nPoints: `{author_info[Strings.PLAYER_POINTS_KEY]:4d}`  Wins: `{author_wins:3d}`  GP: `{author_gp:3d}` WP: `{author_wp:5s}`"
            )
    except Exception:
        pass

    embed.add_field(name="Player", value="\n".join(playerStrings) + "\n", inline=True)
    embed.add_field(name="Stats", value="\n".join(statStrings) + "\n", inline=True)
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
            title=f"{player.display_name} {queue_name} {queue_max_size} Mans {rank_format} Rank",
            color=discord.Colour.blue(),
        )
        embed.set_thumbnail(url=player.display_avatar.url)
        embed.add_field(
            name="Points:",
            value=f"**Value:** {points} | **Rank:** {points_index + 1}/{num_players}",
            inline=True,
        )
        embed.add_field(
            name="Wins:",
            value=f"**Value:** {wins} | **Rank:** {wins_index + 1}/{num_players}",
            inline=True,
        )
        embed.add_field(
            name="Games Played:",
            value=f"**Value:** {games_played} | **Rank:** {games_played_index + 1}/{num_players}",
            inline=True,
        )
    except:
        embed = discord.Embed(
            title=f"{player.display_name} {queue_name} {queue_max_size} Mans {rank_format} Rank",
            color=discord.Colour.red(),
            description=f"No stats yet to rank {player.mention}",
        )
        embed.set_thumbnail(url=player.display_avatar.url)
    return embed


def format_player_list(self, queue: SixMansQueue):
    player_list = ", ".join([player.mention for player in queue.queue.queue])
    if player_list == "":
        player_list = "No players currently in the queue"
    return player_list


# endregion
