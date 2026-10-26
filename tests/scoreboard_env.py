"""A cog backed by Red's real JSON config, loaded with a fixed scoreboard scenario.

Shared by tests that need what the commands actually read and persist, not mocks of it.
"""

import datetime
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import discord
from redbot.core import Config
from redbot.core._drivers.json import JsonDriver

from sixMans.sixMans import SixMans, defaults
from sixMans.types import PlayerScore
from sixMans.utils import format_score_time, utc_now

GUILD_ID = 395806681994493964
GENERAL = 111
DUELS = 222
EMPTY = 333


def make_config(tmp_path) -> Config:
    # Red shares JSON data between drivers by cog name, so each config gets its own
    driver = JsonDriver(f"SixMansTest{uuid.uuid4().hex}", "1234567896", data_path_override=tmp_path)
    conf = Config(cog_name=driver.cog_name, unique_identifier="1234567896", driver=driver, force_registration=True)
    conf.register_guild(**defaults)
    return conf


def make_channel(channel_id: int, kind=discord.TextChannel):
    channel = MagicMock(spec=kind)
    channel.id = channel_id
    channel.mention = f"<#{channel_id}>"
    channel.send = AsyncMock()
    channel.delete = AsyncMock()
    return channel


def make_guild(channel_ids=(10, 20, 30)):
    guild = MagicMock(spec=discord.Guild)
    guild.id = GUILD_ID
    guild.name = "RSC 3v3"
    channels = {cid: make_channel(cid) for cid in channel_ids}
    for channel in channels.values():
        channel.guild = guild
    guild.get_channel = lambda channel_id: channels.get(channel_id)
    return guild


def make_member(member_id: int, guild=None):
    member = MagicMock(spec=discord.Member)
    member.id = member_id
    member.display_name = f"Player{member_id}"
    member.mention = f"<@{member_id}>"
    member.guild = guild
    member.display_avatar.url = f"https://cdn.example/{member_id}.png"
    member.__eq__ = lambda self, other: getattr(other, "id", None) == self.id  # ty: ignore[invalid-assignment]
    member.__hash__ = lambda self: hash(self.id)  # ty: ignore[invalid-assignment]
    return member


async def build_cog(config: Config, guild, guild_data: dict) -> SixMans:
    bot = MagicMock()
    bot.guilds = [guild]
    with patch("sixMans.sixMans.Config.get_conf", return_value=config), patch("sixMans.sixMans.asyncio.create_task"):
        cog = SixMans(bot)
    for key, value in guild_data.items():
        await config.guild(guild).get_attr(key).set(value)
    await cog.cog_load()
    return cog


def queue_data(name: str, channel_id: int, points: tuple[int, int], max_size: int, players: dict, games_played: int) -> dict:
    return {
        "Name": name,
        "Channels": [channel_id],
        "Points": {"Play": points[0], "Win": points[1]},
        "Players": players,
        "GamesPlayed": games_played,
        "TeamSelection": "Vote",
        "MaxSize": max_size,
    }


def scenario() -> dict:
    """Guild config with games in every leaderboard window, more than ten players, and stored totals."""
    now = utc_now()
    game_ids = iter(range(1000, 2000))

    def game(queue: int, hours_ago: float, winners: list[int], losers: list[int], points: tuple[int, int]) -> list[PlayerScore]:
        when = format_score_time(now - datetime.timedelta(hours=hours_ago))
        game_id = next(game_ids)
        rows = [PlayerScore(Game=game_id, Queue=queue, Player=p, Win=1, Points=points[0] + points[1], DateTime=when) for p in winners]
        rows += [PlayerScore(Game=game_id, Queue=queue, Player=p, Win=0, Points=points[0], DateTime=when) for p in losers]
        return rows

    general, duels = (1, 2), (1, 1)
    games = [
        game(GENERAL, 1, [1, 2, 3], [4, 5, 6], general),
        game(DUELS, 2, [1], [14], duels),
        game(GENERAL, 24 * 3, [1, 2, 7], [8, 9, 10], general),
        game(DUELS, 24 * 10, [14], [2], duels),
        game(GENERAL, 24 * 20, [3, 4, 5], [6, 7, 8], general),
        game(GENERAL, 24 * 200, [11, 12, 13], [1, 2, 3], general),
        game(GENERAL, 24 * 400, [4, 5, 6], [1, 2, 3], general),
    ]
    scores = [row for rows in games for row in rows]  # Already newest first

    # Stored totals deliberately include players with no score history, like long-running guilds do
    server_players = {str(p): {"Points": 40 - p * 2, "Wins": 15 - p, "GamesPlayed": 30 - p} for p in range(1, 15)}
    server_players["20"] = {"Points": 50, "Wins": 25, "GamesPlayed": 25}
    server_players["21"] = {"Points": 3, "Wins": 1, "GamesPlayed": 1}
    general_players = {str(p): {"Points": 30 - p * 2, "Wins": 12 - p, "GamesPlayed": 20 - p} for p in range(1, 14)}
    general_players["7"] = {"Points": 9, "Wins": 3, "GamesPlayed": 3}  # 50% win rate for balancing
    duels_players = {"1": {"Points": 4, "Wins": 2, "GamesPlayed": 2}, "2": {"Points": 1, "Wins": 0, "GamesPlayed": 1}, "14": {"Points": 3, "Wins": 1, "GamesPlayed": 2}}

    return {
        "Scores": scores,
        "Players": server_players,
        "GamesPlayed": 42,
        "Queues": {
            str(GENERAL): queue_data("General", 10, general, 6, general_players, 37),
            str(DUELS): queue_data("Duels", 20, duels, 2, duels_players, 5),
            str(EMPTY): queue_data("Empty", 30, general, 6, {}, 0),
        },
    }


LEFT_SERVER = {13}  # Member lookups fail for these, as for anyone who has left the guild
