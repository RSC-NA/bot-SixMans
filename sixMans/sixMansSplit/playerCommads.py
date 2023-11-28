import asyncio

from sys import exc_info, maxsize
from typing import Dict, List

import discord
from discord.ext.commands import Context
from redbot.core import commands
from redbot.core.utils.menus import start_adding_reactions
from redbot.core.utils.predicates import ReactionPredicate

from sixMans.sixMansSplit.functions import *
from sixMansSplit.sixMansParent import SixMansParent

from sixMans.queue import SixMansQueue
from sixMans.strings import Strings
from sixMans.views import GameMode, GameState


class PlayerCommands(SixMansParent):
    # region player commands
    @commands.guild_only()
    @commands.command(aliases=["smMove", "moveme"])
    async def moveMe(self, ctx: Context):
        if ctx.message.channel.category != await self._category(ctx.guild):
            return False

        game = self._get_game_by_text_channel(ctx.channel)
        player = ctx.message.author
        if game:
            try:
                if player in game.blue:
                    await player.move_to(game.voiceChannels[0])
                if player in game.orange:
                    await player.move_to(game.voiceChannels[1])
                await ctx.message.add_reaction(
                    Strings.WHITE_CHECK_REACT
                )  # white_check_mark
            except:
                await ctx.message.add_reaction(
                    Strings.WHITE_X_REACT
                )  # negative_squared_cross_mark
                if not player.voice:
                    await ctx.send(
                        f"{player.mention}, you must be connected to a voice channel to be moved to your Six Man's team channel."
                    )
        else:
            await ctx.message.add_reaction(
                Strings.WHITE_X_REACT
            )  # negative_squared_cross_mark
            await ctx.send(
                f"{player.mention}, you must run this command from within your queue lobby channel."
            )
            # TODO: determine a workaround from filtering through all active games

    @commands.guild_only()
    @commands.command(aliases=["li", "gameInfo", "gi"])
    async def lobbyInfo(self, ctx: Context):
        """Gets lobby info for the series that you are involved in"""
        # TODO: fails after cog is reloaded
        if ctx.message.channel.category != await self._category(ctx.guild):
            return False

        game = self._get_game_by_text_channel(ctx.channel)
        if game:
            await game.post_lobby_info()

    @commands.guild_only()
    @commands.command(aliases=["q"])
    async def queue(self, ctx: Context):
        """Add yourself to the queue"""
        six_mans_queue: SixMansQueue = self._get_queue_by_text_channel(ctx.channel)
        player = ctx.message.author

        if not self.queues_enabled[ctx.guild]:
            return await ctx.send(":x: Queueing is currently disabled.")

        if player in six_mans_queue.queue.queue:
            await ctx.send(f":x: You are already in the {six_mans_queue.name} queue")
            return
        for game in self.games[ctx.guild]:
            if player in game:
                await ctx.send(":x: You are already in a game")
                return

        await self._add_to_queue(player, six_mans_queue)
        if six_mans_queue._queue_full():
            await self._pop_queue(ctx, six_mans_queue)

    @commands.guild_only()
    @commands.command(aliases=["dq", "lq", "leaveq", "leaveQ", "unqueue", "unq", "uq"])
    async def dequeue(self, ctx: Context):
        """Remove yourself from the queue"""
        six_mans_queue = self._get_queue_by_text_channel(ctx.channel)
        player = ctx.message.author

        if player in six_mans_queue.queue:
            await self._remove_from_queue(player, six_mans_queue)
        else:
            await ctx.send(f":x: You're not in the {six_mans_queue.name} queue")

    @commands.guild_only()
    @commands.command(aliases=["cg"])
    async def cancelGame(self, ctx: Context):
        """Cancel the current game. Can only be used in a game channel.
        The game will end with no points given to any of the players. The players with then be allowed to queue again.
        """
        game = self._get_game_by_text_channel(ctx.channel)
        if game is None:
            await ctx.send(
                f":x: This command can only be used in a {self.queueMaxSize[ctx.guild]} Mans game channel."
            )
            return

        opposing_captain = self._get_opposing_captain(ctx.author, game)
        if opposing_captain is None:
            await ctx.send(
                ":x: Only players on one of the two teams can cancel the game."
            )
            return

        msg = await ctx.send(
            f"{opposing_captain.mention} Please verify that both teams want to cancel the game. You have {VERIFY_TIMEOUT} seconds to verify"
        )
        start_adding_reactions(msg, ReactionPredicate.YES_OR_NO_EMOJIS)

        pred = ReactionPredicate.yes_or_no(msg, opposing_captain)
        try:
            await ctx.bot.wait_for("reaction_add", check=pred, timeout=VERIFY_TIMEOUT)
            if pred.result is True:
                await ctx.send(
                    f"Done. Feel free to queue again in an appropriate channel.\n**This channel will be deleted in {CHANNEL_SLEEP_TIME} seconds**"
                )
                await self._remove_game(ctx.guild, game)
            else:
                await ctx.send(
                    f":x: Cancel not verified. To cancel the game you will need to use the `{ctx.prefix}cg` command again."
                )
        except asyncio.TimeoutError:
            self._swap_opposing_captain(game, opposing_captain)
            await ctx.send(
                f":x: Cancel not verified in time. To cancel the game you will need to use the `{ctx.prefix}cg` command again."
                f"\n**If one of the captains is afk, have someone from that team use the command.**"
            )

    @commands.guild_only()
    @commands.command(aliases=["sr"])
    async def scoreReport(self, ctx: Context, winning_team):
        """Report which team won the series. Can only be used in a game channel.
        Only valid after 10 minutes have passed since the game started. Both teams will need to verify the results.

        `winning_team` must be either `Blue` or `Orange`"""
        game_time = ctx.message.created_at - ctx.channel.created_at
        if game_time.seconds < MINIMUM_GAME_TIME:
            await ctx.send(
                f":x: You can't report a game outcome until at least **10 minutes** have passed since the game was created."
                f"\nCurrent time that's passed = **{game_time.seconds // 60} minute(s)**"
            )
            return

        if winning_team.lower() != "blue" and winning_team.lower() != "orange":
            await ctx.send(
                f":x: {winning_team} is an invalid input for `winning_team`. Must be either `Blue` or `Orange`"
            )
            return

        game, six_mans_queue = await self._get_info(ctx)
        if game is None or six_mans_queue is None:
            return

        if game.scoreReported == True:
            await ctx.send(
                ":x: Someone has already reported the results or is waiting for verification"
            )
            return

        opposing_captain = self._get_opposing_captain(ctx.author, game)
        if opposing_captain is None:
            await ctx.send(
                ":x: Only players on one of the two teams can report the score"
            )
            return

        game.scoreReported = True
        msg = await ctx.send(
            f"{opposing_captain.mention} Please verify that the **{winning_team}** team won the series. You have {VERIFY_TIMEOUT} seconds to verify"
        )
        start_adding_reactions(msg, ReactionPredicate.YES_OR_NO_EMOJIS)

        pred = ReactionPredicate.yes_or_no(msg, opposing_captain)
        try:
            await ctx.bot.wait_for("reaction_add", check=pred, timeout=VERIFY_TIMEOUT)
            if pred.result is True:
                pass
            else:
                game.scoreReported = False
                await ctx.send(
                    f":x: Score report not verified. To report the score you will need to use the `{ctx.prefix}sr` command again."
                )
                return
        except asyncio.TimeoutError:
            game.scoreReported = False
            self._swap_opposing_captain(game, opposing_captain)
            await ctx.send(
                f":x: Score report not verified in time. To report the score you will need to use the `{ctx.prefix}sr` command again."
                f"\n**If one of the captains is afk, have someone from that team use the command.**"
            )
            return

        await game.report_winner(winning_team)
        await ctx.send(
            f"Done. Thanks for playing!\n**This channel and the team voice channels will be deleted in {CHANNEL_SLEEP_TIME} seconds**"
        )
        await self._finish_game(ctx.guild, game, six_mans_queue, winning_team)

    @commands.guild_only()
    @commands.command(aliases=["moreinfo", "mi"])
    async def moreInfo(self, ctx: Context):
        """Provides more in-depth information regarding the Six Mans series"""
        game = self._get_game_by_text_channel(ctx.channel)
        if game is None:
            await ctx.send(
                f":x: This command can only be used in a {self.queueMaxSize[ctx.guild]} Mans game channel."
            )
            return
        await game.post_more_lobby_info()

    # team selection
    @commands.guild_only()
    @commands.command(aliases=["r", "random"])
    async def voteRandom(self, ctx):
        game = self._get_game_by_text_channel(ctx.channel)
        ignore_call = (
            await self._is_react_to_vote(ctx.guild)
            or not game
            or game.teamSelection != GameMode.VOTE
            or game.state != GameState.NEW
        )
        if ignore_call:
            return

    @commands.guild_only()
    @commands.command(aliases=["c", "votecaptains", "vc"])
    async def voteCaptains(self, ctx):
        game = self._get_game_by_text_channel(ctx.channel)
        ignore_call = (
            await self._is_react_to_vote(ctx.guild)
            or not game
            or game.teamSelection != GameMode.VOTE
            or game.state != GameState.NEW
        )
        if ignore_call:
            return

    @commands.guild_only()
    @commands.command(aliases=["b", "balanced", "vb"])
    async def voteBalanced(self, ctx):
        game = self._get_game_by_text_channel(ctx.channel)
        ignore_call = (
            await self._is_react_to_vote(ctx.guild)
            or not game
            or game.teamSelection != GameMode.VOTE
            or game.state != GameState.NEW
        )
        if ignore_call:
            return

    @commands.guild_only()
    @commands.command(aliases=["s", "spt", "selfPickingTeams", "vs"])
    async def voteSelfPickingTeams(self, ctx):
        game = self._get_game_by_text_channel(ctx.channel)
        ignore_call = (
            await self._is_react_to_vote(ctx.guild)
            or not game
            or game.teamSelection != GameMode.VOTE
            or game.state != GameState.NEW
        )
        if ignore_call:
            return

    # endregion player commands
