import logging
import random
import struct
from pprint import pformat
from typing import TYPE_CHECKING, Callable

import discord

from sixMans.enums import GameMode, Winner

log = logging.getLogger("red.RSC6Mans.sixMans.views")


if TYPE_CHECKING:
    from sixMans.game import Game


def get_emoji(value):
    try:
        if isinstance(value, int):
            return struct.pack("<I", value).decode("utf-32le")
        if isinstance(value, str):
            return struct.pack("<I", int(value, base=16)).decode(
                "utf-32le"
            )  # i == react_hex
    except (ValueError, TypeError):
        return None


class AuthorOnlyView(discord.ui.View):
    """View class designed to only interact with the interaction author"""

    def __init__(self, author: discord.Member, timeout: float = 10.0):
        super().__init__()
        self.timeout = timeout
        self.author = author
        self.msg: discord.Message

    async def on_timeout(self):
        """Display time out message if we have reference to original"""
        if self.msg:
            embed = discord.Embed(
                title="Time out",
                description=f"{self.author.mention} Sorry, you didn't respond quick enough. Please try again.",
                colour=discord.Colour.orange(),
            )

            await self.msg.edit(embed=embed, view=None)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        """Check if the interaction user is the author. Allow or deny callbacks"""
        if interaction.user != self.author:
            return False
        return True


class GameModeVote(discord.ui.View):
    def __init__(self, game: "Game", helper: discord.Role | None = None):
        super().__init__(timeout=None)
        self.channel: discord.TextChannel = game.textChannel
        self.game: "Game" = game
        self.helper: discord.Role | None = helper
        self.options: list[str] = GameMode.to_options()
        self.picked: list[discord.Member] = []
        self.result: GameMode | None = None
        self.votes: dict = GameMode.to_dict()
        self.size = len(game.players)
        log.debug(f"Starting game mode vote: {self.channel}")

    async def start(self):
        """Initiate voting for game mode."""
        self.embed = discord.Embed(
            title="Game Mode Vote",
            description="Please vote for your preferred game mode!",
            color=discord.Color.blue(),
        )

        self.embed.add_field(
            name="Game Mode", value="\n".join(self.options), inline=True
        )
        self.embed.add_field(
            name="Votes",
            value="\n".join([str(v) for v in self.votes.values()]),
            inline=True,
        )

        # Add 6 Mans helper role if available.
        log.debug(
            f"6 Mans Helper: {type(self.game.helper_role)} {self.game.helper_role}"
        )
        if self.game.helper_role:
            self.embed.set_footer(
                text=(
                    f"If you need help or have questions please contact someone with the {self.game.helper_role.name} role. "
                    "For suggestions or improvements, reach out to the RSC Development Committee."
                )
            )
        else:
            self.embed.set_footer(
                text=(
                    "If you encounter any issues with the RSC 6 Mans bot or have suggestions. "
                    "Please contact the RSC Development Committee."
                )
            )

        # Create Buttons
        for mode in self.votes.keys():
            log.debug(f"Adding game mode button: {mode}")
            button: discord.ui.Button = discord.ui.Button(
                label=mode.value,
                custom_id=mode.value,
                style=discord.ButtonStyle.primary,
            )
            button.callback = self.process_vote
            self.add_item(button)
        self.msg = await self.channel.send(embed=self.embed, view=self)

    async def process_vote(self, interaction: discord.Interaction):
        """Process a game mode vote from button press"""
        log.debug(f"Interaction Data Type: {type(interaction.data)}")
        mode = GameMode(interaction.data["custom_id"])
        log.debug(f"{interaction.user} vote: {mode}")
        # Check if user has already voted.
        # if interaction.user in self.picked:
        #     log.debug(f"{interaction.user} has already voted.")
        #     await interaction.response.send_message(
        #         content="You've already voted.",
        #         ephemeral=True,
        #     )
        #     return
        self.picked.append(interaction.user)

        self.votes[mode] += 1
        log.debug(self.votes)

        # Remove and re-add Votes field. Issues with updating in place.
        self.embed.remove_field(1)
        self.embed.add_field(
            name="Votes",
            value="\n".join([str(v) for v in self.votes.values()]),
            inline=True,
        )

        if self.vote_finished:
            log.debug("Game mode vote Finished.")
            self.stop()
            await self.msg.edit(embed=self.embed, view=None)

        # Defer interaction and update embed
        await interaction.response.defer()
        await self.msg.edit(embed=self.embed)

    # async def on_timeout():
    #     """ NotImplemented: Do something if a player went AFK. """
    #     pass

    @property
    def vote_finished(self) -> bool:
        top_mode = max(self.votes, key=self.votes.get)
        if len(self.picked) == self.size or self.votes[top_mode] > (self.size / 2):
            self.result = top_mode
            return True
        else:
            return False


class CaptainsView(discord.ui.View):
    def __init__(self, game: "Game", helper: discord.Role | None = None):
        super().__init__(timeout=None)
        self.channel: discord.TextChannel = game.textChannel
        self.game: "Game" = game
        self.helper: discord.Role | None = helper
        self.pickable: list[discord.Member] = list(self.game.players)
        self.orange: list[discord.Member] = []
        self.blue: list[discord.Member] = []
        self.size = len(game.players)
        self.team_size = len(game.players) / 2
        self.finished = False

        # Assign captains
        self.captains = random.sample(list(self.pickable), 2)
        log.debug(f"Captains: {[f'{p.id}: {p.display_name}' for p in self.captains]}")

        self.blue.append(self.captains[0])
        self.pickable.remove(self.captains[0])
        self.orange.append(self.captains[1])
        self.pickable.remove(self.captains[1])

        # Blue captain picks first
        self.picking = self.captains[0]

    async def on_interaction(self, interaction: discord.Interaction) -> bool:
        if interaction.user != self.picking:
            log.debug(f"{interaction.user} is not picking now...")
            await interaction.response.send_message(
                content=f"Please wait until {self.picking.display_name} has selected a player.",
                ephemeral=True,
            )
            return False
        return True

    async def start(self):
        """Start picks for captains"""
        await self.update_embed()

        # Add player buttons
        for p in self.pickable:
            log.debug(f"Creating button for {p.display_name}")
            button: discord.ui.Button = discord.ui.Button(
                label=p.display_name,
                custom_id=str(p.id),
                style=discord.ButtonStyle.primary,
            )
            button.callback = self.process_pick
            self.add_item(button)

        self.msg = await self.channel.send(embed=self.embed, view=self)

    async def swap_picking(self):
        for captain in self.captains:
            if self.picking != captain:
                self.picking = captain
                log.debug(f"Now picking: {self.picking}")
                break

    async def process_pick(self, interaction: discord.Interaction, **kwargs):
        """Process a game mode vote from button press"""
        log.debug(f"Kwargs: {pformat(kwargs)}")
        log.debug(f"Interaction Data Type: {type(interaction.data)}")

        # Check which captain is picking
        # if interaction.user != self.picking:
        #     await interaction.response.send_message(
        #         content="It's not your turn to pick. Please wait...",
        #         ephemeral=True
        #     )
        #     return

        pick_id = int(interaction.data["custom_id"])
        pick = await self.find_player_by_id(pick_id)
        if not pick:
            await interaction.response.send_message(
                content="Player has already been picked or is not a valid player.",
                ephemeral=True,
            )
            return
        log.debug(f"{interaction.user.display_name} picked {pick.display_name}")

        # Remove player from pickable as soon as possible. Help alleviate a race condition
        self.pickable.remove(pick)

        if self.picking in self.blue:
            if len(self.blue) >= self.team_size:
                log.debug(f"Blue team already has {self.team_size} players on it.")
                await interaction.response.send_message(
                    content=f"You already have the maximum number of players ({self.team_size})",
                    ephemeral=True,
                )
                # Something is wrong, try switching the picking captain
                await self.swap_picking()
                return
            self.blue.append(pick)
        else:
            if len(self.orange) >= self.team_size:
                log.debug(f"Orange team already has {self.team_size} players on it.")
                await interaction.response.send_message(
                    content=f"You already have the maximum number of players ({self.team_size})",
                    ephemeral=True,
                )
                # Something is wrong, try switching the picking captain
                await self.swap_picking()
                return
            self.orange.append(pick)

        self.embed.clear_fields()
        self.embed.add_field(
            name="Blue Team", value="\n".join(p.mention for p in self.blue), inline=True
        )
        self.embed.add_field(
            name="Orange Team",
            value="\n".join(p.mention for p in self.orange),
            inline=True,
        )

        # Disable buttons here
        for b in self.children:
            log.debug(f"Child Type: {type(b)}")
            log.debug(f"Child Data: {b}")

            # Validate child is a button
            if not isinstance(b, discord.ui.Button):
                log.debug("Not a button")
                continue

            if not b.custom_id:
                log.warning(
                    f"Unknown button without an ID in captain selection. Label: {b.label}"
                )
                continue

            log.debug(f"Button ID: {b.custom_id}")
            log.debug(f"Pick: {pick_id}")

            if int(b.custom_id) == pick_id:
                log.debug(f"Disabling {pick} button")
                b.disabled = True

        # Automatically process last pick
        if len(self.pickable) == 1:
            log.debug("Auto processing last pick")
            if len(self.blue) < self.team_size:
                self.blue.append(self.pickable[0])
            elif len(self.orange) < self.team_size:
                self.orange.append(self.pickable[0])
            else:
                log.error(
                    f"[{self.game.id}] Can't assign last pick. Both teams are full... "
                )
                await interaction.response.send_message(
                    "Unable to assign final player to a team. Please open a modmail or contact 6 mans help role."
                )
                return
            self.pickable = []

        # Swap picking captain
        await self.swap_picking()

        # Update embed
        await self.update_embed()

        if len(self.pickable) == 0:
            log.debug("Captains have finished selecting teams.")
            await self.msg.edit(embed=self.embed, view=None)
            self.finished = True
            self.stop()
        else:
            await self.msg.edit(embed=self.embed, view=self)

        await interaction.response.defer(thinking=False, ephemeral=True)

    async def update_embed(self):
        if len(self.pickable) == 0:
            desc = "Teams have been selected!"
        else:
            desc = f"{self.picking.mention}, please select a player."

        self.embed = discord.Embed(
            title="Captains Pick",
            description=desc,
            color=discord.Color.blue(),
        )

        # Team Fields
        self.embed.add_field(
            name="Blue Team", value="\n".join(p.mention for p in self.blue), inline=True
        )
        self.embed.add_field(
            name="Orange Team",
            value="\n".join(p.mention for p in self.orange),
            inline=True,
        )

        # Add help information
        if self.game.helper_role:
            self.embed.set_footer(
                text=(
                    f"If you need help or have questions please contact someone with the {self.game.helper_role.name} role. "
                    "For suggestions or improvements, reach out to the RSC Development Committee."
                )
            )
        else:
            self.embed.set_footer(
                text=(
                    "If you encounter any issues with the RSC 6 Mans bot or have suggestions. "
                    "Please contact the RSC Development Committee."
                )
            )

    async def find_player_by_id(self, id: int) -> discord.Member | None:
        for p in self.pickable:
            if p.id == id:
                return p
        return None


class ScoreReportView(discord.ui.View):
    """Discord view for reporting a game score"""

    def __init__(self, game: "Game"):
        super().__init__(timeout=120.0)
        self.captains = game.captains
        self.game = game
        self.channel = game.textChannel
        self.answers: dict[discord.Member, Winner] = {}
        self.result = Winner.PENDING
        self.cancelled = False

        for c in self.captains:
            self.answers[c] = Winner.PENDING

    async def prompt(self):
        await self.update_embed()
        self.msg = await self.channel.send(embed=self.embed, view=self)

    async def update_embed(self):
        selections = []
        for k, v in self.answers.items():
            selections.append(f"{k.mention} - **{v.value}**")
        selection_fmt = "\n".join(selections)
        desc = f"Captains, please verify the winner team.\n\n{selection_fmt}"

        self.embed = discord.Embed(
            title="Score Report", description=desc, color=discord.Color.blue()
        )
        self.embed.set_footer(text="You have 2 minutes to confirm the score.")

    async def on_timeout(self):
        """Display time out message if we have reference to original"""
        if self.msg:
            embed = discord.Embed(
                title="Score Report",
                description="Score report timed out. Please try again.",
                colour=discord.Colour.yellow(),
            )

            await self.msg.edit(embed=embed, view=None)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        """Check if the interaction user is a game captain"""
        if not isinstance(interaction.user, discord.Member):
            return False
        if interaction.user not in self.captains:
            return False
        return True

    @discord.ui.button(label="Blue", style=discord.ButtonStyle.blurple)
    async def report_blue(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        if not isinstance(interaction.user, discord.Member):
            return

        if await self.already_answered(interaction.user):
            await interaction.response.send_message(
                "You have already selected a winner. Please cancel the report if you made a mistake.",
                ephemeral=True,
            )
            return

        # Update Embed
        self.answers[interaction.user] = Winner.BLUE
        await self.update_embed()
        await self.msg.edit(embed=self.embed, view=self)

        if not await self.both_captains_reported():
            await interaction.response.defer(thinking=False, ephemeral=True)
            return

        if not await self.unanimous_vote():
            embed = discord.Embed(
                title="Score Report",
                description="The captains did not select a winner unanimously. Please try again...",
                color=discord.Color.red(),
            )
            await self.msg.edit(embed=embed, view=None)

        # Finish and display winner
        await self.display_winner()

    @discord.ui.button(label="Orange", style=discord.ButtonStyle.green)
    async def report_orange(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        if not isinstance(interaction.user, discord.Member):
            return

        if await self.already_answered(interaction.user):
            await interaction.response.send_message(
                "You have already selected a winner. Please cancel the report if you made a mistake.",
                ephemeral=True,
            )
            return

        # Update Embed
        self.answers[interaction.user] = Winner.ORANGE
        await self.update_embed()
        await self.msg.edit(embed=self.embed, view=self)

        if not await self.both_captains_reported():
            await interaction.response.defer(thinking=False, ephemeral=True)
            return

        if not await self.unanimous_vote():
            embed = discord.Embed(
                title="Score Report",
                description="The captains did not select a winner unanimously. Please try again...",
                color=discord.Color.red(),
            )
            await self.msg.edit(embed=embed, view=None)

        # Finish and display winner
        await self.display_winner()

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.red)
    async def cancel_report(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        if not isinstance(interaction.user, discord.Member):
            return

        self.cancelled = True

        embed = discord.Embed(
            title="Score Report Cancelled",
            description=f"{interaction.user.mention} has cancelled score reporting.",
            color=discord.Color.red(),
        )
        await self.msg.edit(embed=embed, view=None)
        self.stop()

    async def unanimous_vote(self) -> bool:
        # Fail if a vote has not been cast
        votes = list(self.answers.values())
        if Winner.PENDING in votes:
            return False

        # Number of occurances should match length of value array
        if votes.count(votes[0]) == len(self.answers):
            return True

        return False

    async def already_answered(self, member: discord.Member) -> bool:
        return all(v != Winner.PENDING for v in self.answers.values())

    async def both_captains_reported(self) -> bool:
        return all(v != Winner.PENDING for v in self.answers.values())

    async def display_winner(self):
        self.winner = list(self.answers.values())[0]
        embed = discord.Embed(
            title="Game Finished",
            description=f"**{self.winner}** has been recorded as the winner of this game. Thanks for playing!",
            color=discord.Color.green(),
        )

        embed.set_footer(
            text="This channel and the team voice channels will be deleted in 30 seconds."
        )
        await self.msg.edit(embed=embed, view=None)
        self.stop()


class ForceResultView(AuthorOnlyView):
    """Discord view for force reporting a game score"""

    def __init__(self, author: discord.Member, game: "Game", timeout=30.0):
        super().__init__(author=author, timeout=timeout)
        self.game = game
        self.channel = game.textChannel
        self.result = Winner.PENDING
        self.cancelled = False

    async def prompt(self):
        embed = discord.Embed(
            title="Force Report",
            description="Please select the team that won the game.",
            color=discord.Color.orange(),
        )
        self.msg = await self.channel.send(embed=embed, view=self)

    @discord.ui.button(label="Blue", style=discord.ButtonStyle.gray, emoji=chr(0x1F535))
    async def report_blue(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        if not isinstance(interaction.user, discord.Member):
            return

        self.result = Winner.BLUE

        # Finish and display winner
        await self.display_winner()

    @discord.ui.button(
        label="Orange", style=discord.ButtonStyle.gray, emoji=chr(0x1F7E0)
    )
    async def report_orange(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        if not isinstance(interaction.user, discord.Member):
            return

        self.result = Winner.ORANGE

        # Finish and display winner
        await self.display_winner()

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.red)
    async def cancel_report(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        if not isinstance(interaction.user, discord.Member):
            return

        self.cancelled = True

        embed = discord.Embed(
            title="Score Report Cancelled",
            description=f"{interaction.user.mention} has cancelled score reporting.",
            color=discord.Color.red(),
        )
        await self.msg.edit(embed=embed, view=None)
        self.stop()

    async def display_winner(self):
        embed = discord.Embed(
            title="Force Score Report",
            description=f"**{self.result.upper()}** has been selected as the winner.",
            color=discord.Color.green(),
        )
        embed.set_footer(
            text="This channel and the team voice channels will be deleted in 30 seconds."
        )
        await self.msg.edit(embed=embed, view=None)
        self.stop()


class ForceCancelView(AuthorOnlyView):
    """Discord view for force cancelling a game"""

    def __init__(self, author: discord.Member, game: "Game", timeout=30.0):
        super().__init__(author=author, timeout=timeout)
        self.game = game
        self.channel = game.textChannel
        self.result = False

    async def prompt(self):
        embed = discord.Embed(
            title="Force Cancel Game",
            description="Are you sure you want to cancel the game?",
            color=discord.Color.orange(),
        )
        self.msg = await self.channel.send(embed=embed, view=self)

    @discord.ui.button(label="Confirm", style=discord.ButtonStyle.success)
    async def confirm(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        if not isinstance(interaction.user, discord.Member):
            return

        self.result = True
        embed = discord.Embed(
            title="Game Cancelled",
            description="The game has been forcibly cancelled by a queue moderator.",
            color=discord.Color.green(),
        )
        embed.set_footer(
            text="This channel and the team voice channels will be deleted in 30 seconds."
        )
        await self.msg.edit(embed=embed, view=None)
        self.stop()

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.red)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not isinstance(interaction.user, discord.Member):
            return

        self.result = False
        embed = discord.Embed(
            title="Action Cancelled",
            description="You have opted to not cancel this game. Please try again if this was a mistake.",
            color=discord.Color.red(),
        )
        await self.msg.edit(embed=embed, view=None)
        self.stop()


class ConfirmButton(discord.ui.Button):
    def __init__(self, callback: Callable | None = None):
        super().__init__()
        self.label = "Confirm"
        self.custom_id = "confirmed"
        self.style = discord.ButtonStyle.green
        if callback:
            self.callback = callback


class DeclineButton(discord.ui.Button):
    def __init__(self, callback: Callable | None = None):
        super().__init__()
        self.label = "Decline"
        self.custom_id = "declined"
        self.style = discord.ButtonStyle.red
        if callback:
            self.callback = callback


class SelfPickingView(discord.ui.View):
    def __init__(self, game: "Game", helper: discord.Role | None = None):
        super().__init__(timeout=None)
        self.channel: discord.TextChannel = game.textChannel
        self.game: "Game" = game
        self.helper: discord.Role | None = helper
        self.players: list[discord.Member] = list(self.game.players)
        self.unplaced: list[discord.Member] = list(self.game.players)
        self.orange: list[discord.Member] = []
        self.blue: list[discord.Member] = []
        self.size = len(game.players)
        self.team_size = len(game.players) / 2
        self.finished = False

    async def on_interaction(self, interaction: discord.Interaction) -> bool:
        if interaction.user not in self.players:
            await interaction.response.send_message(
                content="You are not an active player in this game...",
                ephemeral=True,
            )
            return False
        return True

    async def prompt(self):
        """Start self picking"""
        await self.update_embed()
        self.msg = await self.channel.send(embed=self.embed, view=self)

    async def update_embed(self):
        self.embed = discord.Embed(
            title="{} Game | Team Selection".format(
                self.channel.name.replace("-", " ").title()[4:]
            ),
            description="Select :blue_circle: or :orange_circle: team with the buttons below.",
            color=discord.Color.blue(),
        )
        if self.game.queue.guild.icon:
            self.embed.set_thumbnail(url=self.game.queue.guild.icon.url)

        # List teams as they stand
        no_players_str = "[No Players]"
        blue_players = (
            "\n".join(p.mention for p in self.blue) if self.blue else no_players_str
        )
        orange_players = (
            "\n".join(p.mention for p in self.orange) if self.orange else no_players_str
        )
        unplaced_players = (
            ", ".join(p.mention for p in self.players)
            if self.players
            else no_players_str
        )

        ts_emoji = get_emoji(0x1F530)

        self.embed.add_field(
            name="Team Selection",
            value=f"{ts_emoji} Self Picking Teams",
            inline=False,
        )
        self.embed.add_field(name="Blue Team", value=blue_players, inline=True)
        self.embed.add_field(name="Orange Team", value=orange_players, inline=True)
        self.embed.add_field(
            name="Unplaced Players", value=unplaced_players, inline=False
        )

        # Add help information
        if self.game.helper_role:
            self.embed.set_footer(
                text=(
                    "If you need help or have questions please contact "
                    f"someone with the {self.game.helper_role.mention} role. "
                    "For suggestions or improvements, reach out to the RSC Development Committee."
                )
            )
        else:
            self.embed.set_footer(
                text=(
                    "If you encounter any issues with the RSC 6 Mans bot or have suggestions. "
                    "Please contact the RSC Development Committee."
                )
            )

    async def player_on_team(self, member: discord.Member) -> bool:
        if member in self.blue:
            return True
        if member in self.orange:
            return True
        return False

    @discord.ui.button(
        label="Blue", style=discord.ButtonStyle.blurple, emoji=chr(0x1F535)
    )
    async def pick_blue(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        if not isinstance(interaction.user, discord.Member):
            return

        if await self.player_on_team(interaction.user):
            await interaction.response.send_message(
                "You are already on a team...", ephemeral=True
            )
            return

        if len(self.blue) >= self.team_size:
            await interaction.response.send_message(
                "Blue team is already full.", ephemeral=True
            )
            return

        self.blue.append(interaction.user)
        self.unplaced.remove(interaction.user)
        await self.update_embed()

        if len(self.unplaced) == 0:
            await self.msg.edit(embed=self.embed, view=None)
            self.stop()
        else:
            await self.msg.edit(embed=self.embed, view=self)

        await interaction.response.defer(thinking=False, ephemeral=True)

    @discord.ui.button(
        label="Orange", style=discord.ButtonStyle.gray, emoji=chr(0x1F7E0)
    )
    async def pick_orange(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        if not isinstance(interaction.user, discord.Member):
            return

        if await self.player_on_team(interaction.user):
            await interaction.response.send_message(
                "You are already on a team...", ephemeral=True
            )
            return

        if len(self.orange) >= self.team_size:
            await interaction.response.send_message(
                "Blue team is already full.", ephemeral=True
            )
            return

        self.orange.append(interaction.user)
        self.unplaced.remove(interaction.user)
        await self.update_embed()

        if len(self.unplaced) == 0:
            await self.msg.edit(embed=self.embed, view=None)
            self.stop()
        else:
            await self.msg.edit(embed=self.embed, view=self)

        await interaction.response.defer(thinking=False, ephemeral=True)
