"""Tests for how views answer button presses that overlap.

discord.py runs each button press in its own task, so presses overlap. Covers bugs:
- Some presses were never acknowledged, so Discord showed "This interaction failed" even
  though the press worked.
- Others were acknowledged only after editing the message, which can pass Discord's 3 second
  limit when edits are rate limited.
- Edits from overlapping presses could land out of order, putting an old tally and its dead
  buttons back over the final result.
- Overlapping cancel and play out votes could end the vote twice with different results.
"""

import asyncio
from typing import cast
from unittest.mock import AsyncMock, MagicMock

import pytest

from sixMans.enums import Winner
from sixMans.views.cancel import CancelView, ForceCancelView
from sixMans.views.score import ForceResultView, ScoreReportView
from sixMans.views.selfpick import SelfPickingView
from sixMans.views.vote import GameModeVote

from .conftest import FakeGame, as_game, make_interaction, make_member


def responses(interaction) -> int:
    """How many times an interaction was answered. Discord allows exactly one."""
    return interaction.response.defer.await_count + interaction.response.send_message.await_count


async def yield_once(*args, **kwargs):
    """Stand in for a request that lets other tasks run before it returns."""
    await asyncio.sleep(0)


def record_edits(view, slow_first: bool = False) -> list[dict]:
    """Record each edit of the view's message in the order Discord would apply it.

    With `slow_first`, the first edit takes longer than the rest, as a rate limited request would.
    """
    applied: list[dict] = []
    calls = 0

    async def edit(**kwargs):
        nonlocal calls
        calls += 1
        for _ in range(5 if slow_first and calls == 1 else 0):
            await asyncio.sleep(0)
        applied.append(kwargs)

    cast(MagicMock, view.msg).edit = AsyncMock(side_effect=edit)
    return applied


@pytest.mark.asyncio
async def test_final_pick_is_not_overwritten_by_a_slower_edit():
    """The last two self-picks land together. The slower tally edit must not land last."""
    players = [make_member(f"P{i}", i) for i in range(1, 5)]
    view = SelfPickingView(game=as_game(FakeGame(players=players)))
    await view.prompt()
    await view.pick_blue.callback(make_interaction(players[0]))
    await view.pick_orange.callback(make_interaction(players[1]))
    applied = record_edits(view, slow_first=True)

    third, fourth = make_interaction(players[2]), make_interaction(players[3])
    await asyncio.gather(view.pick_blue.callback(third), view.pick_orange.callback(fourth))

    assert view.finished
    assert applied[-1]["view"] is None, "An earlier tally edit put the buttons back after teams were picked"
    assert responses(third) == 1
    assert responses(fourth) == 1


@pytest.mark.asyncio
async def test_deciding_vote_is_acknowledged_before_the_message_edit():
    """The vote that ends the vote used to edit the message before answering the press."""
    players = [make_member(f"P{i}", i) for i in range(1, 7)]
    view = GameModeVote(game=as_game(FakeGame(players=players)))
    await view.start()
    for player in players[:3]:
        await view.process_vote(make_interaction(player, data={"custom_id": "Random"}))
    order: list[str] = []
    cast(MagicMock, view.msg).edit = AsyncMock(side_effect=lambda **_: order.append("edit"))
    interaction = make_interaction(players[3], data={"custom_id": "Random"})
    interaction.response.defer = AsyncMock(side_effect=lambda *_, **__: order.append("ack"))

    # A fourth vote out of six is a majority, which ends the vote
    await view.process_vote(interaction)

    assert view.is_finished()
    assert order == ["ack", "edit"]


@pytest.mark.asyncio
async def test_overlapping_cancel_and_play_votes_settle_once():
    """With 2-2 votes, a third cancel and a third play out landing together must not both win."""
    players = [make_member(f"P{i}", i) for i in range(1, 7)]
    view = CancelView(game=as_game(FakeGame(players=players)))
    await view.prompt()
    for player in players[:2]:
        await view.confirm.callback(make_interaction(player))
    for player in players[2:4]:
        await view.cancel.callback(make_interaction(player))
    applied = record_edits(view)

    cancel_press, play_press = make_interaction(players[4]), make_interaction(players[5])
    for press in (cancel_press, play_press):
        press.response.send_message = AsyncMock(side_effect=yield_once)
    await asyncio.gather(view.confirm.callback(cancel_press), view.cancel.callback(play_press))

    assert view.result is True
    assert [e["embed"].title for e in applied if e.get("view") is None] == ["Game Cancelled"]
    assert applied[-1]["embed"].title == "Game Cancelled"


@pytest.mark.asyncio
async def test_deciding_score_report_press_is_acknowledged(game, captains):
    view = ScoreReportView(game=game)
    await view.prompt()

    first, second = make_interaction(captains[0]), make_interaction(captains[1])
    await view.report_blue.callback(first)
    await view.report_blue.callback(second)

    assert view.result == Winner.BLUE
    assert responses(first) == 1
    assert responses(second) == 1


@pytest.mark.asyncio
async def test_score_report_cancel_is_acknowledged(game, captains):
    view = ScoreReportView(game=game)
    await view.prompt()

    press = make_interaction(captains[0])
    await view.cancel_report.callback(press)

    assert view.cancelled
    assert responses(press) == 1


@pytest.mark.asyncio
async def test_force_views_acknowledge_every_button(players):
    admin = make_member("Admin", 99)
    game = as_game(FakeGame(players=players))

    for view_type, buttons in ((ForceResultView, ("report_blue", "report_orange", "cancel_report")), (ForceCancelView, ("confirm", "cancel"))):
        for name in buttons:
            view = view_type(author=admin, game=game)
            await view.prompt()
            press = make_interaction(admin)

            await getattr(view, name).callback(press)

            assert view.is_finished(), f"{view_type.__name__}.{name} did not stop the view"
            assert responses(press) == 1, f"{view_type.__name__}.{name} never answered the press"


@pytest.mark.asyncio
async def test_force_result_double_click_keeps_first_choice(players):
    admin = make_member("Admin", 99)
    view = ForceResultView(author=admin, game=as_game(FakeGame(players=players)))
    await view.prompt()

    await asyncio.gather(view.report_blue.callback(make_interaction(admin)), view.report_orange.callback(make_interaction(admin)))

    assert view.result == Winner.BLUE


@pytest.mark.asyncio
async def test_rejected_presses_get_a_reply(players, captains):
    """A press turned away by `interaction_check` must still be answered."""
    outsider = make_member("Helper", 99)
    game = as_game(FakeGame(players=players, captains=captains))
    views = [
        CancelView(game=game),
        ScoreReportView(game=game),
        ForceCancelView(author=make_member("Admin", 98), game=game),
    ]

    for view in views:
        press = make_interaction(outsider)
        assert await view.interaction_check(press) is False
        assert responses(press) == 1, f"{type(view).__name__} turned a press away without answering it"
