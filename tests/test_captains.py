"""Tests for CaptainsView (sixMans/views/captains.py).

Covers bug: a pick refused because the captain's team was full had already been taken off the
pick list, so that player ended up on no team.
"""

import pytest

from sixMans.views.captains import CaptainsView

from .conftest import FakeGame, as_game, make_interaction, make_member


@pytest.mark.asyncio
async def test_refused_pick_stays_pickable():
    players = [make_member(f"P{i}", i) for i in range(1, 7)]
    view = CaptainsView(game=as_game(FakeGame(players=players)))
    await view.start()

    # Fill the picking captain's team without going through the pick order
    team = view.blue if view.picking in view.blue else view.orange
    while len(team) < view.team_size:
        team.append(view.pickable.pop())
    pick = view.pickable[0]

    press = make_interaction(view.picking, data={"custom_id": str(pick.id)})
    await view.process_pick(press)

    press.response.send_message.assert_awaited_once()
    assert pick in view.pickable
    assert pick not in view.blue
    assert pick not in view.orange
