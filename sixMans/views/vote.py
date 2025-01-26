import logging
from typing import TYPE_CHECKING

import discord

from sixMans.enums import GameMode

if TYPE_CHECKING:
    from sixMans.game import Game

log = logging.getLogger("red.sixMans.views.vote")


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
        self.embed.set_footer(text=f"Game ID: {self.game.id}")

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
        for mode in self.votes:
            log.debug(f"Adding game mode button: {mode}")
            button: discord.ui.Button = discord.ui.Button(
                label=mode.value,
                custom_id=mode.value,
                style=discord.ButtonStyle.primary,
            )
            button.callback = self.process_vote  # type: ignore
            self.add_item(button)
        self.msg = await self.channel.send(embed=self.embed, view=self)

    async def process_vote(self, interaction: discord.Interaction):
        """Process a game mode vote from button press"""
        if not interaction.guild or not isinstance(interaction.user, discord.Member):
            await interaction.response.defer()
            return

        log.debug(f"Interaction Data Type: {type(interaction.data)}")
        mode = GameMode(interaction.data["custom_id"])  # type: ignore
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
        top_mode = max(self.votes, key=self.votes.get)  # type: ignore
        if len(self.picked) == self.size or self.votes[top_mode] > (self.size / 2):
            self.result = top_mode
            return True
        else:
            return False
