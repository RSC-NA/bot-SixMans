"""Tests for ScoreReportView (sixMans/views/score.py).

Covers bugs:
1. display_winner() sets self.winner but never self.result
2. already_answered() checks ALL captains, not the specific member
3. Non-unanimous vote doesn't stop the view or return early
"""

import pytest

from sixMans.enums import Winner
from sixMans.views.score import ScoreReportView

from .conftest import make_interaction


# ---------------------------------------------------------------------------
# Helpers — discord.ui.button decorator wraps methods as Button objects,
# so we need to call .callback(interaction) to invoke them in tests.
# ---------------------------------------------------------------------------


async def vote_blue(view: ScoreReportView, interaction):
    await view.report_blue.callback(interaction)


async def vote_orange(view: ScoreReportView, interaction):
    await view.report_orange.callback(interaction)


# ---------------------------------------------------------------------------
# Bug 1: self.result is never set by display_winner()
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_result_set_after_unanimous_blue(game, captains):
    """After both captains vote Blue, result should be Winner.BLUE."""
    view = ScoreReportView(game=game)
    await view.prompt()

    i1 = make_interaction(captains[0])
    await vote_blue(view, i1)

    i2 = make_interaction(captains[1])
    await vote_blue(view, i2)

    assert view.result == Winner.BLUE, (
        f"Expected result=BLUE but got {view.result!r}. "
        "display_winner() must set self.result, not just self.winner."
    )


@pytest.mark.asyncio
async def test_result_set_after_unanimous_orange(game, captains):
    """After both captains vote Orange, result should be Winner.ORANGE."""
    view = ScoreReportView(game=game)
    await view.prompt()

    i1 = make_interaction(captains[0])
    await vote_orange(view, i1)

    i2 = make_interaction(captains[1])
    await vote_orange(view, i2)

    assert view.result == Winner.ORANGE


# ---------------------------------------------------------------------------
# Bug 2: already_answered() checks all answers, not the specific member
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_already_answered_checks_specific_member(game, captains):
    """already_answered(captain_0) should be True only if captain_0 voted."""
    view = ScoreReportView(game=game)
    await view.prompt()

    # Captain 0 has NOT voted yet
    assert not await view.already_answered(captains[0]), (
        "Captain 0 hasn't voted yet, already_answered should be False"
    )

    # Captain 0 votes
    i1 = make_interaction(captains[0])
    await vote_blue(view, i1)

    # Captain 0 HAS voted
    assert await view.already_answered(captains[0]), (
        "Captain 0 has voted, already_answered should be True"
    )

    # Captain 1 has NOT voted — should still be False
    assert not await view.already_answered(captains[1]), (
        "Captain 1 hasn't voted yet, already_answered should be False"
    )


# ---------------------------------------------------------------------------
# Bug 3: Non-unanimous vote falls through to display_winner()
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_non_unanimous_does_not_call_display_winner(game, captains):
    """When captains disagree, display_winner() should NOT be called.

    The current code falls through to display_winner() after showing the
    "not unanimous" embed, which posts a confusing "Game Finished" message.
    """
    view = ScoreReportView(game=game)
    await view.prompt()

    # Captain 0 votes Blue
    i1 = make_interaction(captains[0])
    await vote_blue(view, i1)

    # Captain 1 votes Orange (disagreement)
    i2 = make_interaction(captains[1])
    await vote_orange(view, i2)

    # display_winner sets self.winner — it should NOT have been called
    assert not hasattr(view, "winner"), (
        "display_winner() was called after non-unanimous vote. "
        "The non-unanimous branch must return early."
    )
