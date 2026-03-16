"""Tests for SelfPickingView (sixMans/views/selfpick.py).

Covers bug: Orange-full error message says "Blue team is already full".
"""

import pytest

from sixMans.views.selfpick import SelfPickingView

from .conftest import FakeGame, make_interaction, make_member


@pytest.mark.asyncio
async def test_orange_full_error_message():
    """When orange team is full, error should say 'Orange' not 'Blue'."""
    # 4-player game (2 per team)
    players = [make_member(f"P{i}", i) for i in range(1, 5)]
    game = FakeGame(players=players)

    view = SelfPickingView(game=game)
    await view.prompt()

    # Fill orange team (2 players)
    i1 = make_interaction(players[0])
    await view.pick_orange.callback(i1)
    i2 = make_interaction(players[1])
    await view.pick_orange.callback(i2)

    # Third player tries to join orange — should get "Orange" error
    i3 = make_interaction(players[2])
    await view.pick_orange.callback(i3)

    i3.response.send_message.assert_called_once()
    error_msg = i3.response.send_message.call_args[0][0]
    assert "Orange" in error_msg, (
        f"Expected error to mention 'Orange' but got: {error_msg!r}"
    )
    assert "Blue" not in error_msg, (
        f"Error message incorrectly says 'Blue' when orange is full: {error_msg!r}"
    )
