from sys import exc_info, maxsize
from typing import Dict, List

import discord
from redbot.core import commands

from sixMans.sixMansSplit.functions import *
from sixMansSplit.sixMansParent import SixMansParent


class Listerners(SixMansParent):
    # region listeners
    @commands.Cog.listener("on_raw_reaction_add")
    async def on_raw_reaction_add(self, payload: discord.RawReactionActionEvent):
        log.debug(f"Raw Reaction Add: {payload}")
        channel = self.bot.get_channel(payload.channel_id)
        if type(channel) == discord.DMChannel:
            return

        message = await channel.fetch_message(payload.message_id)
        user = self.bot.get_user(payload.user_id)
        if not user:
            user = await self.bot.fetch_user(payload.user_id)

        await self.process_six_mans_reaction_add(message, channel, user, payload.emoji)

    @commands.Cog.listener("on_raw_reaction_remove")
    async def on_raw_reaction_remove(self, payload: discord.RawReactionActionEvent):
        log.debug(f"Raw Reaction Remove: {payload}")
        channel = self.bot.get_channel(payload.channel_id)
        if type(channel) == discord.DMChannel:
            return

        user = self.bot.get_user(payload.user_id)
        if not user:
            user = await self.bot.fetch_user(payload.user_id)

        await self.process_six_mans_reaction_removed(channel, user, payload.emoji)

    @commands.Cog.listener("on_guild_channel_delete")
    async def on_guild_channel_delete(self, channel):
        """If a queue channel is deleted, removes it from the queue class instance. If the last queue channel is deleted, the channel is replaced."""
        # TODO: Error catch if Q Lobby VC is deleted
        if type(channel) != discord.TextChannel:
            return
        queue = None
        for queue in self.queues[channel.guild]:
            if channel in queue.channels:
                queue.channels.remove(channel)
                break
        if queue.channels:
            return

        clone = await channel.clone()
        helper_role = await self._helper_role(channel.guild)
        helper_ping = f" {helper_role.mention}" if helper_role else ""
        await clone.send(
            f":grey_exclamation:{helper_ping} This channel has been created because the last textChannel for the **{queue.name}** queue has been deleted."
        )
        queue.channels.append(clone)
        await self._save_queues(channel.guild, self.queues[channel.guild])

    # endregion
