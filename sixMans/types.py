import collections
from typing import TYPE_CHECKING, TypedDict

import discord

from sixMans.enums import GameMode

if TYPE_CHECKING:
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


class QueueBan(TypedDict):
    expires: int | float
    banned_by: int
    reason: str | None


class SixMansConfig(TypedDict):
    AutoMove: bool
    CategoryChannel: discord.CategoryChannel | None
    DefaultQueueMaxSize: int
    DefaultTeamSelection: GameMode
    Games: dict[discord.Guild, "Game"]
    GamesPlayed: int
    HelperRole: discord.Role | None
    Players: dict[str, PlayerStats]
    PlayerTimeout: int
    QLobby: discord.VoiceChannel | None
    Queues: dict[discord.Guild, list["SixMansQueue"]]
    QueuesEnabled: bool
    ReactToVote: bool
    Scores: list[PlayerScore]
    QueueBans: dict[str, "QueueBan"]


class OrderedSet(collections.abc.MutableSet):
    def __init__(self, iterable=None):
        self.end = end = []
        end += [None, end, end]  # sentinel node for doubly linked list
        self.map = {}  # key --> [key, prev, next]
        if iterable is not None:
            self |= iterable

    def __len__(self):
        return len(self.map)

    def __contains__(self, key):
        return key in self.map

    def add(self, key):
        if key not in self.map:
            end = self.end
            curr = end[1]
            curr[2] = end[1] = self.map[key] = [key, curr, end]

    def discard(self, key):
        if key in self.map:
            key, prev, next = self.map.pop(key)
            prev[2] = next
            next[1] = prev

    def __iter__(self):
        end = self.end
        curr = end[2]
        while curr is not end:
            yield curr[0]
            curr = curr[2]

    def __reversed__(self):
        end = self.end
        curr = end[1]
        while curr is not end:
            yield curr[0]
            curr = curr[1]

    def __repr__(self):
        if not self:
            return "%s()" % (self.__class__.__name__,)
        return "%s(%r)" % (self.__class__.__name__, list(self))

    def __eq__(self, other):
        if isinstance(other, OrderedSet):
            return len(self) == len(other) and list(self) == list(other)
        return set(self) == set(other)
