import asyncio
import json
import logging
from collections.abc import Iterable

import discord
from redbot.core import Config

from sixMans.queue import SixMansQueue
from sixMans.scoreboard.stats import give_points, make_score, plan_totals_rebuild
from sixMans.types import PlayerScore, PlayerStats, QueueStats
from sixMans.utils import format_score_time, utc_now

log = logging.getLogger("red.sixMans.scoreboard")

# 1: Per-queue totals and game counts moved from each saved queue into QueueStats
SCHEMA_VERSION = 1


class Scoreboard:
    """Score history and player totals for each guild.

    Every read-modify-write of totals goes through `lock`, so a game being scored and a totals
    rebuild can't save over each other. Per-queue stats are also kept in memory, because team
    balancing reads them synchronously.
    """

    def __init__(self, config: Config):
        self.config = config
        self.lock = asyncio.Lock()
        self._queue_stats: dict[int, dict[str, QueueStats]] = {}

    async def load(self, guild: discord.Guild):
        """Migrate the guild's stats if needed, then (re)load per-queue stats into memory."""
        async with self.lock:
            await self._migrate(guild)
            self._queue_stats[guild.id] = await self.config.guild(guild).QueueStats()

    async def scores(self, guild: discord.Guild) -> list[PlayerScore]:
        """Every score row, newest first."""
        return await self.config.guild(guild).Scores()

    async def players(self, guild: discord.Guild) -> dict[str, PlayerStats]:
        """All-time totals across every queue, keyed by player id."""
        return await self.config.guild(guild).Players()

    async def games_played(self, guild: discord.Guild) -> int:
        return await self.config.guild(guild).GamesPlayed()

    def queue_players(self, guild: discord.Guild, queue_id: int) -> dict[str, PlayerStats]:
        """All-time totals in one queue, keyed by player id."""
        stats = self._queue_stats.get(guild.id, {}).get(str(queue_id))
        return stats["Players"] if stats else {}

    def queue_games_played(self, guild: discord.Guild, queue_id: int) -> int:
        stats = self._queue_stats.get(guild.id, {}).get(str(queue_id))
        return stats["GamesPlayed"] if stats else 0

    def queue_player(self, guild: discord.Guild, queue_id: int, player_id: int) -> PlayerStats | None:
        return self.queue_players(guild, queue_id).get(str(player_id))

    async def clear(self, guild: discord.Guild):
        async with self.lock:
            await self._save_scores(guild, [])
            await self._save_games_played(guild, 0)
            await self._save_players(guild, {})
            self._queue_stats[guild.id] = {}
            await self._save_queue_stats(guild)

    async def mark_queue_deleted(self, guild: discord.Guild, queue: SixMansQueue):
        """Keep a removed queue's stats, flagged so it's clear the queue no longer exists."""
        async with self.lock:
            stats = self._entry(guild, queue)
            stats["Deleted"] = True
            await self._save_queue_stats(guild)

    async def record_game(self, guild: discord.Guild, queue: SixMansQueue, game_id: int, winners: Iterable[discord.Member], losers: Iterable[discord.Member]):
        """Add a finished game to the score history and every total it counts towards."""
        async with self.lock:
            scores = await self.scores(guild)
            players = await self.players(guild)
            games_played = await self.games_played(guild)
            queue_stats = self._entry(guild, queue)
            date_time = format_score_time(utc_now())
            for win, team in ((1, winners), (0, losers)):
                for player in team:
                    score = make_score(queue.id, queue.points, game_id, player.id, win, date_time)
                    give_points(queue_stats["Players"], score)
                    give_points(players, score)
                    scores.insert(0, score)

            queue_stats["GamesPlayed"] += 1

            await self._save_scores(guild, scores)
            await self._save_queue_stats(guild)
            await self._save_players(guild, players)
            await self._save_games_played(guild, games_played + 1)

    async def rebuild_totals(self, guild: discord.Guild, queues: list[SixMansQueue], apply: bool) -> dict:
        """Plan (and optionally apply) a totals rebuild. Returns every change with its before and after totals."""
        async with self.lock:
            scores = await self.scores(guild)
            players = await self.players(guild)

            player_changes = plan_totals_rebuild(players, scores)
            queue_changes = {queue: plan_totals_rebuild(self.queue_players(guild, queue.id), scores, queue.id) for queue in queues}

            record = {
                "server": {pid: {"before": players.get(pid), "after": totals} for pid, totals in player_changes.items()},
                "queues": {
                    str(queue.id): {
                        "name": queue.name,
                        "players": {pid: {"before": self.queue_players(guild, queue.id).get(pid), "after": totals} for pid, totals in changes.items()},
                    }
                    for queue, changes in queue_changes.items()
                    if changes
                },
            }
            # Serialize now so the record can't pick up later changes to the live totals
            record = json.loads(json.dumps(record))

            if apply:
                if player_changes:
                    players.update(player_changes)
                    await self._save_players(guild, players)
                if any(queue_changes.values()):
                    for queue, changes in queue_changes.items():
                        self._entry(guild, queue)["Players"].update(changes)
                    await self._save_queue_stats(guild)

        return record

    def _entry(self, guild: discord.Guild, queue: SixMansQueue) -> QueueStats:
        """The queue's stats, created on first use. Only call while holding `lock`."""
        stats = self._queue_stats.setdefault(guild.id, {}).setdefault(str(queue.id), QueueStats(Name=queue.name, Deleted=False, GamesPlayed=0, Players={}))
        stats["Name"] = queue.name  # Follow renames, so a deleted queue is recorded under its final name
        return stats

    async def _migrate(self, guild: discord.Guild):
        group = self.config.guild(guild)
        if await group.ScoreboardSchema() >= SCHEMA_VERSION:
            return

        # Each saved queue keeps its Players and GamesPlayed, frozen from here on, so rolling back
        # to code from before this move still loads.
        queues = await group.Queues()
        queue_stats = await group.QueueStats()
        for queue_id, queue in queues.items():
            queue_stats.setdefault(queue_id, QueueStats(Name=queue["Name"], Deleted=False, GamesPlayed=queue.get("GamesPlayed", 0), Players=queue.get("Players", {})))
        await group.QueueStats.set(queue_stats)
        await group.ScoreboardSchema.set(SCHEMA_VERSION)
        log.info(f"[{guild.name}] Moved per-queue stats for {len(queues)} queues into the scoreboard.")

    async def _save_queue_stats(self, guild: discord.Guild):
        await self.config.guild(guild).QueueStats.set(self._queue_stats.get(guild.id, {}))

    async def _save_scores(self, guild: discord.Guild, scores: list[PlayerScore]):
        await self.config.guild(guild).Scores.set(scores)

    async def _save_players(self, guild: discord.Guild, players: dict[str, PlayerStats]):
        await self.config.guild(guild).Players.set(players)

    async def _save_games_played(self, guild: discord.Guild, games_played: int):
        await self.config.guild(guild).GamesPlayed.set(games_played)
