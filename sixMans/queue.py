import contextlib
import datetime
import logging
import uuid
from queue import Queue
from typing import List

import discord

from sixMans.embeds import SuccessEmbed
from sixMans.enums import GameMode
from sixMans.strings import Strings
from sixMans.types import OrderedSet

log = logging.getLogger("red.sixMans.queue")


SELECTION_MODES = {
    0x1F3B2: Strings.RANDOM_TS,  # game_die
    0x1F1E8: Strings.CAPTAINS_TS,  # C
    0x0262F: Strings.BALANCED_TS,  # yin_yang
    0x1F530: Strings.SELF_PICKING_TS,  # beginner
    0x1F5F3: Strings.VOTE_TS,  # ballot_box
}


class SixMansQueue:
    def __init__(
        self,
        name: str,
        guild: discord.Guild,
        channels: List[discord.TextChannel],
        points: dict[str, int],
        players: dict[str, dict],
        gamesPlayed: int,
        maxSize: int,
        id: int | None = None,
        category: discord.CategoryChannel | None = None,
        lobby_vc: discord.VoiceChannel | None = None,
        teamSelection=GameMode.VOTE,
    ):
        self.id = id or uuid.uuid4().int
        self.name = name
        self.queue = PlayerQueue()
        self.guild = guild
        self.channels = channels
        self.points = points
        self.players = players
        self.gamesPlayed = gamesPlayed
        self.maxSize = maxSize
        self.teamSelection: GameMode = teamSelection
        self.category = category
        self.lobby_vc = lobby_vc
        self.activeJoinLog: dict[int, datetime.datetime] = {}
        # TODO: active join log could maintain queue during downtime

    def get_player_summary(self, player: discord.Member):
        try:
            return self.players[str(player.id)]
        except KeyError:
            return None

    async def send_message(self, message="", embed=None):
        messages = []
        for channel in self.channels:
            messages.append(await channel.send(message, embed=embed))
        return messages

    async def set_team_selection(self, team_selection):
        self.teamSelection = GameMode(team_selection)

    def queue_full(self):
        return self.queue.qsize() >= self.maxSize

    def clear(self):
        while not self.queue.empty():
            log.debug("Queue not empty.")
            self.queue._get()
        log.debug("Done clearing queue.")

    # Internal

    def _put(self, player):
        self.queue.put(player)

    def _get(self):
        player = self.queue.get()
        with contextlib.suppress(KeyError):
            del self.activeJoinLog[player.id]
        return player

    def _remove(self, player):
        self.queue._remove(player)
        with contextlib.suppress(KeyError):
            del self.activeJoinLog[player.id]

    def _to_dict(self):
        q_data = {
            "Name": self.name,
            "Channels": [x.id for x in self.channels],
            "Points": self.points,
            "Players": self.players,
            "GamesPlayed": self.gamesPlayed,
            "TeamSelection": self.teamSelection,
            "MaxSize": self.maxSize,
        }
        if self.category:
            q_data["Category"] = self.category.id
        if self.lobby_vc:
            q_data["LobbyVC"] = self.lobby_vc.id

        return q_data


class PlayerQueue(Queue):
    def _init(self, maxsize: int):
        self.queue = OrderedSet()

    def _put(self, item):
        self.queue.add(item)

    def _get(self):
        return self.queue.pop()

    def _remove(self, value):
        self.queue.remove(value)

    def __contains__(self, item):
        with self.mutex:
            return item in self.queue
