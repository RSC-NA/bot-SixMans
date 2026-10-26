import asyncio
import json
from collections.abc import Callable, Coroutine, Iterable
from typing import Any

import discord
from redbot.core import Config

from sixMans.queue import SixMansQueue
from sixMans.scoreboard.stats import give_points, make_score, plan_totals_rebuild
from sixMans.types import PlayerScore, PlayerStats
from sixMans.utils import format_score_time, utc_now

SaveQueues = Callable[[], Coroutine[Any, Any, None]]


class Scoreboard:
    """Score history and player totals for each guild.

    Every read-modify-write of totals goes through `lock`, so a game being scored and a totals
    rebuild can't save over each other.
    """

    def __init__(self, config: Config):
        self.config = config
        self.lock = asyncio.Lock()

    async def scores(self, guild: discord.Guild) -> list[PlayerScore]:
        """Every score row, newest first."""
        return await self.config.guild(guild).Scores()

    async def players(self, guild: discord.Guild) -> dict[str, PlayerStats]:
        """All-time totals across every queue, keyed by player id."""
        return await self.config.guild(guild).Players()

    async def games_played(self, guild: discord.Guild) -> int:
        return await self.config.guild(guild).GamesPlayed()

    async def clear(self, guild: discord.Guild):
        async with self.lock:
            await self._save_scores(guild, [])
            await self._save_games_played(guild, 0)
            await self._save_players(guild, {})

    async def record_game(
        self,
        guild: discord.Guild,
        queue: SixMansQueue,
        game_id: int,
        winners: Iterable[discord.Member],
        losers: Iterable[discord.Member],
        save_queues: SaveQueues,
    ):
        """Add a finished game to the score history and every total it counts towards."""
        async with self.lock:
            scores = await self.scores(guild)
            players = await self.players(guild)
            games_played = await self.games_played(guild)
            date_time = format_score_time(utc_now())
            for win, team in ((1, winners), (0, losers)):
                for player in team:
                    score = make_score(queue.id, queue.points, game_id, player.id, win, date_time)
                    give_points(queue.players, score)
                    give_points(players, score)
                    scores.insert(0, score)

            queue.gamesPlayed += 1

            await self._save_scores(guild, scores)
            await save_queues()
            await self._save_players(guild, players)
            await self._save_games_played(guild, games_played + 1)

    async def rebuild_totals(self, guild: discord.Guild, queues: list[SixMansQueue], apply: bool, save_queues: SaveQueues) -> dict:
        """Plan (and optionally apply) a totals rebuild. Returns every change with its before and after totals."""
        async with self.lock:
            scores = await self.scores(guild)
            players = await self.players(guild)

            player_changes = plan_totals_rebuild(players, scores)
            queue_changes = {queue: plan_totals_rebuild(queue.players, scores, queue.id) for queue in queues}

            record = {
                "server": {pid: {"before": players.get(pid), "after": totals} for pid, totals in player_changes.items()},
                "queues": {
                    str(queue.id): {
                        "name": queue.name,
                        "players": {pid: {"before": queue.players.get(pid), "after": totals} for pid, totals in changes.items()},
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
                        queue.players.update(changes)
                    await save_queues()

        return record

    async def _save_scores(self, guild: discord.Guild, scores: list[PlayerScore]):
        await self.config.guild(guild).Scores.set(scores)

    async def _save_players(self, guild: discord.Guild, players: dict[str, PlayerStats]):
        await self.config.guild(guild).Players.set(players)

    async def _save_games_played(self, guild: discord.Guild, games_played: int):
        await self.config.guild(guild).GamesPlayed.set(games_played)
