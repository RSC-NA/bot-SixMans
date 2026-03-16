import logging

import discord
from pydantic import BaseModel, RootModel

log = logging.getLogger("red.sixMans.models.queue")


class Points(BaseModel):
    Play: int
    Win: int


class PlayerData(BaseModel):
    GamesPlayed: int
    Points: int
    Wins: int


QueuePlayers = RootModel[dict[str, PlayerData]]


class QueueData(BaseModel):
    Category: int | None = None
    Channels: list[int]
    GamesPlayed: int
    LobbyVC: int | None = None
    MaxSize: int | None = None
    Name: str
    Players: QueuePlayers
    Points: Points
    TeamSelection: str | None = None

    def guild_channels(self, guild: discord.Guild) -> list[discord.TextChannel]:
        channels: list[discord.TextChannel] = []
        for c in self.Channels:
            tmp = guild.get_channel(c)
            if not tmp:
                log.warning(f"Queue has non-existent channel ID: {c}")
                continue

            if not isinstance(tmp, discord.TextChannel):
                log.warning(f"Queue has non-text channel associated: {c}")
                continue

            channels.append(tmp)
        return channels

    def guild_category(self, guild: discord.Guild) -> discord.CategoryChannel | None:
        if not self.Category:
            return None
        c = guild.get_channel(self.Category)
        if not c:
            return None
        if not isinstance(c, discord.CategoryChannel):
            log.warning(f"Queue has non-category channel associated: {self.Category}")
            return None
        return c

    def lobby_vc(self, guild: discord.Guild) -> discord.VoiceChannel | None:
        if not self.LobbyVC:
            return None
        c = guild.get_channel(self.LobbyVC)
        if not c:
            return None
        if not isinstance(c, discord.VoiceChannel):
            log.warning(f"Queue has non-voice channel associated: {self.LobbyVC}")
            return None
        return c


GuildQueueData = RootModel[dict[str, QueueData]]
