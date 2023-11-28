# region get and set commands

from sys import exc_info, maxsize
from typing import Dict, List

import discord
from discord.ext.commands import Context
from redbot.core import checks, commands
from redbot.core.utils.menus import start_adding_reactions


from sixMans.sixMansSplit.functions import *
from sixMansSplit.sixMansParent import SixMansParent
from sixMans.game import Game

from sixMans.views import GameMode


class GetSetCommands(SixMansParent):
    @commands.guild_only()
    @commands.command(aliases=["cq", "status"])
    async def checkQueue(self, ctx: Context):
        six_mans_queue = self._get_queue_by_text_channel(ctx.channel)
        if not six_mans_queue:
            await ctx.send(":x: No queue set up in this channel")
            return
        await ctx.send(embed=self.embed_queue_players(six_mans_queue))

    @commands.guild_only()
    @commands.command(aliases=["setQLobby", "setQVC"])
    @checks.admin_or_permissions(manage_guild=True)
    async def setQueueLobby(self, ctx: Context, lobby_voice: discord.VoiceChannel):
        # TODO: Consider having the queues save the Queue Lobby VC
        for queue in self.queues[ctx.guild]:
            queue.lobby_vc = lobby_voice
        await self._save_q_lobby_vc(ctx.guild, lobby_voice.id)
        await self._save_queues(ctx.guild, self.queues[ctx.guild])
        await ctx.send("Done")

    @commands.guild_only()
    @commands.command(aliases=["unsetQueueLobby, unsetQLobby", "clearQLobby"])
    @checks.admin_or_permissions(manage_guild=True)
    async def clearQueueLobby(self, ctx: Context):
        await self._save_q_lobby_vc(ctx.guild, None)
        await ctx.send("Done")

    @commands.guild_only()
    @commands.command(aliases=["qn"])
    async def getQueueNames(self, ctx: Context):
        queue_names = ""
        for queue in self.queues[ctx.guild]:
            if queue.guild == ctx.guild:
                queue_names += f"{queue.name}\n"
        await ctx.send(f"```Queues set up in server:\n{queue_names}```")

    @commands.guild_only()
    @commands.command(aliases=["qi"])
    async def getQueueInfo(self, ctx: Context, *, queue_name=None):
        if queue_name:
            for queue in self.queues[ctx.guild]:
                if queue.name.lower() == queue_name.lower():
                    await ctx.send(
                        embed=self.embed_queue_info(
                            queue, await self._get_q_lobby_vc(ctx.guild)
                        )
                    )
                    return
            await ctx.send(f":x: No queue set up with name: {queue.name}")
            return

        six_mans_queue = self._get_queue_by_text_channel(ctx.channel)
        if not six_mans_queue:
            await ctx.send(":x: No queue set up in this channel")
            return

        await ctx.send(
            embed=self.embed_queue_info(
                six_mans_queue, await self._get_q_lobby_vc(ctx.guild)
            )
        )

    @commands.guild_only()
    @commands.command()
    @checks.admin_or_permissions(manage_guild=True)
    async def toggleAutoMove(self, ctx: Context):
        """Toggle whether or not bot moves members to their assigned team voice channel"""
        new_automove_status = not await self._get_automove(ctx.guild)
        await self._save_automove(ctx.guild, new_automove_status)

        action = "will move" if new_automove_status else "will not move"
        message = f"Popped {self.queueMaxSize[ctx.guild]} Mans queues **{action}** members to their team voice channel."
        await ctx.send(message)

    @commands.guild_only()
    @commands.command(aliases=["toggleReactToVote", "tvm", "trtv"])
    @checks.admin_or_permissions(manage_guild=True)
    async def toggleVoteMethod(self, ctx: Context):
        """Toggles team selection voting method between commands and reactions."""
        react_to_vote = not await self._is_react_to_vote(ctx.guild)
        await self._save_react_to_vote(ctx.guild, react_to_vote)

        action = "reactions" if react_to_vote else "commands"
        message = f"Members of popped {self.queueMaxSize[ctx.guild]} Mans queues will vote for team reactions with **{action}**."
        await ctx.send(message)

    @commands.guild_only()
    @commands.command(aliases=["setTeamSelection"])
    @checks.admin_or_permissions(manage_guild=True)
    async def setDefaultTeamSelection(self, ctx: Context, team_selection_method):
        """Set method for Six Mans team selection (Default: Vote)

        Valid team selecion methods options:
        - **Random**: selects random teams
        - **Captains**: selects a captain for each team
        - **Vote**: players vote for team selection method after queue pops
        - **Balanced**: creates balanced teams from all participating players
        """
        # TODO: Support Captains [captains random, captains shuffle], Balanced
        if await self._get_queue_max_size(ctx.guild) == 2:
            return await ctx.send(
                ":x: You may not change team selection method when default queue max size is 2."
            )

        try:
            ts = GameMode(team_selection_method)
            await self._save_team_selection(ctx.guild, team_selection_method)
            await ctx.send("Done.")
        except ValueError:
            return await ctx.send(
                f"**{team_selection_method}** is not a valid method of team selection."
            )

    @commands.guild_only()
    @commands.command(aliases=["getTeamSelection"])
    @checks.admin_or_permissions(manage_guild=True)
    async def getDefaultTeamSelection(self, ctx: Context):
        """Get method for Six Mans team selection (Default: Random)"""
        team_selection = await self._team_selection(ctx.guild)
        await ctx.send(
            f"Six Mans team selection is currently set to **{team_selection}**."
        )

    @commands.guild_only()
    @commands.command()
    @checks.admin_or_permissions(manage_guild=True)
    async def setCategory(
        self, ctx: Context, category_channel: discord.CategoryChannel
    ):
        """Sets the category channel where all game channels will be created under"""
        for queue in self.queues[ctx.guild]:
            queue.category = category_channel
        await self._save_category(ctx.guild, category_channel.id)
        await self._save_queues(ctx.guild, self.queues[ctx.guild])
        await ctx.send("Done")

    @commands.guild_only()
    @commands.command()
    @checks.admin_or_permissions(manage_guild=True)
    async def getCategory(self, ctx: Context):
        """Gets the channel currently assigned as the transaction channel"""
        try:
            await ctx.send(
                f"{self.queueMaxSize[ctx.guild]} Mans category channel set to: {(await self._category(ctx.guild)).mention}"
            )
        except:
            await ctx.send(
                f":x: {self.queueMaxSize[ctx.guild]} Mans category channel not set"
            )

    @commands.guild_only()
    @commands.command()
    @checks.admin_or_permissions(manage_guild=True)
    async def unsetCategory(self, ctx: Context):
        """Unsets the category channel. Game channels will not be created if this is not set"""
        category = await self._category(ctx.guild)
        old_helper_role = await self._helper_role(ctx.guild)
        if old_helper_role and category:
            await category.set_permissions(old_helper_role, overwrite=None)
        await self._save_category(ctx.guild, None)
        await ctx.send("Done")

    @commands.guild_only()
    @commands.command()
    @checks.admin_or_permissions(manage_guild=True)
    async def setHelperRole(self, ctx: Context, helper_role: discord.Role):
        """Sets the 6 Mans helper role. Anyone with this role will be able to see all the game channels that are created"""
        await self._save_helper_role(ctx.guild, helper_role.id)
        category: discord.CategoryChannel = await self._category(ctx.guild)
        await category.set_permissions(
            helper_role, read_messages=True, manage_channels=True, connect=True
        )
        await ctx.send("Done")

    @commands.guild_only()
    @commands.command()
    @checks.admin_or_permissions(manage_guild=True)
    async def getHelperRole(self, ctx: Context):
        """Gets the role currently assigned as the 6 Mans helper role"""
        try:
            await ctx.send(
                f"{self.queueMaxSize[ctx.guild]} Mans helper role set to: {(await self._helper_role(ctx.guild)).name}"
            )
        except:
            await ctx.send(
                f":x: {self.queueMaxSize[ctx.guild]} mans helper role not set"
            )

    @commands.guild_only()
    @commands.command()
    @checks.admin_or_permissions(manage_guild=True)
    async def unsetHelperRole(self, ctx: Context):
        """Unsets the 6 Mans helper role."""
        category: discord.CategoryChannel = await self._category(ctx.guild)
        old_helper_role = await self._helper_role(ctx.guild)
        if old_helper_role and category:
            await category.set_permissions(old_helper_role, overwrite=None)
        await self._save_helper_role(ctx.guild, None)
        await ctx.send("Done")

    @commands.guild_only()
    @commands.command(aliases=["cag"])
    async def checkActiveGames(self, ctx: Context):
        if not await self.has_perms(ctx.author):
            return

        queueGames: dict[int, list[Game]] = {}
        for game in self.games[ctx.guild]:
            queueGames.setdefault(game.queue.id, []).append(game)

        embed = self.embed_active_games(ctx.guild, queueGames)
        await ctx.channel.send(embed=embed)

    # endregion
