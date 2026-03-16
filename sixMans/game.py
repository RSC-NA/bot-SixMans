import logging
import random
import uuid
from itertools import combinations
from pprint import pformat

import discord

from sixMans import utils
from sixMans.embeds import GreenEmbed
from sixMans.enums import GameMode, GameState, Winner
from sixMans.queue import SixMansQueue
from sixMans.strings import Strings
from sixMans.views.captains import CaptainsView
from sixMans.views.selfpick import SelfPickingView
from sixMans.views.vote import GameModeVote

log = logging.getLogger("red.sixMans.game")

# SELECTION_MODES = {
#     0x1F3B2: Strings.RANDOM_TS,  # game_die
#     0x1F1E8: Strings.CAPTAINS_TS,  # C
#     0x1F530: Strings.SELF_PICKING_TS,  # beginner
#     0x0262F: Strings.BALANCED_TS,  # yin_yang
# }

SELECTION_MODES = {
    Strings.RANDOM_TS: 0x1F3B2,  # game_die
    Strings.CAPTAINS_TS: 0x1F1E8,  # C
    Strings.SELF_PICKING_TS: 0x1F530,  # beginner
    Strings.BALANCED_TS: 0x0262F,  # yin_yang
}


class Game:
    def __init__(
        self,
        queue: SixMansQueue,
        players: list[discord.Member],
        automove: bool = False,
        blue: list[discord.Member] | None = None,
        orange: list[discord.Member] | None = None,
        captains: list[discord.Member] | None = None,
        helper_role: discord.Role | None = None,
        id: int | None = None,
        info_message: discord.Message | None = None,
        prefix: str = "?",
        roomName: str | None = None,
        roomPass: str | None = None,
        state: GameState = GameState.NEW,
        teamSelection: GameMode | None = None,
        text_channel: discord.TextChannel | None = None,
        voice_channels: list[discord.VoiceChannel] | None = None,
        winner: Winner = Winner.PENDING,
    ):
        # Setup
        self.player_votes: dict[discord.Member, int] = {}
        self.reaction_lock = False

        # Core
        self.id = id or uuid.uuid4().int
        self.queue: SixMansQueue = queue
        self.state: GameState = state
        self.prefix: str = prefix
        self.winner: Winner = winner

        # Game  Mode
        if teamSelection:
            self.teamSelection: GameMode = teamSelection
        else:
            self.teamSelection = queue.teamSelection

        # Lobby Name/Pass
        self.roomName: str = roomName or self._generate_name_pass()
        self.roomPass: str = roomPass or self._generate_name_pass()

        # Teams

        self.players = set(players)
        self.captains: list[discord.Member] = captains or []

        if blue:
            self.blue: set[discord.Member] = set(blue)
        else:
            self.blue = set()

        if orange:
            self.orange: set[discord.Member] = set(orange)
        else:
            self.orange = set()

        # Channels
        self.textChannel: discord.TextChannel | None = text_channel

        # List of voice channels: [Blue, Orange, General]
        self.voiceChannels: list[discord.VoiceChannel] = voice_channels or []

        # Optional params
        self.helper_role: discord.Role | None = helper_role
        self.automove = automove
        self.info_message = info_message

        log.debug(f"Game created. ID: {self.id} Players: {self.players}")

    # Team Management
    async def create_game_channels(self, category=None):
        if not category:
            category = self.queue.category
        guild = self.queue.guild
        # sync permissions on channel creation, and edit overwrites (@everyone) immediately after

        code = str(self.id)[-3:]

        # Create Game Text Channel
        self.textChannel = await guild.create_text_channel(
            f"{code} {self.queue.name} {self.queue.maxSize} Mans", category=category
        )
        await self.textChannel.set_permissions(
            guild.default_role, view_channel=False, read_messages=False
        )
        for player in self.players:
            if isinstance(player, discord.Member):
                await self.textChannel.set_permissions(player, read_messages=True)

        # Create a general VC lobby for all players in a session
        general_vc = await guild.create_voice_channel(
            f"{code} | {self.queue.name} General VC",
            category=category,
        )
        await general_vc.set_permissions(guild.default_role, connect=False)

        blue_vc = await guild.create_voice_channel(
            f"{code} | {self.queue.name} Blue Team",
            category=category,
        )
        await blue_vc.set_permissions(guild.default_role, connect=False)
        oran_vc = await guild.create_voice_channel(
            f"{code} | {self.queue.name} Orange Team",
            category=category,
        )
        await oran_vc.set_permissions(guild.default_role, connect=False)

        # manually add helper role perms if one is set
        if self.helper_role:
            await self.textChannel.set_permissions(
                self.helper_role, view_channel=True, read_messages=True
            )
            await general_vc.set_permissions(
                self.helper_role, connect=True, move_members=True
            )
            await blue_vc.set_permissions(
                self.helper_role, connect=True, move_members=True
            )
            await oran_vc.set_permissions(
                self.helper_role, connect=True, move_members=True
            )

        self.voiceChannels = [blue_vc, oran_vc, general_vc]

        # Mentions all players
        await self.textChannel.send(" ".join(player.mention for player in self.players))

    # Team Selection
    async def vote_team_selection(self):
        """Start a vote for game mode."""
        vote_view = GameModeVote(self)
        await vote_view.start()
        await vote_view.wait()

        if not self.textChannel:
            return

        if not vote_view.result:
            # Vote failed. We need to decide what to do here.
            await self.textChannel.send("Error during game mode vote... Please report.")
            return

        self.state = GameState.SELECTION
        self.teamSelection = vote_view.result
        log.debug(f"Game mode vote finished. Result: {self.teamSelection}")

        # Dispatch
        match self.teamSelection:
            case GameMode.CAPTAINS:
                await self.captains_pick_teams()
            case GameMode.RANDOM:
                await self.pick_random_teams()
            case GameMode.SELF_PICK:
                await self.self_picking_teams()
            case GameMode.BALANCED:
                await self.pick_balanced_teams()
            case _:
                log.error(f"Error during game mode vote: {vote_view.result}")

    async def captains_pick_teams(self):
        """Initiate Captains Game Mode"""
        log.debug(
            f"Game Players: {type(self.players)}\n{pformat([f'{p.id}: {p.name}' for p in self.players])}"
        )
        captains_view = CaptainsView(self)
        await captains_view.start()
        await captains_view.wait()

        if not self.textChannel:
            return

        if not captains_view:
            await self.textChannel.send(
                "Error: Unable to finish captains team selection. Please reach out for support."
            )
            return

        self.captains = captains_view.captains
        self.blue = set(captains_view.blue)
        self.orange = set(captains_view.orange)
        self.state = GameState.ONGOING
        await self.send_game_info()

    async def pick_random_teams(self):
        self.blue = set()
        self.orange = set()

        # Random generate teams
        orange_players = set(random.sample(tuple(self.players), len(self.players) // 2))
        blue_players = self.players - orange_players
        for p in orange_players:
            self.add_to_orange(p)
        for p in blue_players:
            self.add_to_blue(p)
        self.reset_players()
        self.get_new_captains_from_teams()
        await self.update_player_perms()
        await self.send_game_info()
        self.state = GameState.ONGOING

    async def self_picking_teams(self):
        picking_view = SelfPickingView(game=self, helper=self.helper_role)
        await picking_view.prompt()
        await picking_view.wait()

        if not picking_view.finished:
            await self.textChannel.send(
                content="Error during team selection. Please reach out for support."
            )
            return

        self.orange = set(picking_view.orange)
        self.blue = set(picking_view.blue)
        self.state = GameState.ONGOING
        await self.send_game_info()

    async def pick_balanced_teams(self):
        balanced_teams, balance_score = self.get_balanced_teams()
        self.balance_score = balance_score
        # Pick random balanced team
        blue = random.choice(balanced_teams)
        orange = []
        for player in self.players:
            if player not in blue:
                orange.append(player)
        for player in blue:
            self.add_to_blue(player)
        for player in orange:
            self.add_to_orange(player)

        self.reset_players()
        self.get_new_captains_from_teams()
        await self.update_player_perms()
        await self.send_game_info()
        self.state = GameState.ONGOING

    async def shuffle_players(self):
        await self.pick_random_teams()

        if not self.info_message:
            return
        await self.info_message.add_reaction(Strings.SHUFFLE_REACT)

    # Team Selection helpers
    async def process_team_selection_method(
        self, team_selection: GameMode | None = None, force: bool = False
    ):
        log.debug(f"Processing team selection. Current State: {self.state}")

        if self.state == GameState.ONGOING and not force:
            log.debug("Game has started already... skipping team selection processing")
            return

        if team_selection:
            self.teamSelection = team_selection

        self.state = GameState.SELECTION
        self.full_player_reset()

        match self.teamSelection:
            case GameMode.VOTE:
                await self.vote_team_selection()
            case GameMode.CAPTAINS:
                await self.captains_pick_teams()
            case GameMode.RANDOM:
                await self.pick_random_teams()
            case GameMode.SELF_PICK:
                await self.self_picking_teams()
            case GameMode.BALANCED:
                await self.pick_balanced_teams()
            case GameMode.DEFAULT:
                # Use queue default game mode
                await self.process_team_selection_method(self.queue.teamSelection)
            case _:
                # End game here potentially?
                log.error(f"Error processing team selection mode: {self.teamSelection}")

    def get_balanced_teams(self):
        # Get relevant info from helpers
        player_scores = self.get_player_scores()
        team_combos = list(combinations(list(self.players), len(self.players) // 2))

        # Calc perfectly balanced team based on scores
        score_total = 0
        for p_data in player_scores.values():
            score_total += p_data["Score"]
        avg_team_score = score_total / 2

        # Determine balanced teams
        balanced_teams = []
        balance_diff = None
        for a_team in team_combos:
            team_score = 0
            for player in a_team:
                team_score += player_scores[player]["Score"]

            team_diff = abs(avg_team_score - team_score)
            if balance_diff:
                if team_diff < balance_diff:
                    balance_diff = team_diff
                    balanced_teams = [a_team]
                elif team_diff == balance_diff:
                    balanced_teams.append(a_team)
            else:
                balance_diff = team_diff
                balanced_teams = [a_team]

        # return balanced team
        self.state = GameState.ONGOING
        return balanced_teams, team_diff

    def get_player_scores(self):
        # Get Player Stats
        scores = {}
        ranked_players = 0
        rank_total = 0
        wp_players = 0
        wp_total = 0
        # Get each player's "rank" and QWP
        for player in self.players:
            player_stats = self.queue.get_player_summary(player)

            rank = 1  # get_player_rank
            if player_stats:
                p_wins = player_stats["Wins"]
                p_losses = player_stats["GamesPlayed"] - p_wins
                qwp = round(self._get_wp(p_wins, p_losses), 2)
            else:
                qwp = None

            scores[player] = {"Rank": rank, "QWP": qwp}
            if rank:
                ranked_players += 1
                rank_total += rank
            if qwp:
                wp_players += 1
                wp_total += qwp

        rank_avg = rank_total / ranked_players if ranked_players else 1

        # Score Players, Avg
        score_total = 0
        for p_data in scores.values():
            p_rank = (
                p_data["Rank"] if ("Rank" in p_data and p_data["Rank"]) else rank_avg
            )
            p_wp = p_data["QWP"] if ("QWP" in p_data and p_data["QWP"]) else 0.5
            score_adj = (p_wp * 2) - 1  # +/- 1

            score = p_rank + score_adj
            p_data["Score"] = score
            score_total += score

        # p_data['AvgPlayerScore'] = score_total/len(self.players)

        return scores

    async def report_winner(self, winner: Winner):
        self.winner = winner
        await self.color_embed_for_winners(winner)
        self.state = GameState.COMPLETE

    # Embeds & Emojis
    async def send_game_info(self):
        log.debug(f"Game Mode: {self.teamSelection}")
        ts_emoji = utils.get_emoji(SELECTION_MODES.get(self.teamSelection.value))

        embed = GreenEmbed(
            title=f"{self.queue.name} {self.queue.maxSize} Mans Game Info",
        )

        # Team Selection
        if ts_emoji:
            ts_fmt = f"{ts_emoji} {self.teamSelection}"
        else:
            ts_fmt = f"{self.teamSelection}"

        embed.add_field(
            name="Team Selection",
            value=ts_fmt,
            inline=False,
        )

        # Teams
        embed.add_field(
            name="Blue",
            value="\n".join([player.mention for player in self.blue]),
            inline=True,
        )
        embed.add_field(
            name="Orange",
            value="\n".join([player.mention for player in self.orange]),
            inline=True,
        )
        embed.add_field(
            name="Lobby Info",
            value=f"```{self.roomName} // {self.roomPass}```",
            inline=False,
        )

        creator = list(self.blue)[0].mention
        embed.add_field(name="Lobby Creator", value=creator, inline=False)

        # Additional Info
        embed.add_field(
            name="Commands",
            value=Strings.sixmans_highlight_commands.format(prefix=self.prefix),
        )

        if self.helper_role:
            embed.add_field(
                name="Help",
                value=Strings.more_sixmans_info_helper.format(
                    helper=self.helper_role.mention
                ),
                inline=False,
            )

        embed.set_footer(text="Game ID: {}".format(self.id))
        if self.queue.guild.icon:
            embed.set_thumbnail(url=self.queue.guild.icon.url)
        self.info_message = await self.textChannel.send(embed=embed)

    async def post_more_lobby_info(self, helper_role=None, invalid=False):
        if not helper_role:
            helper_role = self.helper_role

        sm_title = "{0} {1} Mans Game Info".format(self.queue.name, self.queue.maxSize)

        embed_color = discord.Colour.green()
        if invalid:
            sm_title += " :x: [Teams Changed]"
            embed_color = discord.Colour.red()

        embed = discord.Embed(title=sm_title, color=embed_color)

        if self.queue.guild.icon:
            embed.set_thumbnail(url=self.queue.guild.icon.url)

        if self.queue.teamSelection == Strings.VOTE_TS:
            team_selection = self.teamSelection.value

            if team_selection == Strings.BALANCED_TS and self.balance_score:
                team_selection += f"\n\nBalance Score: {self.balance_score}"
                team_selection += "\n_Lower Balance Scores = More Balanced_"

            embed.add_field(
                name="Team Selection",
                value=f"{team_selection}",
                inline=False,
            )

        embed.add_field(
            name="Blue Team",
            value=", ".join([player.mention for player in self.blue]) + '\n',
            inline=False,
        )
        embed.add_field(
            name="Orange Team",
            value=", ".join([player.mention for player in self.orange]) + '\n',
            inline=False,
        )
        if not invalid:
            embed.add_field(
                name="Captains",
                value=f"**Blue:** {self.captains[0].mention}\n**Orange:** {self.captains[1].mention}",
                inline=False,
            )
        embed.add_field(
            name="Lobby Info",
            value=f"**Name:** {self.roomName}\n**Password:** {self.roomPass}",
            inline=False,
        )
        embed.add_field(
            name="Point Breakdown",
            value=f"**Playing:** {self.queue.points[Strings.PP_PLAY_KEY]}\n**Winning Bonus:** {self.queue.points[Strings.PP_WIN_KEY]}",
            inline=False,
        )
        if not invalid:
            embed.add_field(
                name="Additional Info",
                value="Feel free to play whatever type of series you want, whether a bo3, bo5, or any other.\n\n"
                "When you are done playing with the current teams please report the winning team "
                "using the command `{0}sr [winning_team]` where the `winning_team` parameter is either "
                "`Blue` or `Orange`. Both teams will need to verify the results.\n\n"
                "If you wish to cancel the game and allow players to queue again you can use the `{0}cg` command."
                " Both teams will need to verify that they wish to "
                "cancel the game.".format(self.prefix),
                inline=False,
            )
        help_message = (
            "If you think the bot isn't working correctly or have suggestions to improve it"
            ", please contact the RSC Development Committee."
        )
        if helper_role:
            help_message = (
                f"If you need any help or have questions please contact someone with the {helper_role.mention} role. " + help_message
            )
        embed.add_field(name="Help", value=help_message, inline=False)
        embed.set_footer(text=f"Game ID: {self.id}")

        self.info_message = await self.textChannel.send(embed=embed)

    def has_lobby_info(self):
        return (
            self.roomName
            and self.roomPass
            and len(self.blue) + len(self.orange) == self.queue.maxSize
        )

    async def post_lobby_info(self):
        if not self.has_lobby_info():
            return
        embed = discord.Embed(
            title=f"{self.queue.name} {self.queue.maxSize} Mans Game Info",
            color=discord.Colour.green(),
        )
        embed.add_field(
            name="Blue",
            value="\n".join([player.mention for player in self.blue]) + '\n',
            inline=True,
        )
        embed.add_field(
            name="Orange",
            value="\n".join([player.mention for player in self.orange]) + '\n',
            inline=True,
        )

        embed.add_field(
            name="Lobby Info",
            value=f"```{self.roomName} // {self.roomPass}```",
            inline=False,
        )
        embed.set_footer(text="Game ID: {}".format(self.id))
        if self.queue.guild.icon:
            embed.set_thumbnail(url=self.queue.guild.icon.url)
        await self.textChannel.send(embed=embed)

    def _hex_i_from_emoji(self, emoji):
        return ord(emoji)

    async def color_embed_for_winners(self, winner: Winner):
        if self.info_message is not None:
            match winner:
                case Winner.BLUE:
                    color = discord.Colour.blue()
                case Winner.ORANGE:
                    color = discord.Colour.orange()
                case Winner.PENDING:
                    color = discord.Colour.yellow()

            embed = self.info_message.embeds[0]
            embed.colour = color
            await self.info_message.edit(embed=embed)

    # General Helper Commands

    def add_to_blue(self, player):
        if player in self.orange:
            self.orange.remove(player)
        if player in self.players:
            self.players.remove(player)
        self.blue.add(player)

    def add_to_orange(self, player):
        if player in self.blue:
            self.blue.remove(player)
        if player in self.players:
            self.players.remove(player)
        self.orange.add(player)

    async def update_player_perms(self):
        blue_vc, orange_vc, general_vc = self.voiceChannels

        for player in self.orange:
            await general_vc.set_permissions(player, connect=True)
            await blue_vc.set_permissions(player, connect=False)
            await orange_vc.set_permissions(player, connect=True)

            if self.automove:
                try:
                    await player.move_to(orange_vc)
                except (discord.Forbidden, discord.HTTPException):
                    pass
                except TypeError as exc:
                    log.warning("Bad type passed to `Member.move_to()`", exc_info=exc)

        for player in self.blue:
            await general_vc.set_permissions(player, connect=True)
            await blue_vc.set_permissions(player, connect=True)
            await orange_vc.set_permissions(player, connect=False)

            if self.automove:
                try:
                    await player.move_to(blue_vc)
                except (discord.Forbidden, discord.HTTPException):
                    pass
                except TypeError as exc:
                    log.warning("Bad type passed to `Member.move_to()`", exc_info=exc)

    def full_player_reset(self):
        self.reset_players()
        self.blue = set()
        self.orange = set()

    def reset_players(self):
        self.players.update(self.orange)
        self.players.update(self.blue)

    def get_new_captains_from_teams(self):
        self.captains = []
        if not self.blue or not self.orange:
            raise ValueError("Blue or orange team has no players to pick captain from")
        self.captains.append(random.sample(list(self.blue), 1)[0])
        self.captains.append(random.sample(list(self.orange), 1)[0])

    def _generate_name_pass(self):
        return Strings.room_pass[random.randrange(len(Strings.room_pass))]

    def _get_wp(self, wins, losses):
        try:
            return wins / (wins + losses)
        except ZeroDivisionError:
            return None

    def __contains__(self, item):
        return item in self.players or item in self.orange or item in self.blue

    def _to_dict(self):
        vc_channels = []
        if self.voiceChannels:
            vc_channels = [x.id for x in self.voiceChannels]

        game_dict = {
            "Players": [x.id for x in self.players],
            "Captains": [x.id for x in self.captains],
            "Blue": [x.id for x in self.blue],
            "Orange": [x.id for x in self.orange],
            "RoomName": self.roomName,
            "RoomPass": self.roomPass,
            "VoiceChannels": vc_channels,
            "QueueId": self.queue.id,
            "TeamSelection": self.teamSelection,
            "State": self.state,
            "Prefix": self.prefix,
            "Winner": self.winner,
        }
        if self.info_message:
            game_dict["InfoMessage"] = self.info_message.id
        if self.textChannel:
            game_dict["TextChannel"] = self.textChannel.id
        if self.helper_role:
            game_dict["HelperRole"] = self.helper_role.id

        return game_dict
