"""Leaderboard rows when players have left the server."""

from unittest.mock import MagicMock, patch

import pytest
from discord.ext import commands

from sixMans.scoreboard.embeds import leaderboard_embed
from sixMans.types import PlayerStats

from .scoreboard_env import make_member


def board(size: int) -> list[tuple[str, PlayerStats]]:
    return [(str(p), PlayerStats(Points=100 - p, Wins=10, GamesPlayed=20)) for p in range(1, size + 1)]


def rows(embed) -> list[str]:
    fields = {f.name: f.value for f in embed.fields}
    return [line for line in fields["Player"].split("\n") if line]


@pytest.fixture
def left_server():
    return set()


@pytest.fixture
def lookups():
    return []


@pytest.fixture(autouse=True)
def member_lookup(left_server, lookups):
    async def convert(_self, _ctx, argument):
        lookups.append(int(argument))
        if int(argument) in left_server:
            raise commands.MemberNotFound(argument)
        return make_member(int(argument))

    with patch.object(commands.MemberConverter, "convert", convert):
        yield


def ctx_for(author_id: int):
    ctx = MagicMock()
    ctx.author = make_member(author_id)
    return ctx


async def test_shows_ten_rows():
    embed = await leaderboard_embed(ctx_for(1), board(15), "General", 6, 5, "All-time")

    assert [row.split("`")[1] for row in rows(embed)] == [str(n) for n in range(1, 11)]


async def test_player_who_left_keeps_their_rank_but_not_a_row(left_server):
    left_server.add(4)

    embed = await leaderboard_embed(ctx_for(1), board(15), "General", 6, 5, "All-time")

    assert [row.split("`")[1] for row in rows(embed)] == ["1", "2", "3", "5", "6", "7", "8", "9", "10", "11"]


async def test_author_moved_into_the_top_rows_is_not_listed_twice(left_server):
    left_server.add(4)

    embed = await leaderboard_embed(ctx_for(11), board(15), "General", 6, 5, "All-time")

    assert sum("Player11" in row for row in rows(embed)) == 1
    assert len(rows(embed)) == 10


async def test_author_outside_the_top_rows_gets_their_own_line():
    embed = await leaderboard_embed(ctx_for(14), board(15), "General", 6, 5, "All-time")

    assert rows(embed)[-1].startswith("`14` **Player14")
    assert len(rows(embed)) == 11


async def test_stops_looking_up_players_after_the_top_twenty(left_server, lookups):
    """Each lookup of a player who left is a Discord query, so a board full of them must stay bounded."""
    left_server.update(range(1, 18))

    embed = await leaderboard_embed(ctx_for(500), board(100), "General", 6, 5, "All-time")

    assert lookups == list(range(1, 21))
    assert [row.split("`")[1] for row in rows(embed)] == ["18", "19", "20"]
