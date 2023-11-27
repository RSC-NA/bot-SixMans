import discord
import random
from enum import StrEnum
from typing import Callable, Union, NoReturn
import logging

log = logging.getLogger("red.RSC6Mans.sixMans.views")

from typing import TYPE_CHECKING, List, Optional

if TYPE_CHECKING:
    from sixMans.game import Game


class GameState(StrEnum):
    NEW = "New"
    ONGOING = "Ongoing"
    CANCELLED = "Cancelled"
    COMPLETE = "Complete"


class GameMode(StrEnum):
    RANDOM = "Random"
    CAPTAINS = "Captains"
    SELF_PICK = "Self Picking Teams"
    BALANCED = "Balanced"
    VOTE = "Vote"
    DEFAULT = "Default"

    @staticmethod
    def to_options():
        opts = []
        for mode in GameMode:
            if mode == GameMode.VOTE or mode == GameMode.DEFAULT:
                continue
            opts.append(mode.value)
        return opts

    @staticmethod
    def to_dict():
        # Return dictionary used to track votes for each mode
        d = dict()
        for mode in GameMode:
            if mode == GameMode.VOTE or mode == GameMode.DEFAULT:
                continue
            d[mode] = 0
        return d


class GameModeVote(discord.ui.View):
    def __init__(self, game: "Game", helper: Optional[discord.Role] = None):
        super().__init__()
        self.channel: discord.TextChannel = game.textChannel
        self.game: "Game" = game
        self.helper: Optional[discord.Role] = helper
        self.options: List[str] = GameMode.to_options()
        self.picked: List[Union[discord.Member, discord.User]] = []
        self.result: GameMode = None
        self.votes: dict = GameMode.to_dict()
        self.size = len(game.players)
        log.debug(f"Starting game mode vote: {self.channel}")

    async def start(self):
        """Initiate voting for game mode."""
        self.embed = discord.Embed(
            title=f"Game Mode Vote",
            description="Please vote for your preferred game mode!",
            color=discord.Color.blue(),
        )

        self.embed.add_field(
            name="Game Mode", value="\n".join(self.options), inline=True
        )
        self.embed.add_field(
            name="Votes",
            value="\n".join(list([str(v) for v in self.votes.values()])),
            inline=True,
        )

        # Add 6 Mans helper role if available.
        log.debug(
            f"6 Mans Helper: {type(self.game.helper_role)} {self.game.helper_role}"
        )
        if self.game.helper_role:
            self.embed.set_footer(
                text=f"If you need help or have questions please contact someone with the {self.game.helper_role.name} role. For suggestions or improvements, reach out to the RSC Development Committee."
            )
        else:
            self.embed.set_footer(
                text="If you encounter any issues with the RSC 6 Mans bot or have suggestions. Please contact the RSC Development Committee."
            )

        # Create Buttons
        for mode in self.votes.keys():
            log.debug(f"Adding game mode button: {mode}")
            button = discord.ui.Button(
                label=mode.value,
                custom_id=mode.value,
                style=discord.ButtonStyle.primary,
            )
            button.callback = self.process_vote
            self.add_item(button)
        self.msg = await self.channel.send(embed=self.embed, view=self)

    async def process_vote(self, interaction: discord.Interaction):
        """Process a game mode vote from button press"""
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
            value="\n".join(list([str(v) for v in self.votes.values()])),
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
    def __init__(self, game: "Game", helper: Optional[discord.Role] = None):
        super().__init__()
        self.channel: discord.TextChannel = game.textChannel
        self.game: "Game" = game
        self.helper: Optional[discord.Role] = helper
        self.pickable: List[Union[discord.Member, discord.User]] = list(
            self.game.players
        )
        self.orange: List[Union[discord.Member, discord.User]] = []
        self.blue: List[Union[discord.Member, discord.User]] = []
        self.size = len(game.players)
        self.team_size = len(game.players) / 2

        # Assign captains
        self.captains = random.sample(self.pickable, 2)
        log.debug(f"Captains: {self.pickable}")

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
        self.embed = discord.Embed(
            title="Captains Pick",
            description=f"{self.captains[0].mention}, please select a player.",
            color=discord.Color.blue(),
        )

        self.embed.add_field(
            name="Blue Team", value="\n".join(p.mention for p in self.blue), inline=True
        )
        self.embed.add_field(
            name="Orange Team",
            value="\n".join(p.mention for p in self.orange),
            inline=True,
        )

        # Add player buttons
        for p in self.pickable:
            log.debug(f"Creating button for {p.display_name}")
            button = discord.ui.Button(
                label=p.display_name,
                custom_id=str(p.id),
                style=discord.ButtonStyle.primary,
            )
            button.callback = self.process_pick
            self.add_item(button)

        # Add help information
        if self.game.helper_role:
            self.embed.set_footer(
                text=f"If you need help or have questions please contact someone with the {self.game.helper_role.name} role. For suggestions or improvements, reach out to the RSC Development Committee."
            )
        else:
            self.embed.set_footer(
                text="If you encounter any issues with the RSC 6 Mans bot or have suggestions. Please contact the RSC Development Committee."
            )

        self.msg = await self.channel.send(embed=self.embed, view=self)

    async def process_pick(self, interaction: discord.Interaction):
        """Process a game mode vote from button press"""
        pick: discord.Member = await self.find_player_by_id(
            int(interaction.data["custom_id"])
        )
        log.debug(f"{interaction.user.display_name} picked {pick.display_name}")

        if interaction.user in self.blue:
            if len(self.blue) >= self.team_size:
                log.debug(f"Blue team already has {self.team_size} players on it.")
                await interaction.response.send_message(
                    content=f"You already have the maximum number of players ({self.team_size})",
                    ephemeral=True,
                )
                return
            self.blue.append(pick)
            self.pickable.remove(pick)
        else:
            if len(self.orange) >= self.team_size:
                log.debug(f"Orange team already has {self.team_size} players on it.")
                await interaction.response.send_message(
                    content=f"You already have the maximum number of players ({self.team_size})",
                    ephemeral=True,
                )
                return
            self.blue.append(pick)
            self.pickable.remove(pick)

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

        await self.msg.edit(embed=self.embed)

    async def find_player_by_id(self, id: int) -> discord.Member:
        for p in self.pickable:
            if p.id == id:
                return p


class AuthorOnlyView(discord.ui.View):
    """View class designed to only interact with the interaction author"""

    def __init__(
        self, author: Union[discord.Member, discord.User], timeout: float = 10.0
    ):
        super().__init__()
        self.timeout = timeout
        self.author = author

    async def on_timeout(self):
        """Display time out message if we have reference to original"""
        if self.message:
            embed = discord.Embed(
                title="Time out",
                description=f"{self.author.mention} Sorry, you didn't respond quick enough. Please try again.",
                colour=discord.Colour.orange(),
            )

            await self.message.edit(embed=embed, view=None)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        """Check if the interaction user is the author. Allow or deny callbacks"""
        if interaction.user != self.author:
            return False
        return True


class ConfirmButton(discord.ui.Button):
    def __init__(self, callback: Callable = None):
        super().__init__()
        self.label = "Confirm"
        self.custom_id = "confirmed"
        self.style = discord.ButtonStyle.green
        if callback:
            self.callback = callback


class DeclineButton(discord.ui.Button):
    def __init__(self, callback: Callable = None):
        super().__init__()
        self.label = "Decline"
        self.custom_id = "declined"
        self.style = discord.ButtonStyle.red
        if callback:
            self.callback = callback
