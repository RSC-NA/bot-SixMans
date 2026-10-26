import logging
from typing import TYPE_CHECKING

import discord

from sixMans.embeds import GreenEmbed, OrangeEmbed
from sixMans.enums import CancelVote
from sixMans.views import AuthorOnlyView, GameOnlyView, safe_edit

if TYPE_CHECKING:
    from sixMans.game import Game

log = logging.getLogger("red.sixMans.views.captains")


class CancelView(GameOnlyView):
    """Discord view for force cancelling a game"""

    def __init__(self, game: "Game", timeout=60.0):
        super().__init__(game=game, timeout=timeout)
        self.channel = game.textChannel
        self.result = False

        # A majority, so in a 2v2 or 3v3 one team can't settle the vote alone
        self.required_votes = len(self.game.players) // 2 + 1
        log.debug(f"Required votes for cancel: {self.required_votes}")

        # Initialize votes to `None`
        self.votes: dict[discord.Member, CancelVote] = {}
        for p in self.game.players:
            self.votes[p] = CancelVote.WAITING

    async def prompt(self):
        if not self.channel:
            log.error(f"No text channel found for game {self.game.id}. Cannot prompt cancel vote.")
            self.stop()
            return

        embed = await self.create_embed()
        self.msg = await self.channel.send(embed=embed, view=self)

    async def create_embed(self) -> discord.Embed:
        embed = OrangeEmbed(
            title="Cancel Game",
            description=(f"Vote to cancel the current game.\n\nTotal votes required: **{self.required_votes}**"),
        )

        embed.add_field(name="Player", value="\n".join([p.mention for p in self.votes]), inline=True)
        embed.add_field(
            name="Vote",
            value="\n".join([str(v) for v in self.votes.values()]),
            inline=True,
        )
        return embed

    def has_required_votes(self, votetype: CancelVote) -> bool:
        votelist = list(self.votes.values())
        if votelist.count(votetype) >= self.required_votes:
            return True
        return False

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.red)
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.record_vote(interaction, CancelVote.CANCEL)

    @discord.ui.button(label="Play Out", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.record_vote(interaction, CancelVote.PLAY)

    async def record_vote(self, interaction: discord.Interaction, vote: CancelVote):
        if not isinstance(interaction.user, discord.Member):
            return

        if not self.votes.get(interaction.user):
            return await interaction.response.send_message(content="You are not a valid player in this game.", ephemeral=True)

        if self.is_finished():
            return await interaction.response.send_message(content="This vote has already ended.", ephemeral=True)

        self.votes[interaction.user] = vote

        # Settle the vote before the first await, so overlapping presses can't end it twice with
        # different results.
        decided = self.has_required_votes(votetype=vote)
        if decided:
            self.result = vote == CancelVote.CANCEL
            self.stop()

        if vote == CancelVote.CANCEL:
            await interaction.response.send_message(content="You have voted to cancel the game.", ephemeral=True)
        else:
            await interaction.response.send_message(content="You have voted to play the match out.", ephemeral=True)

        if not decided:
            await self.update_message(embed=await self.create_embed(), view=self)
            return

        if self.result:
            embed = GreenEmbed(
                title="Game Cancelled",
                description="The game has been forcibly cancelled by a vote.",
            )
            embed.set_footer(text="This channel and the team voice channels will be deleted in 30 seconds.")
        else:
            embed = GreenEmbed(
                title="Vote Failed",
                description="The vote to cancel this game has failed. Please try again if this was a mistake.",
            )
        await self.update_message(final=True, embed=embed, view=None)


class ForceCancelView(AuthorOnlyView):
    """Discord view for force cancelling a game"""

    def __init__(self, author: discord.Member, game: "Game", timeout=60.0):
        super().__init__(author=author, timeout=timeout)
        self.game = game
        self.channel = game.textChannel
        self.result = False

    async def prompt(self):
        if not self.channel:
            log.error(f"No text channel found for game {self.game.id}. Cannot prompt force cancel.")
            self.stop()
            return

        embed = discord.Embed(
            title="Force Cancel Game",
            description="Are you sure you want to cancel the game?",
            color=discord.Color.orange(),
        )
        self.msg = await self.channel.send(embed=embed, view=self)

    @discord.ui.button(label="Confirm", style=discord.ButtonStyle.success)
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not isinstance(interaction.user, discord.Member):
            return

        self.result = True
        self.stop()
        await interaction.response.defer()
        embed = discord.Embed(
            title="Game Cancelled",
            description="The game has been forcibly cancelled by a queue moderator.",
            color=discord.Color.green(),
        )
        embed.set_footer(text="This channel and the team voice channels will be deleted in 30 seconds.")
        await safe_edit(self.msg, embed=embed, view=None)

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.red)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not isinstance(interaction.user, discord.Member):
            return

        self.result = False
        self.stop()
        await interaction.response.defer()
        embed = discord.Embed(
            title="Action Cancelled",
            description="You have opted to not cancel this game. Please try again if this was a mistake.",
            color=discord.Color.red(),
        )
        await safe_edit(self.msg, embed=embed, view=None)
