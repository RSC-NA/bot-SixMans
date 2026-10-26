"""Tests for tearing down selection views when a game goes away.

A game's text channel is deleted when the game is cancelled or finished. Any
view still waiting on that channel has to be stopped, otherwise its timeout
fires later against a channel that no longer exists, and whoever is parked in
`view.wait()` stays blocked until it does.

The same goes for a forced team selection (`fts`) replacing one that is still
waiting on its view.
"""

import asyncio
from typing import cast
from unittest.mock import AsyncMock, MagicMock

import discord
import pytest

from sixMans.enums import GameMode
from sixMans.game import Game
from sixMans.queue import SixMansQueue
from sixMans.views import safe_edit
from sixMans.views.captains import CaptainsView
from sixMans.views.vote import GameModeVote

from .conftest import FakeQueue, make_member, make_text_channel


def make_game(players) -> Game:
    """A real Game backed by mock discord objects."""
    return Game(
        queue=cast(SixMansQueue, FakeQueue()),
        players=players,
        teamSelection=GameMode.VOTE,
        text_channel=make_text_channel(),
    )


@pytest.mark.asyncio
async def test_abort_stops_active_view_and_unblocks_wait():
    """abort() must stop the live view so a pending wait() returns."""
    players = [make_member(f"P{i}", i) for i in range(1, 7)]
    game = make_game(players)

    view = GameModeVote(game=game)
    await view.start()
    game.active_view = view

    assert not view.is_finished()

    game.abort()

    assert game.aborted
    assert game.active_view is None
    assert view.is_finished()
    # A stopped view resolves its future, so wait() returns instead of hanging
    assert await view.wait() is False


@pytest.mark.asyncio
async def test_abort_with_no_active_view_is_safe():
    """abort() on a game that is not mid-selection must not raise."""
    players = [make_member(f"P{i}", i) for i in range(1, 7)]
    game = make_game(players)

    game.abort()

    assert game.aborted
    assert game.active_view is None


@pytest.mark.asyncio
async def test_channel_deleted_reflects_guild_lookup():
    """channel_deleted must detect a channel that is gone from the guild."""
    players = [make_member(f"P{i}", i) for i in range(1, 7)]
    game = make_game(players)

    assert not game.channel_deleted

    # Channel object is still cached on the game, but the guild no longer has it
    cast(MagicMock, game.queue.guild).get_channel.return_value = None
    assert game.channel_deleted

    game.textChannel = None
    assert game.channel_deleted


@pytest.mark.asyncio
async def test_vote_team_selection_skips_aborted_game(monkeypatch):
    """A game aborted mid-vote must not post to its channel or pick teams."""
    players = [make_member(f"P{i}", i) for i in range(1, 7)]
    game = make_game(players)

    original_start = GameModeVote.start
    channel = cast(MagicMock, game.textChannel)

    async def start_then_abort(self):
        await original_start(self)
        # Discount the view posting its own prompt; nothing may follow it
        channel.send.reset_mock()
        # Stand in for _remove_game firing while the vote is still open
        game.active_view = self
        game.abort()

    monkeypatch.setattr(GameModeVote, "start", start_then_abort)

    await game.vote_team_selection()

    # No "Error during game mode vote..." message, no team assignment
    channel.send.assert_not_called()
    assert not game.blue
    assert not game.orange


@pytest.mark.asyncio
async def test_safe_edit_swallows_http_errors():
    """safe_edit must absorb NotFound/Forbidden rather than propagate them."""
    msg = MagicMock(spec=discord.Message)
    msg.id = 123

    msg.edit = AsyncMock(side_effect=discord.NotFound(MagicMock(status=404, reason="Not Found"), {"code": 10003, "message": "Unknown Channel"}))
    await safe_edit(msg, content="x")

    msg.edit = AsyncMock(side_effect=discord.Forbidden(MagicMock(status=403, reason="Forbidden"), "no"))
    await safe_edit(msg, content="x")

    # A None message is a no-op, not an AttributeError
    await safe_edit(None, content="x")


async def park_in_view(game: Game, view_type: type[discord.ui.View]) -> asyncio.Task:
    """Start team selection in the background and return once it is waiting on its view."""
    task = asyncio.create_task(game.process_team_selection_method())
    for _ in range(10):
        if isinstance(game.active_view, view_type):
            return task
        await asyncio.sleep(0)
    raise AssertionError(f"Team selection never parked in {view_type.__name__}")


@pytest.mark.asyncio
@pytest.mark.parametrize(("mode", "view_type"), [(GameMode.VOTE, GameModeVote), (GameMode.CAPTAINS, CaptainsView)])
async def test_forced_selection_replaces_pending_selection(monkeypatch, mode, view_type):
    """`fts` must stop a selection still waiting on its view, which then returns quietly.

    Regression test: the earlier view kept running, and when it finished it
    assigned teams over the forced ones. Stopping it alone is not enough either,
    since its unfinished view would then be reported as a failed selection.
    """
    players = [make_member(f"P{i}", i) for i in range(1, 7)]
    game = make_game(players)
    game.teamSelection = mode
    random_pick = AsyncMock()
    monkeypatch.setattr(Game, "pick_random_teams", random_pick)

    pending = await park_in_view(game, view_type)
    pending_view = game.active_view
    assert pending_view is not None
    channel = cast(MagicMock, game.textChannel)
    channel.send.reset_mock()

    await game.process_team_selection_method(team_selection=GameMode.RANDOM, force=True)
    await asyncio.wait_for(pending, timeout=1)

    assert pending_view.is_finished()
    random_pick.assert_awaited_once()
    # Neither an error report nor a second game info from the replaced selection
    channel.send.assert_not_called()
