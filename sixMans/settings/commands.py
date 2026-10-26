from typing import TYPE_CHECKING

import discord
from discord.ext.commands import Context
from redbot.core import checks, commands
from redbot.core.utils.menus import start_adding_reactions
from redbot.core.utils.predicates import ReactionPredicate

from sixMans.embeds import BlueEmbed, ErrorEmbed
from sixMans.enums import GameMode
from sixMans.settings.config import GuildSettings

if TYPE_CHECKING:
    from sixMans.queue import SixMansQueue


class SettingsCommands(GuildSettings):
    """Guild-wide settings and data management commands, mixed into the SixMans cog."""

    if TYPE_CHECKING:
        queues: dict[discord.Guild, list[SixMansQueue]]
        player_timeout_time: dict[discord.Guild, int]

        async def _save_queues(self, guild: discord.Guild, queues: list[SixMansQueue]): ...
        async def _clear_all_data(self, guild: discord.Guild): ...
        async def _load_guild_data(self): ...
        async def _load_scoreboard(self): ...
        async def _load_queues(self): ...
        async def _load_games(self): ...

    @commands.guild_only()
    @commands.command()
    @checks.admin_or_permissions(manage_guild=True)
    async def clearSixMansData(self, ctx: Context):
        if not ctx.guild:
            return

        msg = await ctx.send(f"{ctx.author.mention} Please verify that you wish to clear **all** of the {self.queueMaxSize[ctx.guild]} Mans data for the guild.")
        start_adding_reactions(msg, ReactionPredicate.YES_OR_NO_EMOJIS)

        pred = ReactionPredicate.yes_or_no(msg, ctx.author)  # ty: ignore[invalid-argument-type]  # Member.bot is a read-only property; discord.abc.User declares it writable
        await ctx.bot.wait_for("reaction_add", check=pred)
        if pred.result:
            # await self.config.clear_all_guilds()
            await self._clear_all_data(ctx.guild)
            await ctx.send("Done")
        else:
            await ctx.send(":x: Data **not** cleared.")

    @commands.guild_only()
    @commands.command()
    @checks.admin_or_permissions(manage_guild=True)
    async def preLoadData(self, ctx: Context):
        """Reloads all data for the 6mans cog"""
        await self._load_guild_data()
        await self._load_scoreboard()
        await self._load_queues()
        await self._load_games()
        await ctx.send("Done")

    @commands.guild_only()
    @commands.command(
        aliases=[
            "setDefaultQueueSize",
            "setDefaultQMaxSize",
            "setDefaultQMS",
            "setDQMS",
            "sdqms",
        ]
    )
    @checks.admin_or_permissions()
    async def setDefaultQueueMaxSize(self, ctx: Context, max_size: int):
        """
        Sets the default queue max size for the guild.

        This will not change the queue max size for any queues. (Default: 6)
        """
        if not ctx.guild:
            return

        if max_size <= 2:
            return await ctx.send(embed=ErrorEmbed(description="Queues sizes must be 2 or more players."))

        if max_size % 2 == 1:
            return await ctx.send(embed=ErrorEmbed(description="Queues sizes must be configured for an even number of players."))

        await self._save_queue_max_size(ctx.guild, max_size)

        if max_size == 2:
            await self._save_team_selection(ctx.guild, GameMode.RANDOM)

        await ctx.send("Done")

    @commands.guild_only()
    @commands.command(aliases=["getDQMaxSize", "getDQMS", "gdqms", "dqms"])
    @checks.admin_or_permissions()
    async def getDefaultQueueMaxSize(self, ctx: Context):
        """Gets the max size for all queues in the guild. (Default: 6)"""
        if not ctx.guild:
            return

        guild_queue_size = await self._get_queue_max_size(ctx.guild)
        await ctx.send(
            embed=BlueEmbed(
                title="Default Queue Size",
                description=f"Current default queue size: **{guild_queue_size}**",
            )
        )

    @commands.guild_only()
    @commands.command(aliases=["setTeamSelection"])
    @checks.admin_or_permissions(manage_guild=True)
    async def setDefaultTeamSelection(self, ctx: Context, team_selection_method):
        """
        Set method for Six Mans team selection (Default: Vote)

        Valid team selection methods options:
        - **Random**: selects random teams
        - **Captains**: selects a captain for each team
        - **Vote**: players vote for team selection method after queue pops
        - **Balanced**: creates balanced teams from all participating players
        """
        # TODO: Support Captains [captains random, captains shuffle], Balanced
        if not ctx.guild:
            return

        if await self._get_queue_max_size(ctx.guild) == 2:
            return await ctx.send(":x: You may not change team selection method when default queue max size is 2.")

        try:
            ts = GameMode(team_selection_method)
            await self._save_team_selection(ctx.guild, ts)
            await ctx.send("Done.")
        except ValueError:
            return await ctx.send(f"**{team_selection_method}** is not a valid method of team selection.")

    @commands.guild_only()
    @commands.command(aliases=["getTeamSelection"])
    @checks.admin_or_permissions(manage_guild=True)
    async def getDefaultTeamSelection(self, ctx: Context):
        """Get method for Six Mans team selection (Default: Random)"""
        if not ctx.guild:
            return

        team_selection = await self._team_selection(ctx.guild)
        await ctx.send(f"Six Mans team selection is currently set to **{team_selection}**.")

    @commands.guild_only()
    @commands.command(aliases=["setQTimeout", "setQTO", "sqto"])
    @checks.admin_or_permissions()
    async def setQueueTimeout(self, ctx: Context, minutes: int):
        """Sets the player timeout in seconds for queues in the guild (Default: 30m) ."""
        if not ctx.guild:
            return

        seconds = minutes * 60
        await self._save_player_timeout(ctx.guild, seconds)
        self.player_timeout_time[ctx.guild] = seconds
        s_if_plural = "" if minutes == 1 else "s"
        await ctx.send(
            embed=BlueEmbed(
                title="Queue Timeout",
                description=f"Players in Six Mans Queues will now be timed out after **{minutes} minute{s_if_plural}**.",
            )
        )

    @commands.guild_only()
    @commands.command(aliases=["getQTO", "gqto", "qto"])
    async def getQueueTimeout(self, ctx: Context):
        """Gets the player timeout in minutes for queues in the guild (Default: 240)."""
        if not ctx.guild:
            return

        seconds = await self._player_timeout(ctx.guild)
        minutes = seconds // 60
        s_if_plural = "" if minutes == 1 else "s"
        await ctx.send(
            embed=BlueEmbed(
                title="Queue Timeout",
                description=f"Players in Six Mans Queues are timed out after **{minutes} minute{s_if_plural}**.",
            )
        )

    @commands.guild_only()
    @commands.command()
    @checks.admin_or_permissions(manage_guild=True)
    async def toggleAutoMove(self, ctx: Context):
        """Toggle whether or not bot moves members to their assigned team voice channel"""
        if not ctx.guild:
            return

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
        if not ctx.guild:
            return

        react_to_vote = not await self._is_react_to_vote(ctx.guild)
        await self._save_react_to_vote(ctx.guild, react_to_vote)

        action = "reactions" if react_to_vote else "commands"
        message = f"Members of popped {self.queueMaxSize[ctx.guild]} Mans queues will vote for team reactions with **{action}**."
        await ctx.send(message)

    @commands.guild_only()
    @commands.command()
    @checks.admin_or_permissions(manage_guild=True)
    async def setCategory(self, ctx: Context, category_channel: discord.CategoryChannel):
        """Sets the category channel where all game channels will be created under"""
        if not ctx.guild:
            return

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
        if not ctx.guild:
            return

        category = await self._category(ctx.guild)
        category_fmt = category.mention if category else "None"

        await ctx.send(f"{self.queueMaxSize[ctx.guild]} Mans category channel set to: {category_fmt}")

    @commands.guild_only()
    @commands.command()
    @checks.admin_or_permissions(manage_guild=True)
    async def unsetCategory(self, ctx: Context):
        """Unsets the category channel. Game channels will not be created if this is not set"""
        if not ctx.guild:
            return

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
        if not ctx.guild:
            return

        await self._save_helper_role(ctx.guild, helper_role.id)
        category = await self._category(ctx.guild)

        if not category:
            await ctx.reply("Six mans category channel is not configured.")
            return

        await category.set_permissions(helper_role, read_messages=True, manage_channels=True, connect=True)
        await ctx.send("Done")

    @commands.guild_only()
    @commands.command()
    @checks.admin_or_permissions(manage_guild=True)
    async def getHelperRole(self, ctx: Context):
        """Gets the role currently assigned as the 6 Mans helper role"""
        if not ctx.guild:
            return

        try:
            await ctx.send(f"{self.queueMaxSize[ctx.guild]} Mans helper role set to: {(await self._helper_role(ctx.guild)).name}")
        except AttributeError:
            await ctx.send(f":x: {self.queueMaxSize[ctx.guild]} mans helper role not set")

    @commands.guild_only()
    @commands.command()
    @checks.admin_or_permissions(manage_guild=True)
    async def unsetHelperRole(self, ctx: Context):
        """Unsets the 6 Mans helper role."""
        if not ctx.guild:
            return

        category = await self._category(ctx.guild)
        old_helper_role = await self._helper_role(ctx.guild)
        if old_helper_role and category:
            await category.set_permissions(old_helper_role, overwrite=None)
        await self._save_helper_role(ctx.guild, None)
        await ctx.send("Done")

    @commands.guild_only()
    @commands.command(aliases=["setQLobby", "setQVC"])
    @checks.admin_or_permissions(manage_guild=True)
    async def setQueueLobby(self, ctx: Context, lobby_voice: discord.VoiceChannel):
        # TODO: Consider having the queues save the Queue Lobby VC
        if not ctx.guild:
            return

        for queue in self.queues[ctx.guild]:
            queue.lobby_vc = lobby_voice
        await self._save_q_lobby_vc(ctx.guild, lobby_voice.id)
        await self._save_queues(ctx.guild, self.queues[ctx.guild])
        await ctx.send("Done")

    @commands.guild_only()
    @commands.command(aliases=["unsetQueueLobby", "unsetQLobby", "clearQLobby"])
    @checks.admin_or_permissions(manage_guild=True)
    async def clearQueueLobby(self, ctx: Context):
        if not ctx.guild:
            return

        await self._save_q_lobby_vc(ctx.guild, None)
        await ctx.send("Done")
