import struct
import discord


def format_team_mentions(team: list[discord.Member], captains: list[discord.Member]) -> str:
    captain_players = [f"{player.mention} (C)" for player in team if player in captains]
    non_captains = [player.mention for player in team if player not in captains]
    ordered_players = captain_players + non_captains
    return "\n".join(ordered_players)


def get_emoji(value):
    try:
        if isinstance(value, int):
            return struct.pack("<I", value).decode("utf-32le")
        if isinstance(value, str):
            return struct.pack("<I", int(value, base=16)).decode("utf-32le")  # i == react_hex
    except (ValueError, TypeError):
        return None
