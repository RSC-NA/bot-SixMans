import logging
from typing import TYPE_CHECKING

import discord

from sixMans.enums import Winner
from sixMans.views import AuthorOnlyView

if TYPE_CHECKING:
    from sixMans.game import Game

log = logging.getLogger("red.sixMans.views.score")


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
        captains_mention = " ".join(c.mention for c in self.captains)
        if not self.channel:
            log.error("No text channel found for game {}. Cannot prompt score report.".format(self.game.id))
            return
        self.msg = await self.channel.send(content=captains_mention, embed=self.embed, view=self, allowed_mentions=discord.AllowedMentions(users=True))

    async def update_embed(self):
        selections = []
        for k, v in self.answers.items():
            selections.append(f"{k.mention} - **{v.value}**")
        selection_fmt = "\n".join(selections)
        desc = f"Captains, please verify the winner team.\n\n{selection_fmt}"

        self.embed = discord.Embed(title="Score Report", description=desc, color=discord.Color.blue())
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
    async def report_blue(self, interaction: discord.Interaction, button: discord.ui.Button):
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
            self.stop()
            return

        # Finish and display winner
        await self.display_winner()

    @discord.ui.button(label="Orange", style=discord.ButtonStyle.green)
    async def report_orange(self, interaction: discord.Interaction, button: discord.ui.Button):
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
            self.stop()
            return

        # Finish and display winner
        await self.display_winner()

    async def captains_report(self, member: discord.Member, winner: Winner):
        if member not in self.captains:
            return

        if await self.already_answered(member):
            return

        # Update Embed
        self.answers[member] = winner
        await self.update_embed()
        await self.msg.edit(embed=self.embed, view=self)

        if not await self.both_captains_reported():
            return

        if not await self.unanimous_vote():
            embed = discord.Embed(
                title="Score Report",
                description="The captains did not select a winner unanimously. Please try again...",
                color=discord.Color.red(),
            )
            await self.msg.edit(embed=embed, view=None)
            self.stop()
            return

        # Finish and display winner
        await self.display_winner()

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.red)
    async def cancel_report(self, interaction: discord.Interaction, button: discord.ui.Button):
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

        # Number of occurrences should match length of value array
        if votes.count(votes[0]) == len(self.answers):
            return True

        return False

    async def already_answered(self, member: discord.Member) -> bool:
        return self.answers.get(member, Winner.PENDING) != Winner.PENDING

    async def both_captains_reported(self) -> bool:
        return all(v != Winner.PENDING for v in self.answers.values())

    async def display_winner(self):
        self.result = list(self.answers.values())[0]
        embed = discord.Embed(
            title="Game Finished",
            description=f"**{self.result}** has been recorded as the winner of this game. Thanks for playing!",
            color=discord.Color.green(),
        )

        embed.set_footer(text="This channel and the team voice channels will be deleted in 30 seconds.")
        await self.msg.edit(embed=embed, view=None)
        self.stop()


class ForceResultView(AuthorOnlyView):
    """Discord view for force reporting a game score"""

    def __init__(self, author: discord.Member, game: "Game", timeout=60.0):
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
    async def report_blue(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not isinstance(interaction.user, discord.Member):
            return

        self.result = Winner.BLUE

        # Finish and display winner
        await self.display_winner()

    @discord.ui.button(label="Orange", style=discord.ButtonStyle.gray, emoji=chr(0x1F7E0))
    async def report_orange(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not isinstance(interaction.user, discord.Member):
            return

        self.result = Winner.ORANGE

        # Finish and display winner
        await self.display_winner()

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.red)
    async def cancel_report(self, interaction: discord.Interaction, button: discord.ui.Button):
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
            colour=discord.Color.light_grey(),
        )

        match self.result:
            case Winner.BLUE:
                embed.colour = discord.Color.blue()
            case Winner.ORANGE:
                embed.colour = discord.Color.orange()

        embed.set_footer(text="This channel and the team voice channels will be deleted in 30 seconds.")
        await self.msg.edit(embed=embed, view=None)
        self.stop()
