import asyncio
import logging
from collections.abc import Callable
from typing import TYPE_CHECKING

import discord

if TYPE_CHECKING:
    from sixMans.game import Game

log = logging.getLogger("red.sixMans.views")


async def safe_edit(msg: discord.Message | None, **kwargs) -> None:
    """Edit a message, tolerating a deleted message or channel.

    Game channels are deleted when a game is cancelled or finished, so a view
    that is still alive can end up editing a message that no longer exists.
    discord.py dispatches `View.on_timeout()` in a bare task, meaning anything
    raised there surfaces as "Task exception was never retrieved" instead of
    being handled. `discord.NotFound` and `discord.Forbidden` both subclass
    `discord.HTTPException`, so one clause covers all of them.
    """
    if msg is None:
        return
    try:
        await msg.edit(**kwargs)
    except discord.HTTPException as exc:
        log.warning(f"Unable to edit message {msg.id}: {exc}")


class SerialEditView(discord.ui.View):
    """A view whose message several people update at once.

    discord.py runs each button press in its own task, so presses overlap and their edits can
    reach Discord out of order. An older tally could land after the final result and put back
    buttons that no longer work. `update_message()` sends edits one at a time, in the order they
    were requested, and drops a tally once the view has finished.

    Callbacks acknowledge the interaction before calling it. Waiting on the lock and the edit can
    otherwise take a press past Discord's 3 second limit, which shows "This interaction failed".
    """

    def __init__(self, timeout: float | None = 180.0):
        super().__init__(timeout=timeout)
        self.msg: discord.Message | None = None
        self._edit_lock = asyncio.Lock()

    async def update_message(self, *, final: bool = False, **kwargs) -> None:
        """Edit the view's message. A tally (not `final`) is skipped once the view has finished."""
        async with self._edit_lock:
            if self.is_finished() and not final:
                return
            await safe_edit(self.msg, **kwargs)


class AuthorOnlyView(discord.ui.View):
    """View class designed to only interact with the interaction author"""

    def __init__(self, author: discord.Member, timeout: float = 10.0):
        super().__init__()
        self.timeout = timeout
        self.author = author
        self.msg: discord.Message | None = None

    async def on_timeout(self):
        """Display time out message if we have reference to original"""
        embed = discord.Embed(
            title="Time out",
            description=f"{self.author.mention} Sorry, you didn't respond quick enough. Please try again.",
            colour=discord.Colour.orange(),
        )

        await safe_edit(self.msg, embed=embed, view=None)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        """Check if the interaction user is the author. Allow or deny callbacks"""
        if interaction.user != self.author:
            await interaction.response.send_message(content=f"Only {self.author.display_name} can use these buttons.", ephemeral=True)
            return False
        return True


class GameOnlyView(SerialEditView):
    """View class designed to only interact with the game players"""

    def __init__(self, game: "Game", timeout: float = 60.0):
        super().__init__(timeout=timeout)
        self.game = game

    async def on_timeout(self):
        """Display time out message if we have reference to original"""
        embed = discord.Embed(
            title="Cancel Game",
            description="Game cancel vote has timed out. Please try again.",
            colour=discord.Colour.yellow(),
        )

        await self.update_message(final=True, embed=embed, view=None)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        """Check if the interaction user is the author. Allow or deny callbacks"""
        if not isinstance(interaction.user, discord.Member):
            return False

        if interaction.user in self.game.players:
            return True
        await interaction.response.send_message(content="You are not an active player in this game...", ephemeral=True)
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
