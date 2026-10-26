"""scoreReport refuses reports until the game channel is five minutes old, however old the game gets."""

import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import discord
import pytest

from sixMans.sixMans import SixMans

NOW = datetime.datetime(2026, 10, 26, 12, 0, tzinfo=datetime.UTC)


@pytest.fixture
def cog():
    with patch("sixMans.sixMans.Config.get_conf"):
        cog = SixMans(MagicMock())
    # Past the time check the command looks up the game. Stopping there is enough to show it got through.
    cog.get_info = AsyncMock(return_value=(None, None))
    return cog


def context(game_age: datetime.timedelta) -> MagicMock:
    ctx = MagicMock()
    ctx.channel = MagicMock(spec=discord.TextChannel)
    ctx.channel.created_at = NOW - game_age
    ctx.message.created_at = NOW
    ctx.send = AsyncMock()
    return ctx


async def report(cog, ctx):
    await cog.scoreReport.callback(cog, ctx)


@pytest.mark.parametrize("game_age", [datetime.timedelta(minutes=2), datetime.timedelta(minutes=4, seconds=59)])
async def test_new_game_is_refused(cog, game_age):
    ctx = context(game_age)

    await report(cog, ctx)

    cog.get_info.assert_not_awaited()
    assert f"Current time that's passed = **{int(game_age.total_seconds()) // 60} minute(s)**" in ctx.send.await_args.args[0]


@pytest.mark.parametrize("game_age", [datetime.timedelta(minutes=5), datetime.timedelta(hours=3)])
async def test_game_past_five_minutes_is_accepted(cog, game_age):
    ctx = context(game_age)

    await report(cog, ctx)

    cog.get_info.assert_awaited_once_with(ctx)


async def test_game_over_a_day_old_is_accepted(cog):
    """A day and two minutes in, the old check only saw the two minutes and refused the report."""
    ctx = context(datetime.timedelta(days=1, minutes=2))

    await report(cog, ctx)

    cog.get_info.assert_awaited_once_with(ctx)
