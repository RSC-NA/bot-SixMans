import logging

import discord
from pydantic import BaseModel

from sixMans.enums import GameMode, GameState, Winner

log = logging.getLogger("red.sixMans.models.game")


class GameData(BaseModel):
    Blue: list[int]
    Captains: list[int]
    Orange: list[int]
    Players: list[int]
    Prefix: str
    QueueId: int
    RoomName: str
    RoomPass: str
    State: GameState
    TeamSelection: GameMode
    TextChannel: int
    VoiceChannels: list[int]
    Winner: Winner

    def get_player_members(self, guild: discord.Guild) -> list[discord.Member]:
        members: list[discord.Member] = []
        for p in self.Players:
            m = guild.get_member(p)
            if not m:
                log.warning(f"Player does not exist in guild: {p}")
                continue
            members.append(m)
        return members

    def get_blue_members(self, guild: discord.Guild) -> list[discord.Member]:
        members: list[discord.Member] = []
        for p in self.Blue:
            m = guild.get_member(p)
            if not m:
                log.warning(f"Player does not exist in guild: {p}")
                continue
            members.append(m)
        return members

    def get_orange_members(self, guild: discord.Guild) -> list[discord.Member]:
        members: list[discord.Member] = []
        for p in self.Orange:
            m = guild.get_member(p)
            if not m:
                log.warning(f"Player does not exist in guild: {p}")
                continue
            members.append(m)
        return members

    def get_captain_members(self, guild: discord.Guild) -> list[discord.Member]:
        members: list[discord.Member] = []
        for p in self.Captains:
            m = guild.get_member(p)
            if not m:
                log.warning(f"Player does not exist in guild: {p}")
                continue
            members.append(m)
        return members

    def guild_text_channel(self, guild: discord.Guild) -> discord.TextChannel | None:
        c = guild.get_channel(self.TextChannel)
        if not c:
            return None
        if not isinstance(c, discord.TextChannel):
            log.warning(f"Game has a non-text channel associated: {self.TextChannel}")
            return None
        return c

    def guild_voice_channels(self, guild: discord.Guild) -> list[discord.VoiceChannel]:
        channels: list[discord.VoiceChannel] = []
        for c in self.VoiceChannels:
            vc = guild.get_channel(c)
            if not vc:
                log.warning(f"Game voice channel does not exist: {c}")
                continue
            if not isinstance(vc, discord.VoiceChannel):
                log.warning(f"Game has non-voice channel associated: {c}")
                continue
            channels.append(vc)
        return channels
