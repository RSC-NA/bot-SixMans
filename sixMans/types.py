from typing import TypedDict

import discord

from sixMans.enums import GameMode
from sixMans.game import Game
from sixMans.queue import SixMansQueue


class PlayerScore(TypedDict):
    Game: int
    Queue: int
    Player: int
    Win: int
    Points: int
    DateTime: str


class PlayerStats(TypedDict):
    Points: int
    GamesPlayed: int
    Wins: int


class SixMansConfig(TypedDict):
    AutoMove: bool
    CategoryChannel: discord.CategoryChannel | None
    DefaultQueueMaxSize: int
    DefaultTeamSelection: GameMode
    Games: dict[discord.Guild, Game]
    GamesPlayed: int
    HelperRole: discord.Role | None
    Players: dict[str, PlayerStats]
    PlayerTimeout: int
    QLobby: discord.VoiceChannel | None
    Queues: dict[discord.Guild, list[SixMansQueue]]
    QueuesEnabled: bool
    ReactToVote: bool
    Scores: list[PlayerScore]
