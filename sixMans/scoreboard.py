import discord
from redbot.core import Config

from sixMans.queue import SixMansQueue
from sixMans.types import PlayerScore, PlayerStats


class Scoreboard:
    def __init__(self, config: Config):
        self.config = config

    async def overall(self, guild: discord.Guild, queue: SixMansQueue | None = None):
        """All-time leader board"""
        players = None
        queue = self.get_queue_by_name(ctx.guild, queue_name) if queue_name else None
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

    def _give_points(self, players_dict: dict[str, PlayerStats], score: PlayerScore):
        player_id = score["Player"]
        points_earned = score["Points"]
        win = score["Win"]

        new_player = PlayerStats(Points=0, Wins=0, GamesPlayed=0)

        player_score = players_dict.get(str(player_id), new_player)
        player_score["Points"] = player_score["Points"] + points_earned
        player_score["GamesPlayed"] = player_score["GamesPlayed"] + 1
        player_score["Wins"] = player_score["Wins"] + win

    async def _games(self, guild: discord.Guild):
        return await self.config.guild(guild).Games()

    async def _queues(self, guild: discord.Guild):
        return await self.config.guild(guild).Queues()

    async def _scores(self, guild: discord.Guild) -> list[PlayerScore]:
        return await self.config.guild(guild).Scores()

    async def _save_scores(self, guild: discord.Guild, scores: list[PlayerScore]):
        await self.config.guild(guild).Scores.set(scores)

    async def _games_played(self, guild: discord.Guild):
        return await self.config.guild(guild).GamesPlayed()

    async def _save_games_played(self, guild: discord.Guild, games_played: int):
        await self.config.guild(guild).GamesPlayed.set(games_played)

    async def _players(self, guild: discord.Guild) -> dict[str, PlayerStats]:
        return await self.config.guild(guild).Players()

    async def _save_players(
        self, guild: discord.Guild, players: dict[str, PlayerStats]
    ):
        await self.config.guild(guild).Players.set(players)
