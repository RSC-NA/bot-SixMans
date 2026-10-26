"""Tests for CancelView (sixMans/views/cancel.py).

Covers bug: once a vote passed, the callback carried on and replaced the result
embed with the vote tally, re-attaching buttons on a view that had stopped.
"""

from typing import cast
from unittest.mock import MagicMock

import pytest

from sixMans.views.cancel import CancelView

from .conftest import FakeGame, as_game, make_interaction, make_member


async def make_view() -> tuple[CancelView, list]:
    players = [make_member(f"P{i}", i) for i in range(1, 7)]
    view = CancelView(game=as_game(FakeGame(players=players)))
    await view.prompt()
    return view, players


@pytest.mark.asyncio
async def test_passed_cancel_vote_keeps_result_message():
    """The last edit after a passed cancel vote must be the result, with no buttons."""
    view, players = await make_view()

    for player in players[: view.required_votes]:
        await view.confirm.callback(make_interaction(player))

    assert view.result is True
    assert view.is_finished()
    last_edit = cast(MagicMock, view.msg).edit.call_args
    assert last_edit.kwargs["view"] is None
    assert last_edit.kwargs["embed"].title == "Game Cancelled"


@pytest.mark.asyncio
async def test_failed_cancel_vote_keeps_result_message():
    """The last edit after enough play out votes must be the result, with no buttons."""
    view, players = await make_view()

    for player in players[: view.required_votes]:
        await view.cancel.callback(make_interaction(player))

    assert view.result is False
    assert view.is_finished()
    last_edit = cast(MagicMock, view.msg).edit.call_args
    assert last_edit.kwargs["view"] is None
    assert last_edit.kwargs["embed"].title == "Vote Failed"
