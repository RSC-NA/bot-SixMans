import logging
from typing import TYPE_CHECKING

import discord

from sixMans.enums import GameMode

if TYPE_CHECKING:
    from redbot.core import Config

log = logging.getLogger("red.sixMans.settings")


class GuildSettings:
    """Guild-wide settings stored in config, and the helper permission check built on them."""

    if TYPE_CHECKING:
        config: Config
        queueMaxSize: dict[discord.Guild, int]

    async def has_perms(self, member: discord.Member):
        # Admins
        if member.guild_permissions.manage_guild:
            return True

        # Helpers
        helper_role = await self._helper_role(member.guild)
        if helper_role and helper_role in member.roles:
            return True

        # Default to no permissions
        return False

    async def _player_timeout(self, guild: discord.Guild):
        return await self.config.guild(guild).PlayerTimeout()

    async def _save_player_timeout(self, guild: discord.Guild, time_seconds: int):
        await self.config.guild(guild).PlayerTimeout.set(time_seconds)

    async def _get_automove(self, guild: discord.Guild):
        return await self.config.guild(guild).AutoMove()

    async def _save_automove(self, guild: discord.Guild, automove: bool):
        await self.config.guild(guild).AutoMove.set(automove)

    async def _is_react_to_vote(self, guild: discord.Guild):
        return await self.config.guild(guild).ReactToVote()

    async def _save_react_to_vote(self, guild: discord.Guild, automove: bool):
        await self.config.guild(guild).ReactToVote.set(automove)

    async def _category(self, guild: discord.Guild) -> discord.CategoryChannel | None:
        category_id = await self.config.guild(guild).CategoryChannel()
        if not category_id:
            return None
        category = guild.get_channel(category_id)
        if not isinstance(category, discord.CategoryChannel):
            log.error(f"[{guild.name}] 6 mans category is not actually a category.")
            return None
        return category

    async def _save_category(self, guild: discord.Guild, category: int | None):
        await self.config.guild(guild).CategoryChannel.set(category)

    async def _save_q_lobby_vc(self, guild: discord.Guild, vc: int | None):
        await self.config.guild(guild).QLobby.set(vc)

    async def _get_q_lobby_vc(self, guild: discord.Guild):
        log.debug(f"Guild: {guild}")
        lobby_voice = await self.config.guild(guild).QLobby()
        log.debug(f"lobby_voice: {lobby_voice}")
        for vc in guild.voice_channels:
            if vc.id == lobby_voice:
                return vc
        return None

    async def _get_queue_max_size(self, guild: discord.Guild):
        return await self.config.guild(guild).DefaultQueueMaxSize()

    async def _save_queue_max_size(self, guild: discord.Guild, max_size: int):
        await self.config.guild(guild).DefaultQueueMaxSize.set(max_size)
        self.queueMaxSize[guild] = max_size

    async def _helper_role(self, guild: discord.Guild):
        return guild.get_role(await self.config.guild(guild).HelperRole())

    async def _save_helper_role(self, guild: discord.Guild, helper_role):
        await self.config.guild(guild).HelperRole.set(helper_role)

    async def _save_team_selection(self, guild: discord.Guild, team_selection: GameMode):
        await self.config.guild(guild).DefaultTeamSelection.set(team_selection.value)

    async def _team_selection(self, guild: discord.Guild) -> GameMode:
        mode = await self.config.guild(guild).DefaultTeamSelection()
        # Backwards compatibilitgy
        if mode:
            mode = mode.lower().capitalize()
            return GameMode(mode)
        else:
            return GameMode.VOTE

    async def _save_queues_enabled(self, guild: discord.Guild, enabled: bool):
        return await self.config.guild(guild).QueuesEnabled.set(enabled)

    async def _get_queues_enabled(self, guild: discord.Guild):
        return await self.config.guild(guild).QueuesEnabled()
