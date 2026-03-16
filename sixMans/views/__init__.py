import logging
from typing import TYPE_CHECKING, Callable

import discord

if TYPE_CHECKING:
    from sixMans.game import Game

log = logging.getLogger("red.sixMans.views")


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


class GameOnlyView(discord.ui.View):
    """View class designed to only interact with the game players"""

    def __init__(self, game: "Game", timeout: float = 60.0):
        super().__init__()
        self.timeout = timeout
        self.game = game
        self.msg: discord.Message

    async def on_timeout(self):
        """Display time out message if we have reference to original"""
        if self.msg:
            embed = discord.Embed(
                title="Cancel Game",
                description="Game cancel vote has timed out. Please try again.",
                colour=discord.Colour.yellow(),
            )

            await self.msg.edit(embed=embed, view=None)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        """Check if the interaction user is the author. Allow or deny callbacks"""
        if not isinstance(interaction.user, discord.Member):
            return False

        if interaction.user in self.game.players:
            return True
        return False


class ConfirmButton(discord.ui.Button):
    def __init__(self, callback: Callable | None = None):
        super().__init__()
        self.label = "Confirm"
        self.custom_id = "confirmed"
        self.style = discord.ButtonStyle.green
        if callback:
            self.callback = callback  # type: ignore


class DeclineButton(discord.ui.Button):
    def __init__(self, callback: Callable | None = None):
        super().__init__()
        self.label = "Decline"
        self.custom_id = "declined"
        self.style = discord.ButtonStyle.red
        if callback:
            self.callback = callback  # type: ignore
