import logging
from typing import TYPE_CHECKING

import discord
from discord.ext.commands import Context
from redbot.core import commands

from sixMans.constants import MINIMUM_GAME_TIME
from sixMans.embeds import BlueEmbed, ErrorEmbed, ExceptionErrorEmbed
from sixMans.enums import GameMode, GameState, Winner
from sixMans.game import Game
from sixMans.games.embeds import active_games_embed
from sixMans.games.lifecycle import GameLifecycle
from sixMans.views.cancel import CancelView, ForceCancelView
from sixMans.views.score import ForceResultView, ScoreReportView

log = logging.getLogger("red.sixMans.games")


class GameCommands(GameLifecycle):
    """Score reports, cancels, lobby info and helper game commands, mixed into the SixMans cog."""

    if TYPE_CHECKING:

        async def has_perms(self, member: discord.Member) -> bool: ...

    @commands.guild_only()
    @commands.command(aliases=["fts"])
    async def forceTeamSelection(self, ctx: Context, mode: GameMode, game_id: int | None = None):
        """Forces a popped queue to restart a specified team selection.

        Format: `[p]fts <team_selection> [game_id]`"""
        if not ctx.guild:
            return

        if not isinstance(ctx.author, discord.Member):
            return

        if not isinstance(ctx.channel, discord.TextChannel):
            return

        if not await self.has_perms(ctx.author):
            return

        log.debug(f"Game Mode: {mode}")
        log.debug(f"Game ID: {game_id}")
        if game_id:
            game = self.get_game_by_id(ctx.guild, game_id)
            if not game:
                return await ctx.send(embed=ErrorEmbed(description=f"No active game found with ID: **{game_id}**"))
        else:
            game = self.get_game_by_text_channel(ctx.channel)
            if not game:
                return await ctx.send(embed=ErrorEmbed(description="No active game in this channel."))

        if not game.textChannel:
            return await ctx.send(embed=ErrorEmbed(description=f"Game **{game.id}** no longer has a text channel."))

        await game.textChannel.send(f"Processing Forced Team Selection: {mode}")
        await game.process_team_selection_method(team_selection=mode, force=True)

    @commands.guild_only()
    @commands.max_concurrency(1, commands.BucketType.channel, wait=False)
    @commands.command(aliases=["fcg"])
    async def forceCancelGame(self, ctx: Context, gameId: int | None = None):
        """Cancel the current game. Can only be used in a game channel unless a gameId is given.
        The game will end with no points given to any of the players. The players with then be allowed to queue again.
        """
        if not ctx.guild:
            return

        if not isinstance(ctx.author, discord.Member):
            return

        if not isinstance(ctx.channel, discord.TextChannel):
            return

        if not await self.has_perms(ctx.author):
            return

        # game: Game | None = None
        if gameId:
            game = self.get_game_by_id(ctx.guild, gameId)
            if not game:
                return await ctx.send(embed=ErrorEmbed(description=f"No active game found with ID: **{gameId}**"))
        else:
            game = self.get_game_by_text_channel(ctx.channel)
            if not game:
                return await ctx.send(embed=ErrorEmbed(description="No active game in this channel."))

        cancel_view = ForceCancelView(author=ctx.author, game=game)
        await cancel_view.prompt()

        if await cancel_view.wait():
            return

        if not cancel_view.result:
            return

        live_game = self.revalidate_game(ctx.guild, game)
        if live_game is None:
            return await ctx.send(embed=ErrorEmbed(description="This game is no longer active."))
        game = live_game

        game.state = GameState.CANCELLED
        await self._remove_game(ctx.guild, game)

    @commands.guild_only()
    @commands.max_concurrency(1, commands.BucketType.channel, wait=False)
    @commands.command(aliases=["fr"])
    async def forceResult(self, ctx: Context):
        if not ctx.guild:
            return

        if not isinstance(ctx.author, discord.Member):
            return

        if not await self.has_perms(ctx.author):
            return

        game, six_mans_queue = await self.get_info(ctx)
        if game is None or six_mans_queue is None:
            return

        report_view = ForceResultView(author=ctx.author, game=game)
        await report_view.prompt()
        if await report_view.wait():
            return

        if report_view.cancelled:
            return

        if report_view.result == Winner.PENDING:
            return await ctx.send(embed=ErrorEmbed(description="Error reporting game result. Winner was not selected. Please reach out for support."))

        live_game = self.revalidate_game(ctx.guild, game)
        if live_game is None:
            return await ctx.send(embed=ErrorEmbed(description="This game is no longer active. The score was not recorded."))
        game = live_game

        await game.report_winner(report_view.result)
        await self._finish_game(ctx.guild, game, six_mans_queue, report_view.result)

    @commands.guild_only()
    @commands.max_concurrency(1, commands.BucketType.channel, wait=False)
    @commands.command(aliases=["cg"])
    async def cancelGame(self, ctx: Context):
        """Cancel the current game. Can only be used in a game channel.
        The game will end with no points given to any of the players. The players with then be allowed to queue again.
        """
        if not ctx.guild:
            return

        if not isinstance(ctx.channel, discord.TextChannel):
            return

        if not isinstance(ctx.author, discord.Member):
            return

        game = self.get_game_by_text_channel(ctx.channel)
        if game is None:
            return await ctx.send(embed=ErrorEmbed(description="This command can only be used in a private game channel."))

        cancel_view = CancelView(game=game)
        await cancel_view.prompt()
        if await cancel_view.wait():
            return

        if not cancel_view.result:
            return

        live_game = self.revalidate_game(ctx.guild, game)
        if live_game is None:
            return await ctx.send(embed=ErrorEmbed(description="This game is no longer active."))
        game = live_game

        game.state = GameState.CANCELLED
        await self._remove_game(ctx.guild, game)

    @commands.guild_only()
    @commands.max_concurrency(1, commands.BucketType.channel, wait=False)
    @commands.command(aliases=["sr", "reportScore"])
    async def scoreReport(self, ctx: Context):
        """Report which team won the series. Can only be used in a game channel.
        Only valid after 5 minutes have passed since the game started. Both captains pick the winner with buttons and must agree."""

        if not ctx.guild:
            return

        if not isinstance(ctx.channel, discord.TextChannel):
            return

        msg_created_at = ctx.message.created_at
        channel_created_at = ctx.channel.created_at
        game_seconds = int((msg_created_at - channel_created_at).total_seconds())

        if game_seconds < MINIMUM_GAME_TIME:
            await ctx.send(f":x: You can't report a game outcome until at least **5 minutes** have passed since the game was created.\nCurrent time that's passed = **{game_seconds // 60} minute(s)**")
            return

        game, six_mans_queue = await self.get_info(ctx)
        if game is None or six_mans_queue is None:
            return

        if game.winner != Winner.PENDING:
            return await ctx.send(
                embed=BlueEmbed(
                    title="Already Reported",
                    description=f"The game result has already been reported.\n\nWinner: {game.winner}",
                )
            )

        if ctx.author not in game.captains:
            return await ctx.send(embed=ErrorEmbed(description="Only game captains can report the score."))

        # Prompt for winner
        report_view = ScoreReportView(game=game)
        await report_view.prompt()
        if await report_view.wait():
            return

        if report_view.cancelled:
            return

        # The prompt above can block for two minutes. Re-fetch before scoring: the game may have
        # been cancelled, reported by a competing prompt, or replaced by a reload in that window.
        live_game = self.revalidate_game(ctx.guild, game)
        if live_game is None:
            return await ctx.send(embed=ErrorEmbed(description="This game is no longer active. The score was not recorded."))
        game = live_game

        if game.winner != Winner.PENDING:
            return await ctx.send(
                embed=BlueEmbed(
                    title="Already Reported",
                    description=f"The game result has already been reported.\n\nWinner: {game.winner}",
                )
            )

        winner = report_view.result
        log.debug(f"Game Winner: {winner}")

        # Something went wrong during reporting.
        if winner == Winner.PENDING:
            log.error(f"[{game.id}] Game winner was confirmed as PENDING.")
            helper_role = await self._helper_role(ctx.guild)
            if helper_role:
                desc = f"Score report vote did not succeed. If you believe this is an error, please ping {helper_role.mention}"
            else:
                desc = "Score report vote did not succeed. If you believe this is an error, please reach out for support."
            return await ctx.reply(embed=ErrorEmbed(description=desc))

        await game.report_winner(winner)
        await self._finish_game(ctx.guild, game, six_mans_queue, winner)

    @commands.guild_only()
    @commands.command(aliases=["smMove", "moveme"])
    async def moveMe(self, ctx: Context):
        if not ctx.guild:
            return

        player = ctx.author
        if not isinstance(player, discord.Member):
            return

        if not isinstance(ctx.channel, discord.TextChannel):
            return

        if not isinstance(ctx.message.channel, discord.TextChannel):
            return

        if ctx.message.channel.category != await self._category(ctx.guild):
            return False

        game = self.get_game_by_text_channel(ctx.channel)
        if not game:
            return await ctx.send(
                f"{player.mention}, you are not in a game or must run this command from the lobby channel.",
                allowed_mentions=discord.AllowedMentions(users=True),
            )

        if not player.voice:
            return await ctx.send(
                f"{player.mention}, you must be connected to a voice channel to be moved to your team channel.",
                allowed_mentions=discord.AllowedMentions(users=True),
            )

        try:
            if player in game.blue:
                await player.move_to(game.voiceChannels[0])
            else:
                await player.move_to(game.voiceChannels[1])
        except (
            discord.Forbidden,
            discord.HTTPException,
            discord.NotFound,
            TypeError,
        ) as exc:
            await ctx.send(embed=ExceptionErrorEmbed(exc_message=str(exc)))

    @commands.guild_only()
    @commands.command(aliases=["li", "gameInfo", "gi"])
    async def lobbyInfo(self, ctx: Context):
        """Gets lobby info for the series that you are involved in"""
        if not ctx.guild:
            return

        if not isinstance(ctx.channel, discord.TextChannel):
            return

        if ctx.channel.category != await self._category(ctx.guild):
            return False

        game = self.get_game_by_text_channel(ctx.channel)
        if game:
            await game.post_lobby_info()

    @commands.guild_only()
    @commands.command(aliases=["moreinfo", "mi"])
    async def moreInfo(self, ctx: Context):
        """Provides more in-depth information regarding the Six Mans series"""
        if not ctx.guild:
            return

        if not isinstance(ctx.channel, discord.TextChannel):
            return

        game = self.get_game_by_text_channel(ctx.channel)
        if game is None:
            return await ctx.send(embed=ErrorEmbed(description="Not a valid game channel."))
        await game.post_more_lobby_info()

    @commands.guild_only()
    @commands.command(aliases=["cag"])
    async def checkActiveGames(self, ctx: Context):
        if not ctx.guild:
            return

        if not isinstance(ctx.author, discord.Member):
            return

        if not await self.has_perms(ctx.author):
            return

        queueGames: dict[int, list[Game]] = {}
        for game in self.games[ctx.guild]:
            queueGames.setdefault(game.queue.id, []).append(game)

        embed = active_games_embed(self.queueMaxSize[ctx.guild], self.queues[ctx.guild], queueGames)
        await ctx.channel.send(embed=embed)
