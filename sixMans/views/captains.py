import logging
import random
from pprint import pformat
from typing import TYPE_CHECKING

import discord

if TYPE_CHECKING:
    from sixMans.game import Game

log = logging.getLogger("red.sixMans.views.captains")


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
            button.callback = self.process_pick  # type: ignore
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
        if not interaction.guild or not isinstance(interaction.user, discord.Member):
            await interaction.response.defer()
            return

        log.debug(f"Kwargs: {pformat(kwargs)}")
        log.debug(f"Interaction Data Type: {type(interaction.data)}")

        # Check which captain is picking
        # if interaction.user != self.picking:
        #     await interaction.response.send_message(
        #         content="It's not your turn to pick. Please wait...",
        #         ephemeral=True
        #     )
        #     return

        pick_id = int(interaction.data["custom_id"])  # type: ignore
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
        self.embed.add_field(name="Blue Team", value="\n".join(p.mention for p in self.blue), inline=True)
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
                log.warning(f"Unknown button without an ID in captain selection. Label: {b.label}")
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
                log.error(f"[{self.game.id}] Can't assign last pick. Both teams are full... ")
                await interaction.response.send_message("Unable to assign final player to a team. Please open a modmail or contact 6 mans help role.")
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
        self.embed.add_field(name="Blue Team", value="\n".join(p.mention for p in self.blue), inline=True)
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
            self.embed.set_footer(text=("If you encounter any issues with the RSC 6 Mans bot or have suggestions. Please contact the RSC Development Committee."))

    async def find_player_by_id(self, id: int) -> discord.Member | None:
        for p in self.pickable:
            if p.id == id:
                return p
        return None
