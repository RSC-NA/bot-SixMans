import asyncio
import datetime
import logging
import random
from sys import exc_info, maxsize
from typing import Dict, List

import discord
from discord.ext.commands import Context
from redbot.core import Config, checks, commands, app_commands
from redbot.core.utils.menus import start_adding_reactions
from redbot.core.utils.predicates import ReactionPredicate

from sixMans.sixMansSplit.functions import *
from sixMans.sixMansSplit.getsetCommands import GetSetCommands
from sixMans.sixMansSplit.leaderboardCommands import LeaderboardCommands
from sixMans.sixMansSplit.listeners import Listerners
from sixMans.sixMansSplit.playerCommads import PlayerCommands
from sixMans.sixMansSplit.rankCommands import RankCommands


from sixMans.game import Game
from sixMans.queue import SixMansQueue
from sixMans.strings import Strings
from sixMans.views import GameMode, GameState


# the starting cog class
# Contains all of the admin commands for the sixmans cog
class SixMans(
    GetSetCommands, LeaderboardCommands, Listerners, PlayerCommands, RankCommands
):
    def cog_unload(self):
        """Clean up when cog shuts down."""
        for player, tasks in self.timeout_tasks.items():
            for queue, timeout_task in tasks.items():
                timeout_task.cancel()

    # region commmands

    # region admin commands
    @commands.guild_only()
    @commands.command()
    @checks.admin_or_permissions(manage_guild=True)
    async def clearSixMansData(self, ctx: Context):
        """
        Clears all the Six Mans data for the guild.

        Parameters:
        - ctx (Context): The context object representing the invocation context.

        Returns:
        None
        """
        msg = await ctx.send(
            f"{ctx.author.mention} Please verify that you wish to clear **all** of the {self.queueMaxSize[ctx.guild]} Mans data for the guild."
        )
        start_adding_reactions(msg, ReactionPredicate.YES_OR_NO_EMOJIS)

        pred = ReactionPredicate.yes_or_no(msg, ctx.author)
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
        await self._pre_load_data()
        await ctx.send("Done")

    @commands.guild_only()
    @commands.command()
    @checks.admin_or_permissions(manage_guild=True)
    async def addNewQueue(
        self, ctx: Context, name, points_per_play: int, points_per_win: int, *channels
    ):
        """
        Adds a new queue with the specified parameters.

        Parameters:
        - ctx (Context): The context of the command.
        - name (str): The name of the queue.
        - points_per_play (int): The number of points awarded per play.
        - points_per_win (int): The number of points awarded per win.
        - channels (str): The channels where the queue will be active.

        Returns:
        - None

        Raises:
        - None
        """
        queue_channels = []
        for channel in channels:
            queue_channels.append(
                await commands.TextChannelConverter().convert(ctx, channel)
            )
        for queue in self.queues[ctx.guild]:
            if queue.name == name:
                await ctx.send(
                    f":x: There is already a queue set up with the name: {name}"
                )
                return
            for channel in queue_channels:
                if channel in queue.channels:
                    await ctx.send(
                        f":x: {channel.mention} is already being used for queue: {queue.name}"
                    )
                    return
        queue_max_size = await self._get_queue_max_size(ctx.guild)
        points = {
            Strings.PP_PLAY_KEY: points_per_play,
            Strings.PP_WIN_KEY: points_per_win,
        }
        team_selection = await self._team_selection(ctx.guild)
        six_mans_queue = SixMansQueue(
            name,
            ctx.guild,
            queue_channels,
            points,
            {},
            0,
            queue_max_size,
            teamSelection=team_selection,
            category=await self._category(ctx.guild),
        )
        self.queues[ctx.guild].append(six_mans_queue)
        await self._save_queues(ctx.guild, self.queues[ctx.guild])
        await ctx.send("Done")

    @commands.guild_only()
    @commands.command()
    @checks.admin_or_permissions(manage_guild=True)
    async def editQueue(
        self,
        ctx: Context,
        current_name,
        new_name,
        points_per_play: int,
        points_per_win: int,
        *channels,
    ):
        """
        Edits a queue in the six mans system.

        Parameters:
        - ctx (Context): The context of the command.
        - current_name (str): The current name of the queue to be edited.
        - new_name (str): The new name for the queue.
        - points_per_play (int): The points awarded per play.
        - points_per_win (int): The points awarded per win.
        - *channels (str): Variable number of channel names to be added to the queue.

        Returns:
        - None

        Raises:
        - None
        """
        six_mans_queue = None
        for queue in self.queues[ctx.guild]:
            if queue.name == current_name:
                six_mans_queue = queue
                break

        if six_mans_queue is None:
            await ctx.send(f":x: No queue found with name: {current_name}")
            return

        queue_channels = []
        for channel in channels:
            queue_channels.append(
                await commands.TextChannelConverter().convert(ctx, channel)
            )
        for queue in self.queues[ctx.guild]:
            if queue.name != current_name:
                if queue.name == new_name:
                    await ctx.send(
                        f":x: There is already a queue set up with the name: {new_name}"
                    )
                    return

                for channel in queue_channels:
                    if channel in queue.channels:
                        await ctx.send(
                            f":x: {channel.mention} is already being used for queue: {queue.name}"
                        )
                        return

        six_mans_queue.name = new_name
        six_mans_queue.points = {
            Strings.PP_PLAY_KEY: points_per_play,
            Strings.PP_WIN_KEY: points_per_win,
        }
        six_mans_queue.channels = queue_channels
        await self._save_queues(ctx.guild, self.queues[ctx.guild])
        await ctx.send("Done")

    @commands.guild_only()
    @commands.command(aliases=["setQTS", "setQueueTeamSelection", "sqts"])
    @checks.admin_or_permissions()
    async def setQueueTS(self, ctx: Context, queue_name, *, team_selection):
        """Sets the team selection mode for a specific queue.

        Parameters:
        - ctx (Context): The context of the command.
        - queue_name (str): The name of the queue to set the team selection mode for.
        - team_selection (str): The team selection mode to set.

        Returns:
        - None

        Raises:
        - None

        """
        if not await self.has_perms(ctx.author):
            return

        invalid_embed = discord.Embed(title="Error", color=discord.Color.red())

        six_mans_queue = None
        for queue in self.queues[ctx.guild]:
            if queue.name == queue_name:
                six_mans_queue = queue
                break

        if six_mans_queue is None:
            invalid_embed.description = f"No queue found with name: **{queue_name}**"
            await ctx.send(embed=invalid_embed)
            return

        if six_mans_queue.maxSize == 2:
            invalid_embed.description = (
                "Queue with max size of 2 cannot change team selection method."
            )
            await ctx.send(embed=invalid_embed)
            return
        # Set team selection method
        try:
            await six_mans_queue.set_team_selection(team_selection)
            await self._save_queues(ctx.guild, self.queues[ctx.guild])
        except ValueError:
            invalid_embed.description = (
                f"**{team_selection}** is an invalid team selection mode"
            )
            await ctx.send(embed=invalid_embed)

    @commands.guild_only()
    @commands.command(aliases=["getQTS", "getQueueTeamSelection", "gqts"])
    @checks.admin_or_permissions()
    async def getQueueTS(self, ctx: Context, queue_name):
        """Sets the team selection mode for a specific queue

        Parameters:
        - ctx (Context): The context of the command
        - queue_name (str): The name of the queue

        Returns:
        - None

        Raises:
        - None
        """
        if not await self.has_perms(ctx.author):
            return

        six_mans_queue = None
        for queue in self.queues[ctx.guild]:
            if queue.name == queue_name:
                six_mans_queue = queue
                break

        if six_mans_queue is None:
            await ctx.send(f":x: No queue found with name: {queue_name}")
            return

        await ctx.send(
            f"{six_mans_queue.name} team selection is currently set to **{six_mans_queue.teamSelection}**."
        )

    @commands.guild_only()
    @commands.command(aliases=["setQTimeout", "setQTO", "sqto"])
    @checks.admin_or_permissions()
    async def setQueueTimeout(self, ctx: Context, minutes: int):
        """Sets the player timeout in minutes for queues in the guild (Default: 240) ."""
        seconds = minutes * 60
        await self._save_player_timeout(ctx.guild, seconds)
        self.player_timeout_time[ctx.guild] = seconds
        s_if_plural = "" if minutes == 1 else "s"
        await ctx.send(
            f":white_check_mark: Players in Six Mans Queues will now be timed out after **{minutes} minute{s_if_plural}**."
        )

    @commands.guild_only()
    @commands.command(aliases=["getQTO", "gqto", "qto"])
    async def getQueueTimeout(self, ctx: Context):
        """Gets the player timeout in minutes for queues in the guild (Default: 240)."""
        seconds = await self._player_timeout(ctx.guild)
        minutes = seconds // 60
        s_if_plural = "" if minutes == 1 else "s"
        await ctx.send(
            f"Players in Six Mans Queues are timed out after **{minutes} minute{s_if_plural}**."
        )

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
        """Sets the default queue max size for the guild. This will not change the queue max size for any queues. (Default: 6)"""
        if max_size % 2 == 1:
            return await ctx.send(
                ":x: Queues sizes must be configured for an even number of players."
            )

        await self._save_queue_max_size(ctx.guild, max_size)

        if max_size == 2:
            await self._save_team_selection(ctx.guild, GameMode.RANDOM)

        await ctx.send("Done")

    @commands.guild_only()
    @commands.command(aliases=["setQueueSize", "setQMaxSize", "setQMS", "sqms"])
    @checks.admin_or_permissions()
    async def setQueueMaxSize(self, ctx: Context, queue_name, *, max_size: int):
        """Sets the max size for a queue (Default: 6)"""
        six_mans_queue = None
        for queue in self.queues[ctx.guild]:
            if queue.name == queue_name:
                six_mans_queue = queue
                break

        if six_mans_queue is None:
            return await ctx.send(
                ":x: No queue found with name: {0}".format(queue_name)
            )

        if max_size % 2 == 1:
            return await ctx.send(
                f":x: Queues sizes must be configured for an even number of players."
            )

        six_mans_queue.maxSize = max_size

        if max_size == 2:
            await six_mans_queue.set_team_selection(GameMode.RANDOM)

        await self._save_queues(ctx.guild, self.queues[ctx.guild])
        await ctx.send("Done")

    @commands.guild_only()
    @commands.command(aliases=["getDQMaxSize", "getDQMS", "gdqms", "dqms"])
    @checks.admin_or_permissions()
    async def getDefaultQueueMaxSize(self, ctx: Context):
        """Gets the max size for all queues in the guild. (Default: 6)"""
        guild_queue_size = await self._get_queue_max_size(ctx.guild)
        await ctx.send(f"Default Queue Size: {guild_queue_size}")

    @commands.guild_only()
    @commands.command(aliases=["getQMaxSize", "getQMS", "gqms", "qms"])
    @checks.admin_or_permissions()
    async def getQueueMaxSize(self, ctx: Context, queue_name):
        """Gets the max size for a specific queue"""
        six_mans_queue = None
        for queue in self.queues[ctx.guild]:
            if queue.name == queue_name:
                six_mans_queue = queue
                break

        if six_mans_queue is None:
            return await ctx.send(
                ":x: No queue found with name: {0}".format(queue_name)
            )

        await ctx.send(f"{six_mans_queue.name} Queue Size: {six_mans_queue.maxSize}")

    @commands.guild_only()
    @commands.command()
    @checks.admin_or_permissions(manage_guild=True)
    async def removeQueue(self, ctx: Context, *, queue_name):
        for queue in self.queues[ctx.guild]:
            if queue.name == queue_name:
                self.queues[ctx.guild].remove(queue)
                await self._save_queues(ctx.guild, self.queues[ctx.guild])
                await ctx.send("Done")
                return
        await ctx.send(f":x: No queue set up with name: {queue_name}")

    @commands.guild_only()
    @commands.command(aliases=["qm", "queueAll", "qa", "forceQueue", "fq"])
    @checks.admin_or_permissions(manage_guild=True)
    async def queueMultiple(self, ctx: Context, *members: discord.Member):
        """Mass queueing for testing purposes"""
        six_mans_queue = self._get_queue_by_text_channel(ctx.channel)
        for member in members:
            if member in six_mans_queue.queue.queue:
                await ctx.send(f"{member.display_name} is already in queue.")
                break
            await self._add_to_queue(member, six_mans_queue)
        if six_mans_queue._queue_full():
            await self._pop_queue(ctx, six_mans_queue)

    @commands.guild_only()
    @commands.command(aliases=["kq", "fdq"])
    async def kickQueue(self, ctx: Context, player: discord.Member):
        """Remove someone else from the queue"""
        if not await self.has_perms(ctx.author):
            return

        six_mans_queue = self._get_queue_by_text_channel(ctx.channel)
        if player in six_mans_queue.queue:
            await self._remove_from_queue(player, six_mans_queue)
        else:
            await ctx.send(f"{player.display_name} is not in queue.")

    @commands.guild_only()
    @commands.command(aliases=["clrq"])
    async def clearQueue(self, ctx: Context):
        """Clear the queue"""
        if not await self.has_perms(ctx.author):
            return

        six_mans_queue = self._get_queue_by_text_channel(ctx.channel)
        try:
            for player in six_mans_queue.queue.queue:
                log.debug(f"Removing player: {player}")
                await self._remove_from_queue(player, six_mans_queue)
            await ctx.send("Queue cleared.")
        except Exception as exc:
            log.debug(f"Error clearing queue: {exc}")
            await ctx.send("Error clearing queue.")

    @commands.guild_only()
    @commands.command(aliases=["eq"])
    async def enableQueues(self, ctx: Context):
        """Enable queueing for the guild."""
        if not await self.has_perms(ctx.author):
            return

        await self._save_queues_enabled(ctx.guild, True)
        self.queues_enabled[ctx.guild] = True

        await ctx.send("Queueing has been enabled.")

    @commands.guild_only()
    @commands.command(aliases=["stopQueue", "sq"])
    async def disableQueues(self, ctx: Context):
        """Disable queueing for the guild."""
        if not await self.has_perms(ctx.author):
            return

        await self._save_queues_enabled(ctx.guild, False)
        self.queues_enabled[ctx.guild] = False

        await ctx.send("Queueing has been disabled.")

    # team selection
    @commands.guild_only()
    @commands.command(aliases=["fts"])
    async def forceTeamSelection(self, ctx, *, args):
        """Forces a popped queue to restart a specified team selection.

        Format: `[p]fts <team_selection> [game_id]`"""
        if not await self.has_perms(ctx.author):
            return

        if len(args) == 1:
            game_id = None
            team_selection = args
        elif len(args) > 1:
            args = args.split()
            try:
                game_id = int(args[-1])
                team_selection = " ".join(args[0:-1])
            except:
                game_id = None
                team_selection = " ".join(args)

        game: Game = None
        if game_id:
            for active_game in self.games[ctx.guild]:
                if active_game.id == game_id:
                    game = active_game
        else:
            game = self._get_game_by_text_channel(ctx.channel)

        if not game:
            await ctx.send(":x: Game not found.")
            return

        valid_ts = self.is_valid_ts(team_selection)
        if not valid_ts:
            return await ctx.send(
                f":x: **{team_selection}** is not a valid team selection method."
            )

        await game.textChannel.send(f"Processing Forced Team Selection: {valid_ts}")
        game.teamSelection = valid_ts
        await game.process_team_selection_method(team_selection=valid_ts)

    @commands.guild_only()
    @commands.command(aliases=["fcg"])
    async def forceCancelGame(self, ctx: Context, gameId: int = None):
        """Cancel the current game. Can only be used in a game channel unless a gameId is given.
        The game will end with no points given to any of the players. The players with then be allowed to queue again.
        """
        if not await self.has_perms(ctx.author):
            return

        game = None
        if gameId is None:
            game = self._get_game_by_text_channel(ctx.channel)
            if game is None:
                await ctx.send(
                    f":x: This command can only be used in a {self.queueMaxSize[ctx.guild]} Mans game channel."
                )
                return
        else:
            pass

        if not game:
            await ctx.send(f"No game found with id: {gameId}")
            return

        msg = await ctx.send(
            f"{ctx.author.mention} Please verify that you want to cancel this game."
        )
        start_adding_reactions(msg, ReactionPredicate.YES_OR_NO_EMOJIS)

        game.scoreReported = True
        pred = ReactionPredicate.yes_or_no(msg, ctx.author)
        try:
            await ctx.bot.wait_for("reaction_add", check=pred, timeout=VERIFY_TIMEOUT)
            if pred.result is True:
                await ctx.send("Done.")
                try:
                    # If the text channel has been deleted this will throw an error and we'll instead want to send the message to wherever the command was used
                    await game.textChannel.send(
                        f"Game canceled by {ctx.author.mention}. Feel free to queue again in an appropriate channel.\n**This game's channels will be deleted in {CHANNEL_SLEEP_TIME} seconds**"
                    )
                except:
                    await ctx.send(
                        f"Game canceled by {ctx.author.mention}. Feel free to queue again in an appropriate channel.\n**This game's channels will be deleted in {CHANNEL_SLEEP_TIME} seconds**"
                    )
                await self._remove_game(ctx.guild, game)
            else:
                await ctx.send(
                    f":x: Cancel not verified. To cancel the game you will need to use the `{ctx.prefix}cg` command again."
                )
        except asyncio.TimeoutError:
            await ctx.send(
                f":x: Cancel not verified in time. To cancel the game you will need to use the `{ctx.prefix}cg` command again."
            )

    @commands.guild_only()
    @commands.command(aliases=["fr"])
    async def forceResult(self, ctx: Context, winning_team):
        if not await self.has_perms(ctx.author):
            return

        if winning_team.lower() != "blue" and winning_team.lower() != "orange":
            await ctx.send(
                f":x: {winning_team} is an invalid input for `winning_team`. Must be either `Blue` or `Orange`"
            )
            return

        game, six_mans_queue = await self._get_info(ctx)
        if game is None or six_mans_queue is None:
            return

        msg = await ctx.send(
            f"{ctx.author.mention} Please verify that the **{winning_team}** team won the series."
        )
        start_adding_reactions(msg, ReactionPredicate.YES_OR_NO_EMOJIS)

        game.scoreReported = True
        pred = ReactionPredicate.yes_or_no(msg, ctx.author)
        await ctx.bot.wait_for("reaction_add", check=pred)
        if pred.result is True:
            pass
        else:
            game.scoreReported = False
            await ctx.send(
                f":x: Score report not verified. To report the score you will need to use the `{ctx.prefix}sr` command again."
            )
            return

        await game.report_winner(winning_team)
        await ctx.send(
            f"Done. Thanks for playing!\n**This channel and the team voice channels will be deleted in {CHANNEL_SLEEP_TIME} seconds**"
        )
        await self._finish_game(ctx.guild, game, six_mans_queue, winning_team)

    # endregion

    # endregion
