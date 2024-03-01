import asyncio
import contextlib
import logging
import random
import struct
import uuid
from itertools import combinations
from pprint import pformat

import discord

from sixMans.enums import GameMode, GameState, Winner
from sixMans.queue import SixMansQueue
from sixMans.strings import Strings
from sixMans.views import CaptainsView, GameModeVote, SelfPickingView

log = logging.getLogger("red.RSC6Mans.sixMans.game")

SELECTION_MODES = {
    0x1F3B2: Strings.RANDOM_TS,  # game_die
    0x1F1E8: Strings.CAPTAINS_TS,  # C
    0x1F530: Strings.SELF_PICKING_TS,  # beginner
    0x0262F: Strings.BALANCED_TS,  # yin_yang
}


class Game:
    def __init__(
        self,
        players: list[discord.Member],
        queue: SixMansQueue,
        helper_role: discord.Role | None = None,
        automove: bool = False,
        text_channel: discord.TextChannel | None = None,
        voice_channels: list[discord.VoiceChannel] | None = None,
        info_message: discord.Message | None = None,
        prefix: str = "?",
    ):
        self.id = uuid.uuid4().int
        self.players = set(players)
        self.player_votes: dict[discord.Member, int] = {}
        self.captains: list[discord.Member] = []
        self.blue: set[discord.Member] = set()
        self.orange: set[discord.Member] = set()
        self.roomName = self._generate_name_pass()
        self.roomPass = self._generate_name_pass()
        self.queue = queue
        self.winner = Winner.PENDING
        self.teamSelection: GameMode = queue.teamSelection
        self.state: GameState = GameState.NEW
        self.prefix = prefix
        self.reaction_lock = False
        log.debug(f"Game created. ID: {self.id} Players: {self.players}")

        # Optional params
        self.helper_role = helper_role
        self.automove = automove
        self.textChannel = text_channel
        self.voiceChannels = (
            voice_channels  # List of voice channels: [Blue, Orange, General]
        )
        self.info_message = info_message

    # Team Management
    async def create_game_channels(self, category=None):
        if not category:
            category = self.queue.category
        guild = self.queue.guild
        # sync permissions on channel creation, and edit overwrites (@everyone) immediately after
        code = str(self.id)[-3:]
        self.textChannel = await guild.create_text_channel(
            f"{code} {self.queue.name} {self.queue.maxSize} Mans",
            category=category,
        )
        await self.textChannel.set_permissions(
            guild.default_role, view_channel=False, read_messages=False
        )
        for player in self.players:
            if isinstance(player, discord.Member):
                await self.textChannel.set_permissions(player, read_messages=True)

        # create a general VC lobby for all players in a session
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
                await self.captains_pick_teams(self.helper_role)
            case GameMode.RANDOM:
                await self.pick_random_teams()
            case GameMode.SELF_PICK:
                await self.self_picking_teams()
            case GameMode.BALANCED:
                await self.pick_balanced_teams()
            case _:
                log.error(f"Error during game mode vote: {vote_view.result}")

    async def captains_pick_teams(self, helper_role=None):
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
        for player in random.sample(tuple(self.players), int(len(self.players) // 2)):
            self.add_to_orange(player)
        blue = list(self.players)
        for player in blue:
            self.add_to_blue(player)
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
    async def process_team_selection_method(self, team_selection=None):
        if not team_selection:
            team_selection = self.teamSelection

        if self.state == GameState.ONGOING:
            log.debug("Game has started already... skipping team selection processing")
            return

        self.full_player_reset()
        team_selection = team_selection.lower()
        helper_role = self.helper_role

        match self.teamSelection:
            case GameMode.VOTE:
                await self.vote_team_selection()
            case GameMode.CAPTAINS:
                await self.captains_pick_teams(helper_role)
            case GameMode.RANDOM:
                await self.pick_random_teams()
            case GameMode.SELF_PICK:
                await self.self_picking_teams()
            case GameMode.BALANCED:
                await self.pick_balanced_teams()
            case GameMode.DEFAULT:
                if self.queue.teamSelection.lower() != team_selection:
                    return self.process_team_selection_method(self.queue.teamSelection)
                guild_ts = await self._guild_team_selection()
                return self.process_team_selection_method(guild_ts)
            case _:
                # End game here potentially?
                log.error(f"Error processing team selection mode: {self.teamSelection}")

    async def process_self_picking_teams(self, emoji, user, added=True):
        if not self.textChannel:
            return

        if not self.info_message:
            return

        self.info_message = await self.textChannel.fetch_message(self.info_message.id)
        if self.state != GameState.NEW:
            return False

        if user not in set(list(self.blue) + list(self.orange) + list(self.players)):
            try:
                if ord(emoji) in [Strings.ORANGE_REACT, Strings.BLUE_REACT]:
                    self.info_message = await self.textChannel.fetch_message(
                        self.info_message.id
                    )
                    for reaction in self.info_message.reactions:
                        reacted_members = [gen async for gen in reaction.users()]
                        if reaction.emoji == emoji and user in reacted_members:
                            await reaction.remove(user)
                            break
            except TypeError as exc:
                log.exception("Type error in self picking teams", exc_info=exc)
                pass
            return

        if added:
            if ord(emoji) == Strings.ORANGE_REACT:
                if len(self.orange) < self.queue.maxSize // 2:
                    self.add_to_orange(user)
                # Remove opposite color reaction
                for react in self.info_message.reactions:
                    emoji = react.emoji

                    if ord(emoji) == Strings.BLUE_REACT:
                        reacted_members = [gen async for gen in reaction.users()]
                        if user in reacted_members:
                            with contextlib.suppress(
                                discord.HTTPException,
                                discord.Forbidden,
                                discord.NotFound,
                            ):
                                await react.remove(user)

            elif ord(emoji) == Strings.BLUE_REACT:
                if len(self.blue) < self.queue.maxSize // 2:
                    self.add_to_blue(user)

                # Remove opposite color reaction
                for react in self.info_message.reactions:
                    emoji = react.emoji

                    if ord(emoji) == Strings.ORANGE_REACT:
                        reacted_members = [gen async for gen in reaction.users()]
                        if user in reacted_members:
                            with contextlib.suppress(
                                discord.HTTPException,
                                discord.Forbidden,
                                discord.NotFound,
                            ):
                                await react.remove(user)
            else:
                return
        else:
            if (ord(emoji) == Strings.ORANGE_REACT) and (user in self.orange):
                self.orange.remove(user)
                self.players.add(user)
            elif (ord(emoji) == Strings.BLUE_REACT) and (user in self.blue):
                self.blue.remove(user)
                self.players.add(user)

        embed = self._get_spt_embed()
        await self.info_message.edit(embed=embed)

        # Check if Teams are determined
        teams_finalized = False
        if len(self.orange) == self.queue.maxSize // 2:
            self.blue.update(self.players)
            teams_finalized = True
        elif len(self.blue) == self.queue.maxSize // 2:
            self.orange.update(self.players)
            teams_finalized = True

        if teams_finalized:
            self.reset_players()
            self.get_new_captains_from_teams()
            await self.update_player_perms()
            await self.send_game_info()
            self.state = GameState.ONGOING

    async def _remove_stale_reactions(self, emoji_hex: int, member: discord.Member):
        """
        Removes stale reactions from the info message
        This function removes any reactions from the member that are not the emoji_hex.
        It utilizes an lock to prevent multiple instances of this function from running at the same time.
        """
        if self.reaction_lock:
            return

        if not self.info_message:
            return

        self.reaction_lock = True
        coros = []

        for react_hex, reaction in [
            (react_hex, self._get_pick_reaction(react_hex))
            for react_hex in SELECTION_MODES
        ]:
            if react_hex != emoji_hex:
                coros.append(self.info_message.remove_reaction(reaction, member))

        await asyncio.gather(*coros)
        self.reaction_lock = False

    async def process_team_select_vote(self, emoji, member, added=True):
        if not self.info_message:
            return

        if member not in self.players:
            asyncio.create_task(self.info_message.remove_reaction(emoji, member))
            return

        emoji_hex = self._hex_i_from_emoji(emoji)
        if emoji_hex not in SELECTION_MODES:
            return

        if added:
            await self._remove_stale_reactions(emoji_hex, member)
            self.player_votes[member] = emoji_hex
        elif self.player_votes[member] == emoji_hex:
            self.player_votes.pop(member)

        # ensure we still need to take action
        if self.reaction_lock or self.teamSelection.lower() != Strings.VOTE_TS.lower():
            return

        votes = {react_hex_i: 0 for react_hex_i in SELECTION_MODES}
        for vote in self.player_votes.values():
            votes[vote] += 1
        total_votes = 0
        runner_up = 0
        winning_vote = [None, 0]
        for react_hex, num_votes in votes.items():
            if num_votes > winning_vote[1]:
                runner_up = winning_vote[1]
                winning_vote = [react_hex, num_votes]
            elif num_votes > runner_up and num_votes <= winning_vote[1]:
                runner_up = num_votes
            total_votes += num_votes
        pending_votes = len(self.players) - total_votes
        # Vote Complete if...
        if added and (pending_votes + runner_up) <= winning_vote[1]:
            # action and update first - help with race conditions
            self.teamSelection = SELECTION_MODES[winning_vote[0]]
            embed = self._get_vote_embed(vote=votes, winning_vote=winning_vote[0])
            await self.info_message.edit(embed=embed)
            await self.process_team_selection_method()
        else:
            # Update embed
            embed = self._get_vote_embed(votes)
            await self.info_message.edit(embed=embed)

    def get_balanced_teams(self):
        # Get relevent info from helpers
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

    def _get_pick_reaction(self, int_or_hex):
        try:
            if isinstance(int_or_hex, int):
                return struct.pack("<I", int_or_hex).decode("utf-32le")
            if isinstance(int_or_hex, str):
                return struct.pack("<I", int(int_or_hex, base=16)).decode(
                    "utf-32le"
                )  # i == react_hex
        except (TypeError, ValueError):
            return None

    def _get_pickable_players_str(self):
        players = ""
        for react_hex, player in self.react_player_picks.items():
            react = self._get_pick_reaction(int(react_hex, base=16))
            players += "{} {}\n".format(react, player.mention)
        return players

    # Embeds & Emojis
    async def send_game_info(self):
        embed = discord.Embed(
            title="{0} {1} Mans Game Info".format(self.queue.name, self.queue.maxSize),
            color=discord.Colour.green(),
        )
        ts_emoji = self._get_ts_emoji()
        embed.add_field(
            name="Team Selection",
            value="{} {}".format(ts_emoji, self.teamSelection),
            inline=False,
        )

        embed.set_thumbnail(url=self.queue.guild.icon.url)
        embed.add_field(
            name="Blue",
            value="{}\n".format("\n".join([player.mention for player in self.blue])),
            inline=True,
        )
        embed.add_field(
            name="Orange",
            value="{}\n".format("\n".join([player.mention for player in self.orange])),
            inline=True,
        )

        embed.add_field(
            name="Lobby Info",
            value="```{} // {}```".format(self.roomName, self.roomPass),
            inline=False,
        )

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
            ts_emoji = self._get_ts_emoji()
            team_selection = self.teamSelection.value

            if team_selection == Strings.BALANCED_TS and self.balance_score:
                team_selection += f"\n\nBalance Score: {self.balance_score}"
                team_selection += "\n_Lower Balance Scores = More Balanced_"

            embed.add_field(
                name="Team Selection",
                value="{} {}".format(ts_emoji, team_selection),
                inline=False,
            )

        embed.add_field(
            name="Blue Team",
            value="{}\n".format(", ".join([player.mention for player in self.blue])),
            inline=False,
        )
        embed.add_field(
            name="Orange Team",
            value="{}\n".format(", ".join([player.mention for player in self.orange])),
            inline=False,
        )
        if not invalid:
            embed.add_field(
                name="Captains",
                value="**Blue:** {0}\n**Orange:** {1}".format(
                    self.captains[0].mention, self.captains[1].mention
                ),
                inline=False,
            )
        embed.add_field(
            name="Lobby Info",
            value="**Name:** {0}\n**Password:** {1}".format(
                self.roomName, self.roomPass
            ),
            inline=False,
        )
        embed.add_field(
            name="Point Breakdown",
            value="**Playing:** {0}\n**Winning Bonus:** {1}".format(
                self.queue.points[Strings.PP_PLAY_KEY],
                self.queue.points[Strings.PP_WIN_KEY],
            ),
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
                "If you need any help or have questions please contact someone with the {0} role. ".format(
                    helper_role.mention
                )
                + help_message
            )
        embed.add_field(name="Help", value=help_message, inline=False)
        embed.set_footer(text="Game ID: {}".format(self.id))

        # player_scores = self.get_player_scores()
        # new_player_stats = self.queue.get_player_summary(player)

        # player_scores_str = ""
        # for player in self.blue:
        #     player_scores_str += f"{player}: {player_scores.get(player)}: {new_player_stats}"
        # for player in self.orange:
        #     player_scores_str += f"{player}: {player_scores.get(player)}: {new_player_stats}"

        # embed.description = player_scores_str
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
            title="{0} {1} Mans Game Info".format(self.queue.name, self.queue.maxSize),
            color=discord.Colour.green(),
        )
        embed.set_thumbnail(url=self.queue.guild.icon.url)
        embed.add_field(
            name="Blue",
            value="{}\n".format("\n".join([player.mention for player in self.blue])),
            inline=True,
        )
        embed.add_field(
            name="Orange",
            value="{}\n".format("\n".join([player.mention for player in self.orange])),
            inline=True,
        )

        embed.add_field(
            name="Lobby Info",
            value="```{} // {}```".format(self.roomName, self.roomPass),
            inline=False,
        )
        embed.set_footer(text="Game ID: {}".format(self.id))
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

    def _get_captains_embed(self, pick, guild=None):
        # Determine who picks next
        if pick:
            team_color = (
                discord.Colour.blue() if pick == "blue" else discord.Colour.orange()
            )
            player = self.captains[0] if pick == "blue" else self.captains[1]
            description = (
                "**{}**, react to pick a player to join the **{}** team.".format(
                    player.name, pick
                )
            )

        else:
            team_color = discord.Colour.green()
            description = "Teams are finalized!"

        embed = discord.Embed(
            title="{} Game | Team Selection".format(
                self.textChannel.name.replace("-", " ").title()[4:]
            ),
            color=team_color,
            description=description,
        )
        ts_emoji = self._get_ts_emoji()
        embed.add_field(
            name="Team Selection",
            value="{} {}".format(ts_emoji, self.teamSelection),
            inline=False,
        )

        if pick:
            embed.set_thumbnail(url=player.display_avatar.url)
        elif guild:
            embed.set_thumbnail(url=guild.icon.url)
        else:
            embed.set_thumbnail(url=self.queue.guild.icon.url)

        # List teams as they stand
        embed.add_field(
            name="Blue Team",
            value=", ".join(p.mention for p in self.blue),
            inline=False,
        )
        embed.add_field(
            name="Orange Team",
            value=", ".join(p.mention for p in self.orange),
            inline=False,
        )

        # List available players
        pickable_players = self._get_pickable_players_str()
        if pickable_players:
            embed.add_field(
                name="Available Players", value=pickable_players, inline=False
            )

        if self.helper_role:
            embed.add_field(
                name="Help",
                value="If you need any help or have questions please contact someone with the {} role.".format(
                    self.helper_role.mention
                ),
            )

        embed.set_footer(text="Game ID: {}".format(self.id))

        return embed

    # General Helper Commands

    def full_player_reset(self):
        self.reset_players()
        self.blue = set()
        self.orange = set()

    def reset_players(self):
        self.players.update(self.orange)
        self.players.update(self.blue)

    def get_new_captains_from_teams(self):
        self.captains = []
        self.captains.append(random.sample(list(self.blue), 1)[0])
        self.captains.append(random.sample(list(self.orange), 1)[0])

    def _generate_name_pass(self):
        return Strings.room_pass[random.randrange(len(Strings.room_pass))]

    async def _add_reactions(self, react_hex_codes, message):
        for react_hex_i in react_hex_codes:
            if isinstance(react_hex_i, int):
                react = struct.pack("<I", react_hex_i).decode("utf-32le")
                await message.add_reaction(react)
            elif isinstance(react_hex_i, str):
                react = struct.pack("<I", int(react_hex_i, base=16)).decode("utf-32le")
                await message.add_reaction(react)

    def _get_wp(self, wins, losses):
        try:
            return wins / (wins + losses)
        except ZeroDivisionError:
            return None

    def _get_completion_color(self, voted: int, pending: int):
        if not (voted or pending):
            return discord.Color.default()
        red = (255, 0, 0)
        yellow = (255, 255, 0)
        green = (0, 255, 0)
        wp = self._get_wp(voted, pending)

        if wp == 0:
            return discord.Color.from_rgb(*red)
        if wp == 0.5:
            return discord.Color.from_rgb(*yellow)
        if wp == 1:
            return discord.Color.from_rgb(*green)

        blue_scale = 0
        if wp < 0.5:
            wp_adj = wp / 0.5
            red_scale = 255
            green_scale = round(255 * wp_adj)
            return discord.Color.from_rgb(red_scale, green_scale, blue_scale)
        else:
            # sub_wp = ((wp-50)/50)*100
            wp_adj = (wp - 0.5) / 0.5
            green_scale = 255
            red_scale = 255 - round(255 * wp_adj)
            return discord.Color.from_rgb(red_scale, green_scale, blue_scale)

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

    async def _guild_team_selection(self):
        return await self.config.guild(self.queue.guild).DefaultTeamSelection()
