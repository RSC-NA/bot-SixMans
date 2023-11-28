import datetime

from sys import exc_info, maxsize
from typing import Dict, List

import discord
from discord.ext.commands import Context
from redbot.core import commands

from sixMans.sixMansSplit.functions import *
from sixMansSplit.sixMansParent import SixMansParent

class RankCommands(SixMansParent):
    # region rank commands

    @commands.guild_only()
    @commands.group(aliases=["rnk", "playerCard", "pc"])
    async def rank(self, ctx: Context):
        """Get your rank in points, wins, and games played for the specific queue. If no queue name is given it will show your overall rank across all queues."""

    @commands.guild_only()
    @rank.command(aliases=["all-time", "overall"])
    async def alltime(
        self, ctx: Context, player: discord.Member = None, *, queue_name: str = None
    ):
        """All-time ranks"""
        queue = None
        if queue_name:
            queue = await self._get_queue_by_name(ctx.guild, queue_name)
            players = queue.players
        else:
            players = await self._players(ctx.guild)
            queue_name = ctx.guild.name

        if not players:
            await ctx.send(f":x: Player ranks not available for {queue_name}")
            return

        queue_max_size = queue.maxSize if queue else self.queueMaxSize[ctx.guild]
        sorted_players = self._sort_player_dict(players)
        player = player if player else ctx.author
        await ctx.send(
            embed=self.embed_rank(
                player, sorted_players, queue_name, queue_max_size, "All-time"
            )
        )

    @commands.guild_only()
    @rank.command(aliases=["day"])
    async def daily(
        self, ctx: Context, player: discord.Member = None, *, queue_name: str = None
    ):
        """Daily ranks. All games from the last 24 hours will count"""
        scores = await self._scores(ctx.guild)

        queue = (
            await self._get_queue_by_name(ctx.guild, queue_name) if queue_name else None
        )
        queue_id = queue.id if queue else None
        day_ago = datetime.datetime.now() - datetime.timedelta(days=1)
        players = self._filter_scores(ctx.guild, scores, day_ago, queue_id)[0]
        queue_name = queue.name if queue else ctx.guild.name

        if not players:
            await ctx.send(f":x: Player ranks not available for {queue_name}")
            return

        queue_max_size = queue.maxSize if queue else self.queueMaxSize[ctx.guild]
        sorted_players = self._sort_player_dict(players)
        player = player if player else ctx.author
        await ctx.send(
            embed=self.embed_rank(
                player, sorted_players, queue_name, queue_max_size, "Daily"
            )
        )

    @commands.guild_only()
    @rank.command(aliases=["week", "wk"])
    async def weekly(
        self, ctx: Context, player: discord.Member = None, *, queue_name: str = None
    ):
        """Weekly ranks. All games from the last week will count"""
        scores = await self._scores(ctx.guild)

        queue = (
            await self._get_queue_by_name(ctx.guild, queue_name) if queue_name else None
        )
        queue_id = queue.id if queue else None
        week_ago = datetime.datetime.now() - datetime.timedelta(weeks=1)
        players = self._filter_scores(ctx.guild, scores, week_ago, queue_id)[0]
        queue_name = queue.name if queue else ctx.guild.name

        if not players:
            await ctx.send(f":x: Player ranks not available for {queue_name}")
            return

        queue_max_size = queue.maxSize if queue else self.queueMaxSize[ctx.guild]
        sorted_players = self._sort_player_dict(players)
        player = player if player else ctx.author
        await ctx.send(
            embed=self.embed_rank(
                player, sorted_players, queue_name, queue_max_size, "Weekly"
            )
        )

    @commands.guild_only()
    @rank.command(aliases=["month", "mnth"])
    async def monthly(
        self, ctx: Context, player: discord.Member = None, *, queue_name: str = None
    ):
        """Monthly ranks. All games from the last 30 days will count"""
        scores = await self._scores(ctx.guild)

        queue = (
            await self._get_queue_by_name(ctx.guild, queue_name) if queue_name else None
        )
        queue_id = queue.id if queue else None
        month_ago = datetime.datetime.now() - datetime.timedelta(days=30)
        players = self._filter_scores(ctx.guild, scores, month_ago, queue_id)[0]
        queue_name = queue.name if queue else ctx.guild.name

        if not players:
            await ctx.send(f":x: Player ranks not available for {queue_name}")
            return

        queue_max_size = queue.maxSize if queue else self.queueMaxSize[ctx.guild]
        sorted_players = self._sort_player_dict(players)
        player = player if player else ctx.author
        await ctx.send(
            embed=self.embed_rank(
                player, sorted_players, queue_name, queue_max_size, "Monthly"
            )
        )

    @commands.guild_only()
    @rank.command(aliases=["year", "yr"])
    async def yearly(
        self, ctx: Context, player: discord.Member = None, *, queue_name: str = None
    ):
        """Yearly ranks. All games from the last 365 days will count"""
        scores = await self._scores(ctx.guild)

        queue = (
            await self._get_queue_by_name(ctx.guild, queue_name) if queue_name else None
        )
        queue_id = queue.id if queue else None
        year_ago = datetime.datetime.now() - datetime.timedelta(days=365)
        players = self._filter_scores(ctx.guild, scores, year_ago, queue_id)[0]
        queue_name = queue.name if queue else ctx.guild.name

        if not players:
            await ctx.send(f":x: Player ranks not available for {queue_name}")
            return

        queue_max_size = queue.maxSize if queue else self.queueMaxSize[ctx.guild]
        sorted_players = self._sort_player_dict(players)
        player = player if player else ctx.author
        await ctx.send(
            embed=self.embed_rank(
                player, sorted_players, queue_name, queue_max_size, "Yearly"
            )
        )

    # endregion