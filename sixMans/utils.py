import datetime
import struct
from collections.abc import Collection

import discord

# Score timestamps are stored as the bot host's local time with no offset, so they're parsed and written as local time.
SCORE_DATE_FORMAT = "%d-%b-%Y (%H:%M:%S.%f)"


def utc_now() -> datetime.datetime:
    return datetime.datetime.now(datetime.UTC)


def parse_score_time(value: str) -> datetime.datetime:
    return datetime.datetime.strptime(value, SCORE_DATE_FORMAT).astimezone()


def format_score_time(when: datetime.datetime) -> str:
    return when.astimezone().strftime(SCORE_DATE_FORMAT)


def format_team_mentions(team: Collection[discord.Member], captains: Collection[discord.Member]) -> str:
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
