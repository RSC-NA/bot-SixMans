
import datetime

from sys import exc_info, maxsize
from typing import Dict, List

import discord
from discord.ext.commands import Context
from redbot.core import commands

from sixMans.sixMansSplit.functions import *
from sixMansSplit.sixMansParent import SixMansParent

class LeaderboardCommands(SixMansParent):
    # region leaderboard commands

    @commands.guild_only()
    @commands.group(aliases=["qlb"])
    async def queueLeaderBoard(self, ctx: Context):
        """Get the top ten players in points for the specific queue. If no queue name is given the list will be the top ten players across all queues.
        If you're not in the top ten your name and rank will be shown at the bottom of the list.
        """

    @commands.guild_only()
    @queueLeaderBoard.command(aliases=["all-time", "alltime"])
    async def overall(self, ctx: Context, *, queue_name: str = None):
        """All-time leader board"""
        players = None
        queue = (
            await self._get_queue_by_name(ctx.guild, queue_name) if queue_name else None
        )
        queue_name = queue.name if queue else ctx.guild.name

        if queue:
            players = queue.players
            games_played = queue.gamesPlayed
        else:
            players = await self._players(ctx.guild)
            games_played = await self._games_played(ctx.guild)

        if games_played == 0:
            await ctx.send(f":x: No games have been played in {queue_name}")
            return

        if not players:
            await ctx.send(f":x: Queue leaderboard not available for {queue_name}")
            return

        sorted_players = self._sort_player_dict(players)
        await ctx.send(
            embed=await self.embed_leaderboard(
                ctx, sorted_players, queue_name, games_played, "All-time"
            )
        )

    @commands.guild_only()
    @queueLeaderBoard.command(aliases=["daily"])
    async def day(self, ctx: Context, *, queue_name: str = None):
        """Daily leader board. All games from the last 24 hours will count"""
        scores = await self._scores(ctx.guild)

        queue = (
            await self._get_queue_by_name(ctx.guild, queue_name) if queue_name else None
        )
        queue_id = queue.id if queue else None
        queue_name = queue.name if queue else ctx.guild.name
        day_ago = datetime.datetime.now() - datetime.timedelta(days=1)
        players, games_played = self._filter_scores(
            ctx.guild, scores, day_ago, queue_id
        )

        if games_played == 0:
            await ctx.send(f":x: No games have been played in {queue_name}")
            return

        if not players:
            await ctx.send(f":x: Queue leaderboard not available for {queue_name}")
            return

        sorted_players = self._sort_player_dict(players)
        await ctx.send(
            embed=await self.embed_leaderboard(
                ctx, sorted_players, queue_name, games_played, "Daily"
            )
        )

    @commands.guild_only()
    @queueLeaderBoard.command(aliases=["weekly", "wk"])
    async def week(self, ctx: Context, *, queue_name: str = None):
        """Weekly leader board. All games from the last week will count"""
        scores = await self._scores(ctx.guild)

        queue = (
            await self._get_queue_by_name(ctx.guild, queue_name) if queue_name else None
        )
        queue_id = queue.id if queue else None
        week_ago = datetime.datetime.now() - datetime.timedelta(weeks=1)
        players, games_played = self._filter_scores(
            ctx.guild, scores, week_ago, queue_id
        )

        if games_played == 0:
            await ctx.send(f":x: No games have been played in {queue_name}")
            return

        if not players:
            await ctx.send(f":x: Queue leaderboard not available for {queue_name}")
            return

        queue_name = queue.name if queue else ctx.guild.name
        sorted_players = self._sort_player_dict(players)
        await ctx.send(
            embed=await self.embed_leaderboard(
                ctx, sorted_players, queue_name, games_played, "Weekly"
            )
        )

    @commands.guild_only()
    @queueLeaderBoard.command(aliases=["monthly", "mnth"])
    async def month(self, ctx: Context, *, queue_name: str = None):
        """Monthly leader board. All games from the last 30 days will count"""
        scores = await self._scores(ctx.guild)

        queue = (
            await self._get_queue_by_name(ctx.guild, queue_name) if queue_name else None
        )
        queue_id = queue.id if queue else None
        month_ago = datetime.datetime.now() - datetime.timedelta(days=30)
        players, games_played = self._filter_scores(
            ctx.guild, scores, month_ago, queue_id
        )

        if games_played == 0:
            await ctx.send(f":x: No games have been played in {queue_name}")
            return

        if not players:
            await ctx.send(f":x: Queue leaderboard not available for {queue_name}")
            return

        queue_name = queue.name if queue else ctx.guild.name
        sorted_players = self._sort_player_dict(players)
        await ctx.send(
            embed=await self.embed_leaderboard(
                ctx, sorted_players, queue_name, games_played, "Monthly"
            )
        )

    @commands.guild_only()
    @queueLeaderBoard.command(aliases=["yearly", "yr"])
    async def year(self, ctx: Context, *, queue_name: str = None):
        """Yearly leader board. All games from the last 365 days will count"""
        scores = await self._scores(ctx.guild)

        queue = (
            await self._get_queue_by_name(ctx.guild, queue_name) if queue_name else None
        )
        queue_id = queue.id if queue else None
        year_ago = datetime.datetime.now() - datetime.timedelta(days=365)
        players, games_played = self._filter_scores(
            ctx.guild, scores, year_ago, queue_id
        )

        if games_played == 0:
            await ctx.send(f":x: No games have been played in {queue_name}")
            return

        if not players:
            await ctx.send(f":x: Queue leaderboard not available for {queue_name}")
            return

        queue_name = queue.name if queue else ctx.guild.name
        sorted_players = self._sort_player_dict(players)
        await ctx.send(
            embed=await self.embed_leaderboard(
                ctx, sorted_players, queue_name, games_played, "Yearly"
            )
        )

    # endregion