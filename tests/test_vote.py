"""Tests for GameModeVote (sixMans/views/vote.py).

Covers bug: Double voting is allowed (duplicate check commented out).
"""

import pytest

from sixMans.enums import GameMode
from sixMans.views.vote import GameModeVote

from .conftest import make_interaction, make_member, FakeGame


@pytest.mark.asyncio
async def test_player_cannot_vote_twice():
    """A player who already voted should not have their second vote counted."""
    players = [make_member(f"P{i}", i) for i in range(1, 7)]
    game = FakeGame(players=players)
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
    assert view.votes[GameMode.RANDOM] == 1, (
        f"Vote count is {view.votes[GameMode.RANDOM]} — "
        "duplicate vote was counted. The duplicate check needs to be enabled."
    )
