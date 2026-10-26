import discord

from sixMans.enums import GameMode
from sixMans.game import Game
from sixMans.queue import SixMansQueue

# What a player has to do in the game channel once their queue pops, by team selection mode
POPPED_NEXT_STEPS = {
    GameMode.VOTE: "Vote on how teams are picked. Team selection can't start until the vote ends.",
    GameMode.CAPTAINS: "Two captains will take turns picking players. If you're a captain, the pick message shows when it's your turn.",
    GameMode.SELF_PICK: "Choose your team with the Blue or Orange button.",
    GameMode.RANDOM: "Teams are assigned at random. Check the channel for your team and the lobby info.",
    GameMode.BALANCED: "Teams are balanced automatically. Check the channel for your team and the lobby info.",
}


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


def queue_popped_embed(game: Game) -> discord.Embed:
    """The DM sent to each player when their queue pops."""
    queue = game.queue
    mode = queue.teamSelection if game.teamSelection == GameMode.DEFAULT else game.teamSelection

    if game.textChannel:
        where = f"Head to [#{game.textChannel.name}]({game.textChannel.jump_url}) now."
    else:
        where = "Head to the game channel now."

    embed = discord.Embed(
        title=f"{queue.guild.name}: {queue.name} {queue.maxSize} Mans Queue Popped",
        description=f"Your **{queue.name}** queue has popped and your game is ready. {where}",
        color=discord.Colour.green(),
    )
    embed.add_field(name="Team Selection", value=f"**{mode}**\n{POPPED_NEXT_STEPS.get(mode, 'Follow the instructions in the game channel.')}", inline=False)

    # Voice channels are [Blue, Orange, General]
    if len(game.voiceChannels) == 3:
        general_vc = game.voiceChannels[2]
        embed.add_field(name="Voice", value=f"[{general_vc.name}]({general_vc.jump_url})", inline=False)

    embed.add_field(name="Players", value=", ".join(player.mention for player in game.players), inline=False)
    embed.set_footer(text=f"Game ID: {game.id}")
    if queue.guild.icon:
        embed.set_thumbnail(url=queue.guild.icon.url)
    return embed
