import discord

from sixMans.game import Game
from sixMans.queue import SixMansQueue


def active_games_embed(team_size: int, queues: list[SixMansQueue], queueGames: dict[int, list[Game]]) -> discord.Embed:
    embed = discord.Embed(
        title=f"{team_size} Mans Active Games",
        color=discord.Colour.blue(),
    )
    for queueId in queueGames:
        games = queueGames[queueId]
        queueName = next(queue.name for queue in queues if queue.id == queueId)
        embed.add_field(
            name=f"{queueName}:",
            value="\n".join([f"{game.id!s}\n{', '.join([player.mention for player in game.players])}" for game in games]),
            inline=False,
        )
    return embed
