import logging
from typing import TYPE_CHECKING

import discord

from sixMans.utils import get_emoji

if TYPE_CHECKING:
    from sixMans.game import Game

log = logging.getLogger("red.sixMans.views.selfpick")


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
            title="{} Game | Team Selection".format(self.channel.name.replace("-", " ").title()[4:]),
            description="Select :blue_circle: or :orange_circle: team with the buttons below.",
            color=discord.Color.blue(),
        )
        if self.game.queue.guild.icon:
            self.embed.set_thumbnail(url=self.game.queue.guild.icon.url)

        # List teams as they stand
        no_players_str = "[No Players]"
        blue_players = "\n".join(p.mention for p in self.blue) if self.blue else no_players_str
        orange_players = "\n".join(p.mention for p in self.orange) if self.orange else no_players_str
        unplaced_players = ", ".join(p.mention for p in self.players) if self.players else no_players_str

        ts_emoji = get_emoji(0x1F530)

        self.embed.add_field(
            name="Team Selection",
            value=f"{ts_emoji} Self Picking Teams",
            inline=False,
        )
        self.embed.add_field(name="Blue Team", value=blue_players, inline=True)
        self.embed.add_field(name="Orange Team", value=orange_players, inline=True)
        self.embed.add_field(name="Unplaced Players", value=unplaced_players, inline=False)

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
            self.embed.set_footer(text=("If you encounter any issues with the RSC 6 Mans bot or have suggestions. Please contact the RSC Development Committee."))

    async def player_on_team(self, member: discord.Member) -> bool:
        if member in self.blue:
            return True
        if member in self.orange:
            return True
        return False

    @discord.ui.button(label="Blue", style=discord.ButtonStyle.blurple, emoji=chr(0x1F535))
    async def pick_blue(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not isinstance(interaction.user, discord.Member):
            return

        if await self.player_on_team(interaction.user):
            await interaction.response.send_message("You are already on a team...", ephemeral=True)
            return

        if len(self.blue) >= self.team_size:
            await interaction.response.send_message("Blue team is already full.", ephemeral=True)
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

    @discord.ui.button(label="Orange", style=discord.ButtonStyle.gray, emoji=chr(0x1F7E0))
    async def pick_orange(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not isinstance(interaction.user, discord.Member):
            return

        if await self.player_on_team(interaction.user):
            await interaction.response.send_message("You are already on a team...", ephemeral=True)
            return

        if len(self.orange) >= self.team_size:
            await interaction.response.send_message("Orange team is already full.", ephemeral=True)
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
