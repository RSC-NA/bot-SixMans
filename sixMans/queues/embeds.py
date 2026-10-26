import discord

from sixMans.queue import SixMansQueue
from sixMans.strings import Strings


def player_added_embed(player: discord.Member, six_mans_queue: SixMansQueue) -> discord.Embed:
    player_list = format_player_list(six_mans_queue)
    embed = discord.Embed(color=discord.Colour.green())
    player_icon = player.display_avatar.url
    embed.set_author(
        name=f"{player.display_name} added to the {six_mans_queue.name} queue. ({six_mans_queue.queue.qsize()}/{six_mans_queue.maxSize})",
        icon_url=player_icon,
    )
    embed.add_field(name="Players in Queue", value=player_list, inline=False)
    return embed


def player_removed_embed(player: discord.Member, six_mans_queue: SixMansQueue) -> discord.Embed:
    player_list = format_player_list(six_mans_queue)
    embed = discord.Embed(color=discord.Colour.red())
    embed.set_author(
        name=f"{player.display_name} removed from the {six_mans_queue.name} queue. ({six_mans_queue.queue.qsize()}/{six_mans_queue.maxSize})",
        icon_url=player.display_avatar.url,
    )
    embed.add_field(name="Players in Queue", value=player_list, inline=False)
    return embed


def queue_info_embed(queue: SixMansQueue, games_played: int, unique_players: int, default_lobby_vc=None) -> discord.Embed:
    embed = discord.Embed(
        title=f"{queue.name} {queue.maxSize} Mans Info",
        color=discord.Colour.blue(),
    )
    embed.add_field(name="Team Selection", value=queue.teamSelection, inline=False)
    embed.add_field(
        name="Channels",
        value=f"{', '.join([channel.mention for channel in queue.channels])}\n",
        inline=False,
    )
    embed.add_field(
        name="Queue Size",
        value=queue.maxSize,
        inline=False,
    )

    if queue.lobby_vc:
        embed.add_field(name="Lobby VC", value=queue.lobby_vc, inline=False)
    elif default_lobby_vc:
        embed.add_field(name="Lobby VC", value=default_lobby_vc, inline=False)

    embed.add_field(name="Games Played", value=f"{games_played}\n", inline=False)
    embed.add_field(
        name="Unique Players All-Time",
        value=f"{unique_players}\n",
        inline=False,
    )
    embed.add_field(
        name="Point Breakdown",
        value=f"**Per Series Played:** {queue.points[Strings.PP_PLAY_KEY]}\n**Per Series Win:** {queue.points[Strings.PP_WIN_KEY]}",
        inline=False,
    )
    return embed


def queue_players_embed(queue: SixMansQueue) -> discord.Embed:
    player_list = format_player_list(queue)
    embed = discord.Embed(
        title=f"{queue.name} {queue.maxSize} Mans Queue",
        color=discord.Colour.blue(),
    )
    embed.add_field(
        name=f"Players in Queue ({len(queue.queue.queue)}/{queue.maxSize})",
        value=player_list,
        inline=False,
    )
    return embed


def format_player_list(queue: SixMansQueue) -> str:
    player_list = ", ".join([player.mention for player in queue.queue.queue])
    if player_list == "":
        player_list = "No players currently in the queue"
    return player_list
