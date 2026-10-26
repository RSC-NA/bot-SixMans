import datetime
import io
import json
import logging
from typing import TYPE_CHECKING

import discord
from discord.ext.commands import Context
from redbot.core import checks, commands
from redbot.core.utils.menus import start_adding_reactions
from redbot.core.utils.predicates import ReactionPredicate

from sixMans.scoreboard.embeds import leaderboard_embed, rank_embed
from sixMans.scoreboard.stats import filter_scores, sort_players
from sixMans.utils import utc_now

if TYPE_CHECKING:
    from sixMans.queue import SixMansQueue
    from sixMans.scoreboard.scoreboard import Scoreboard

log = logging.getLogger("red.sixMans.scoreboard")

CONFIRM_TIMEOUT = 60  # How long an admin has to confirm a totals rebuild (seconds)
DAY = datetime.timedelta(days=1)
WEEK = datetime.timedelta(weeks=1)
MONTH = datetime.timedelta(days=30)
YEAR = datetime.timedelta(days=365)


class ScoreboardCommands:
    """Leaderboard, rank and totals rebuild commands, mixed into the SixMans cog."""

    if TYPE_CHECKING:
        scoreboard: Scoreboard
        queues: dict[discord.Guild, list[SixMansQueue]]
        queueMaxSize: dict[discord.Guild, int]

        def get_queue_by_name(self, guild: discord.Guild, queue_name: str) -> SixMansQueue | None: ...

    # region leaderboard commands

    @commands.guild_only()
    @commands.group(aliases=["qlb"])
    async def queueLeaderBoard(self, ctx: Context):
        """
        Get the top ten players in points for the specific queue.

        If no queue name is given the list will be the top ten players across all queues.
        If you're not in the top ten your name and rank will be shown at the bottom of the list.
        """

    @commands.guild_only()
    @queueLeaderBoard.command(aliases=["all-time", "alltime"])
    async def overall(self, ctx: Context, *, queue_name: str | None = None):
        """All-time leader board"""
        await self._send_leaderboard(ctx, queue_name, "All-time", None)

    @commands.guild_only()
    @queueLeaderBoard.command(aliases=["daily"])
    async def day(self, ctx: Context, *, queue_name: str | None = None):
        """Daily leader board. All games from the last 24 hours will count"""
        await self._send_leaderboard(ctx, queue_name, "Daily", DAY)

    @commands.guild_only()
    @queueLeaderBoard.command(aliases=["weekly", "wk"])
    async def week(self, ctx: Context, *, queue_name: str | None = None):
        """Weekly leader board. All games from the last week will count"""
        await self._send_leaderboard(ctx, queue_name, "Weekly", WEEK)

    @commands.guild_only()
    @queueLeaderBoard.command(aliases=["monthly", "mnth"])
    async def month(self, ctx: Context, *, queue_name: str | None = None):
        """Monthly leader board. All games from the last 30 days will count"""
        await self._send_leaderboard(ctx, queue_name, "Monthly", MONTH)

    @commands.guild_only()
    @queueLeaderBoard.command(aliases=["yearly", "yr"])
    async def year(self, ctx: Context, *, queue_name: str | None = None):
        """Yearly leader board. All games from the last 365 days will count"""
        await self._send_leaderboard(ctx, queue_name, "Yearly", YEAR)

    # endregion

    # region rank commands

    @commands.guild_only()
    @commands.group(aliases=["rnk", "playerCard", "pc"])
    async def rank(self, ctx: Context):
        """
        Get your rank in points, wins, and games played for the specific queue.

        If no queue name is given it will show your overall rank across all queues.
        """

    @commands.guild_only()
    @rank.command(aliases=["all-time", "overall"])
    async def alltime(self, ctx: Context, player: discord.Member | None = None, *, queue_name: str | None = None):
        """All-time ranks"""
        await self._send_rank(ctx, player, queue_name, "All-time", None)

    @commands.guild_only()
    @rank.command(aliases=["day"])
    async def daily(self, ctx: Context, player: discord.Member | None = None, *, queue_name: str | None = None):
        """Daily ranks. All games from the last 24 hours will count"""
        await self._send_rank(ctx, player, queue_name, "Daily", DAY)

    @commands.guild_only()
    @rank.command(aliases=["week", "wk"])
    async def weekly(self, ctx: Context, player: discord.Member | None = None, *, queue_name: str | None = None):
        """Weekly ranks. All games from the last week will count"""
        await self._send_rank(ctx, player, queue_name, "Weekly", WEEK)

    @commands.guild_only()
    @rank.command(aliases=["month", "mnth"])
    async def monthly(self, ctx: Context, player: discord.Member | None = None, *, queue_name: str | None = None):
        """Monthly ranks. All games from the last 30 days will count"""
        await self._send_rank(ctx, player, queue_name, "Monthly", MONTH)

    @commands.guild_only()
    @rank.command(aliases=["year", "yr"])
    async def yearly(self, ctx: Context, player: discord.Member | None = None, *, queue_name: str | None = None):
        """Yearly ranks. All games from the last 365 days will count"""
        await self._send_rank(ctx, player, queue_name, "Yearly", YEAR)

    # endregion

    # region admin commands

    @commands.guild_only()
    @commands.command()
    @checks.admin_or_permissions(manage_guild=True)
    async def rebuildPlayerTotals(self, ctx: Context):
        """Restore all-time totals for players a past bug failed to record.

        Only players whose first game came after the bug shipped are rebuilt from score history.
        Everyone else's totals are left exactly as they are. A file with every change is posted afterwards.
        """
        if not ctx.guild:
            return

        preview = await self._rebuild_player_totals(ctx.guild, apply=False)
        if not preview["server"] and not preview["queues"]:
            return await ctx.send("No player totals need rebuilding.")

        msg = await ctx.send(f"{ctx.author.mention} Rebuilding player totals will make these changes. No other player's totals will change.\n{summarize_rebuild(preview)}\nContinue?")
        start_adding_reactions(msg, ReactionPredicate.YES_OR_NO_EMOJIS)
        pred = ReactionPredicate.yes_or_no(msg, ctx.author)  # ty: ignore[invalid-argument-type]  # Member.bot is a read-only property; discord.abc.User declares it writable
        try:
            await ctx.bot.wait_for("reaction_add", check=pred, timeout=CONFIRM_TIMEOUT)
        except TimeoutError:
            return await ctx.send(":x: Timed out. Player totals **not** changed.")
        if not pred.result:
            return await ctx.send(":x: Player totals **not** changed.")

        # Games may have finished while waiting, so the applied changes are planned again from current data
        record = await self._rebuild_player_totals(ctx.guild, apply=True)
        if not record["server"] and not record["queues"]:
            return await ctx.send("No player totals need rebuilding.")

        log.info(f"[{ctx.guild.name}] {ctx.author} rebuilt player totals: {json.dumps(record)}")
        changes = discord.File(io.BytesIO(json.dumps(record, indent=2).encode()), filename="player_totals_changes.json")
        await ctx.send(f"Done. Player totals rebuilt.\n{summarize_rebuild(record)}", file=changes)

    # endregion

    async def _send_leaderboard(self, ctx: Context, queue_name: str | None, label: str, window: datetime.timedelta | None):
        """Send a points leaderboard for all time (no `window`) or for games within `window`."""
        if not ctx.guild:
            return

        queue = self.get_queue_by_name(ctx.guild, queue_name) if queue_name else None
        queue_name = queue.name if queue else ctx.guild.name

        if window is None:
            if queue:
                players = self.scoreboard.queue_players(ctx.guild, queue.id)
                games_played = self.scoreboard.queue_games_played(ctx.guild, queue.id)
            else:
                players = await self.scoreboard.players(ctx.guild)
                games_played = await self.scoreboard.games_played(ctx.guild)
        else:
            scores = await self.scoreboard.scores(ctx.guild)
            players, games_played = filter_scores(scores, utc_now() - window, queue.id if queue else None, self.queueMaxSize[ctx.guild])

        if games_played == 0:
            await ctx.send(f":x: No games have been played in {queue_name}")
            return

        if not players:
            await ctx.send(f":x: Queue leaderboard not available for {queue_name}")
            return

        team_size = queue.maxSize if queue else self.queueMaxSize[ctx.guild]
        embed = await leaderboard_embed(ctx, sort_players(players), queue_name, team_size, games_played, label)
        await ctx.send(embed=embed)

    async def _send_rank(self, ctx: Context, player: discord.Member | None, queue_name: str | None, label: str, window: datetime.timedelta | None):
        """Send a player's ranks for all time (no `window`) or for games within `window`."""
        if not ctx.guild:
            return

        if not isinstance(ctx.author, discord.Member):
            return

        queue = self.get_queue_by_name(ctx.guild, queue_name) if queue_name else None
        if window is None:
            players = self.scoreboard.queue_players(ctx.guild, queue.id) if queue else await self.scoreboard.players(ctx.guild)
        else:
            scores = await self.scoreboard.scores(ctx.guild)
            players = filter_scores(scores, utc_now() - window, queue.id if queue else None, self.queueMaxSize[ctx.guild])[0]
        queue_name = queue.name if queue else ctx.guild.name

        if not players:
            await ctx.send(f":x: Player ranks not available for {queue_name}")
            return

        queue_max_size = queue.maxSize if queue else self.queueMaxSize[ctx.guild]
        await ctx.send(embed=rank_embed(player or ctx.author, sort_players(players), queue_name, queue_max_size, label))

    async def _rebuild_player_totals(self, guild: discord.Guild, apply: bool) -> dict:
        return await self.scoreboard.rebuild_totals(guild, self.queues.get(guild, []), apply)


def summarize_rebuild(record: dict) -> str:
    def describe(changes: dict) -> str:
        added = sum(1 for change in changes.values() if change["before"] is None)
        return f"{added} added, {len(changes) - added} updated"

    lines = []
    if record["server"]:
        lines.append(f"**Server totals:** {describe(record['server'])}")
    lines.extend(f"**{queue['name']}:** {describe(queue['players'])}" for queue in record["queues"].values())
    return "\n".join(lines)
