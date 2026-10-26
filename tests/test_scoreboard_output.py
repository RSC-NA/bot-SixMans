"""Golden output for every leaderboard, rank and queue info view, plus team balancing inputs.

Captured from the scoreboard before it was split out of the cog, so refactors can prove they change
nothing a player sees. Regenerate with UPDATE_GOLDEN=1 only for an intended output change, and review
the diff.
"""

import json
import os
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from discord.ext import commands

from sixMans.game import Game

from .scoreboard_env import DUELS, GENERAL, LEFT_SERVER, build_cog, make_config, make_guild, make_member, scenario

GOLDEN = Path(__file__).parent / "data" / "scoreboard_output.json"
AUTHOR = 14  # Ranked outside the all-time top ten, so their own line is appended

LEADERBOARDS = [
    ("overall", None),
    ("overall", "General"),
    ("overall", "Duels"),
    ("overall", "Empty"),
    ("overall", "No Such Queue"),
    ("day", None),
    ("day", "Duels"),
    ("day", "Empty"),
    ("week", None),
    ("week", "General"),
    ("month", None),
    ("month", "Duels"),
    ("year", None),
    ("year", "General"),
]
RANKS = [
    ("alltime", None, None),
    ("alltime", 1, None),
    ("alltime", 1, "Duels"),
    ("alltime", 99, None),
    ("alltime", None, "Empty"),
    ("daily", None, None),
    ("daily", 2, "General"),
    ("weekly", 7, "General"),
    ("monthly", 3, None),
    ("monthly", None, "Duels"),
    ("yearly", 12, "General"),
    ("yearly", None, "Empty"),
]


@pytest.fixture
def guild():
    return make_guild()


@pytest.fixture
async def cog(tmp_path, guild):
    return await build_cog(make_config(tmp_path), guild, scenario())


@pytest.fixture
def members(guild):
    return {i: make_member(i, guild) for i in range(1, 100)}


@pytest.fixture(autouse=True)
def member_lookup(members):
    async def convert(_self, _ctx, argument):
        member_id = int(argument)
        if member_id in LEFT_SERVER or member_id not in members:
            raise commands.MemberNotFound(argument)
        return members[member_id]

    with patch.object(commands.MemberConverter, "convert", convert):
        yield


@pytest.fixture
def ctx(guild, members):
    ctx = MagicMock()
    ctx.guild = guild
    ctx.author = members[AUTHOR]
    ctx.send = AsyncMock()
    return ctx


def sent(ctx) -> dict:
    call = ctx.send.await_args
    if "embed" in call.kwargs:
        return {"embed": call.kwargs["embed"].to_dict()}
    return {"text": call.args[0]}


async def collect(cog, ctx, members) -> dict:
    output = {}
    for name, queue_name in LEADERBOARDS:
        await getattr(cog, name).callback(cog, ctx, queue_name=queue_name)
        output[f"qlb {name} {queue_name}"] = sent(ctx)
    for name, player, queue_name in RANKS:
        await getattr(cog, name).callback(cog, ctx, members[player] if player else None, queue_name=queue_name)
        output[f"rank {name} {player} {queue_name}"] = sent(ctx)
    queues = {q.id: q for q in cog.queues[ctx.guild]}
    for queue_id in (GENERAL, DUELS):
        output[f"queue info {queue_id}"] = {"embed": cog.embed_queue_info(queues[queue_id]).to_dict()}

    game = Game(queue=queues[GENERAL], players=[members[p] for p in (1, 2, 7, 8, 9, 15)])
    output["balance scores"] = {str(member.id): data for member, data in sorted(game.get_player_scores().items(), key=lambda kv: kv[0].id)}
    return output


async def test_output_matches_golden(cog, ctx, members):
    output = json.loads(json.dumps(await collect(cog, ctx, members)))

    if os.environ.get("UPDATE_GOLDEN"):
        GOLDEN.parent.mkdir(exist_ok=True)
        GOLDEN.write_text(json.dumps(output, indent=2, sort_keys=True) + "\n")

    golden = json.loads(GOLDEN.read_text())
    assert output.keys() == golden.keys()
    for key in golden:
        assert output[key] == golden[key], key
