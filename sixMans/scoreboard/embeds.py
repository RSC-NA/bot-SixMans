import logging

import discord
from discord.ext.commands import Context
from redbot.core import commands

from sixMans.types import PlayerStats

log = logging.getLogger("red.sixMans.scoreboard")


async def leaderboard_embed(ctx: Context, sorted_players: list[tuple[str, PlayerStats]], queue_name: str, team_size: int, games_played: int, lb_format: str) -> discord.Embed:
    embed = discord.Embed(
        title=f"{queue_name} {team_size} Mans {lb_format} Leaderboard",
        color=discord.Colour.blue(),
    )
    embed.add_field(name="Games Played", value=f"{games_played}\n", inline=True)
    embed.add_field(name="Unique Players", value=f"{len(sorted_players)}\n", inline=True)
    embed.add_field(name="⠀", value="⠀", inline=True)  # Blank field added to push the Player and Stats fields to a new line

    playerStrings = []
    statStrings = []
    for idx, player in enumerate(sorted_players):
        try:
            member: discord.Member = await commands.MemberConverter().convert(ctx, player[0])
        except (
            commands.MemberNotFound,
            commands.CommandError,
        ):
            log.warning(f":x: Can't find player with id: {player[0]}")
            continue

        player_info = player[1]
        playerStrings.append(f"`{idx + 1}` **{member.display_name:25s}:**")
        try:
            player_wins = player_info["Wins"]
            player_gp = player_info["GamesPlayed"]
            player_wp = round(player_wins / player_gp * 100, 1)
            player_wp = f"{player_wp}%" if player_wp != 100 else "100%"
        except ZeroDivisionError:
            player_wp = "N/A"

        statStrings.append(f"Points: `{player_info['Points']:4d}`  Wins: `{player_wins:3d}`  GP: `{player_gp:3d}` WP: `{player_wp:5s}`")

        if idx + 1 > 10:
            break

    author = ctx.author
    try:
        author_index = [y[0] for y in sorted_players].index(f"{author.id}")
        if author_index is not None and author_index > 9:
            author_info = sorted_players[author_index][1]
            playerStrings.append(f"\n`{author_index + 1}` **{author.display_name:25s}:**")
            try:
                author_wins = author_info["Wins"]
                author_gp = author_info["GamesPlayed"]
                author_wp = round(author_wins / author_gp * 100, 1)
                author_wp = f"{author_wp}%" if author_wp != 100 else "100%"
            except ZeroDivisionError:
                author_wp = "N/A"

            statStrings.append(f"\nPoints: `{author_info['Points']:4d}`  Wins: `{author_wins:3d}`  GP: `{author_gp:3d}` WP: `{author_wp:5s}`")
    except Exception:
        pass

    embed.add_field(name="Player", value="\n".join(playerStrings), inline=True)
    embed.add_field(name="Stats", value="\n".join(statStrings), inline=True)
    return embed


def rank_embed(player: discord.Member, sorted_players: list[tuple[str, PlayerStats]], queue_name: str, queue_max_size: int, rank_format: str) -> discord.Embed:
    try:
        num_players = len(sorted_players)
        points_index = [y[0] for y in sorted_players].index(f"{player.id}")
        player_info = sorted_players[points_index][1]
        points, wins, games_played = (
            player_info["Points"],
            player_info["Wins"],
            player_info["GamesPlayed"],
        )
        wins_index = [
            y[0]
            for y in sorted(
                sorted_players,
                key=lambda x: x[1]["Wins"],
                reverse=True,
            )
        ].index(f"{player.id}")
        games_played_index = [
            y[0]
            for y in sorted(
                sorted_players,
                key=lambda x: x[1]["GamesPlayed"],
                reverse=True,
            )
        ].index(f"{player.id}")
        embed = discord.Embed(
            title=f"{player.display_name} {rank_format} Rank",
            description=f"Player rank data for {queue_name} queue ({queue_max_size} mans)",
            color=discord.Colour.blue(),
        )
        embed.set_thumbnail(url=player.display_avatar.url)
        embed.add_field(
            name="Category",
            value=f"Points: `{points_index + 1}/{num_players}`\nWins: `{wins_index + 1}/{num_players}`\nGames Played: `{games_played_index + 1}/{num_players}`",
            inline=True,
        )
        embed.add_field(
            name="Value",
            value=f"`{points:4d}`\n`{wins:4d}`\n`{games_played:4d}`",
            inline=True,
        )
    except ValueError:
        embed = discord.Embed(
            title=f"{player.display_name} {queue_name} {queue_max_size} Mans {rank_format} Rank",
            description=f"No stats yet to rank {player.mention}",
            color=discord.Colour.red(),
        )
        embed.set_thumbnail(url=player.display_avatar.url)
    return embed
