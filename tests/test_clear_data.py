"""clearSixMansData only clears a guild's data after the admin confirms, and stops waiting after a timeout."""

from unittest.mock import AsyncMock, MagicMock, patch

import discord
import pytest

from sixMans.constants import CONFIRM_TIMEOUT
from sixMans.sixMans import SixMans


@pytest.fixture
def guild():
    return MagicMock(spec=discord.Guild)


@pytest.fixture
def cog(guild):
    with patch("sixMans.sixMans.Config.get_conf"):
        cog = SixMans(MagicMock())
    cog.queueMaxSize = {guild: 6}
    cog._clear_all_data = AsyncMock()
    return cog


@pytest.fixture
def ctx(guild):
    ctx = MagicMock()
    ctx.guild = guild
    ctx.send = AsyncMock()
    return ctx


def answer(ctx, yes: bool | None):
    """Make the confirmation prompt resolve as yes, no, or time out (None)."""

    async def wait_for(_event, check, **kwargs):
        assert kwargs["timeout"] == CONFIRM_TIMEOUT
        if yes is None:
            raise TimeoutError
        check.result = yes

    ctx.bot.wait_for = wait_for


async def run_command(cog, ctx):
    with patch("sixMans.settings.commands.start_adding_reactions"), patch("sixMans.settings.commands.ReactionPredicate.yes_or_no", return_value=MagicMock()):
        await cog.clearSixMansData.callback(cog, ctx)


async def test_confirmed_clears_the_guild(cog, ctx, guild):
    answer(ctx, yes=True)

    await run_command(cog, ctx)

    cog._clear_all_data.assert_awaited_once_with(guild)
    assert ctx.send.await_args.args[0] == "Done"


async def test_declined_clears_nothing(cog, ctx):
    answer(ctx, yes=False)

    await run_command(cog, ctx)

    cog._clear_all_data.assert_not_awaited()
    assert ctx.send.await_args.args[0] == ":x: Data **not** cleared."


async def test_timed_out_clears_nothing(cog, ctx):
    answer(ctx, yes=None)

    await run_command(cog, ctx)

    cog._clear_all_data.assert_not_awaited()
    assert ctx.send.await_args.args[0] == ":x: Timed out. Data **not** cleared."
