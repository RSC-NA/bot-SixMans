"""Tests for GameModeVote (sixMans/views/vote.py).

Covers:
- Double voting is allowed (duplicate check commented out).
- Vote timeout picks the leading mode.
- Timing out against a deleted channel does not raise.
"""

from typing import cast
from unittest.mock import AsyncMock, MagicMock

import discord
import pytest

from sixMans.enums import GameMode
from sixMans.views.vote import GameModeVote

from .conftest import FakeGame, as_game, make_interaction, make_member


@pytest.mark.asyncio
async def test_player_cannot_vote_twice():
    """A player who already voted should not have their second vote counted."""
    players = [make_member(f"P{i}", i) for i in range(1, 7)]
    game = as_game(FakeGame(players=players))
    view = GameModeVote(game=game)
    await view.start()

    voter = players[0]

    # First vote for RANDOM
    i1 = make_interaction(voter, data={"custom_id": GameMode.RANDOM.value})
    await view.process_vote(i1)
    assert view.votes[GameMode.RANDOM] == 1

    # Second vote by same player — should be rejected
    i2 = make_interaction(voter, data={"custom_id": GameMode.RANDOM.value})
    await view.process_vote(i2)
    assert view.votes[GameMode.RANDOM] == 1, f"Vote count is {view.votes[GameMode.RANDOM]} — duplicate vote was counted. The duplicate check needs to be enabled."


@pytest.mark.asyncio
async def test_timeout_picks_leading_mode():
    """When the vote times out, the mode with the most votes should win."""
    players = [make_member(f"P{i}", i) for i in range(1, 7)]
    game = as_game(FakeGame(players=players))
    view = GameModeVote(game=game)
    await view.start()

    # Two players vote for CAPTAINS, one for RANDOM
    for i, mode in enumerate([GameMode.CAPTAINS, GameMode.CAPTAINS, GameMode.RANDOM]):
        interaction = make_interaction(players[i], data={"custom_id": mode.value})
        await view.process_vote(interaction)

    # Simulate timeout (not enough votes to finish normally)
    assert not view.vote_finished
    await view.on_timeout()

    assert view.result == GameMode.CAPTAINS


@pytest.mark.asyncio
async def test_timeout_with_no_votes_defaults_to_random():
    """When the vote times out with zero votes, default to RANDOM."""
    players = [make_member(f"P{i}", i) for i in range(1, 7)]
    game = as_game(FakeGame(players=players))
    view = GameModeVote(game=game)
    await view.start()

    await view.on_timeout()

    assert view.result == GameMode.RANDOM


@pytest.mark.asyncio
async def test_timeout_survives_deleted_channel():
    """Timing out after the game channel is deleted must not raise.

    Regression test: discord.py dispatches on_timeout() in a bare task, so a
    NotFound here surfaces as "Task exception was never retrieved".
    """
    players = [make_member(f"P{i}", i) for i in range(1, 7)]
    game = as_game(FakeGame(players=players))
    view = GameModeVote(game=game)
    await view.start()

    # One vote so a real result is selected, then the channel goes away
    interaction = make_interaction(players[0], data={"custom_id": GameMode.CAPTAINS.value})
    await view.process_vote(interaction)

    not_found = discord.NotFound(MagicMock(status=404, reason="Not Found"), {"code": 10003, "message": "Unknown Channel"})
    cast(MagicMock, view.msg).edit = AsyncMock(side_effect=not_found)

    await view.on_timeout()

    # The result still has to be resolved -- the caller waiting on this view
    # dispatches on it regardless of whether the embed could be updated.
    assert view.result == GameMode.CAPTAINS


@pytest.mark.asyncio
async def test_timeout_without_message_does_not_raise():
    """A view that timed out before start() posted its message must not raise."""
    players = [make_member(f"P{i}", i) for i in range(1, 7)]
    game = as_game(FakeGame(players=players))
    view = GameModeVote(game=game)

    assert view.msg is None
    await view.on_timeout()

    assert view.result == GameMode.RANDOM


@pytest.mark.asyncio
async def test_start_without_channel_stops_view():
    """With no text channel, start() must stop the view so wait() returns."""
    players = [make_member(f"P{i}", i) for i in range(1, 7)]
    game = as_game(FakeGame(players=players))
    game.textChannel = None
    view = GameModeVote(game=game)

    await view.start()

    assert view.is_finished()
    assert view.msg is None
