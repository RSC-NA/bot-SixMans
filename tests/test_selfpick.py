"""Tests for SelfPickingView (sixMans/views/selfpick.py).

Covers bug: Orange-full error message says "Blue team is already full".
Covers bug: a completed pick left `finished` False, so game.self_picking_teams()
reported an error and assigned no teams.
Covers bug: the player check was named `on_interaction`, which discord.py never
calls, so anyone who could see the channel could take a team slot.
"""

from typing import cast
from unittest.mock import MagicMock

import pytest

from sixMans.enums import GameMode, GameState
from sixMans.game import Game
from sixMans.queue import SixMansQueue
from sixMans.views.selfpick import SelfPickingView

from .conftest import FakeGame, FakeQueue, as_game, make_interaction, make_member, make_text_channel


@pytest.mark.asyncio
async def test_orange_full_error_message():
    """When orange team is full, error should say 'Orange' not 'Blue'."""
    # 4-player game (2 per team)
    players = [make_member(f"P{i}", i) for i in range(1, 5)]
    game = as_game(FakeGame(players=players))

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
    assert "Orange" in error_msg, f"Expected error to mention 'Orange' but got: {error_msg!r}"
    assert "Blue" not in error_msg, f"Error message incorrectly says 'Blue' when orange is full: {error_msg!r}"


async def complete_pick(view, players):
    """Place every player on a team, alternating blue and orange."""
    for i, player in enumerate(players):
        interaction = make_interaction(player)
        if i % 2 == 0:
            await view.pick_blue.callback(interaction)
        else:
            await view.pick_orange.callback(interaction)


@pytest.mark.asyncio
async def test_completed_pick_sets_finished():
    """Placing the last player must mark the view finished, not just stop it.

    `game.self_picking_teams()` reads `finished` to decide whether the pick
    succeeded, so stopping without setting it reports a failure on a good pick.
    """
    players = [make_member(f"P{i}", i) for i in range(1, 7)]
    game = as_game(FakeGame(players=players))

    view = SelfPickingView(game=game)
    await view.prompt()
    await complete_pick(view, players)

    assert len(view.unplaced) == 0
    assert view.is_finished()
    assert view.finished


@pytest.mark.asyncio
async def test_self_picking_teams_assigns_teams(monkeypatch):
    """A successful self-pick must assign teams instead of reporting an error."""
    players = [make_member(f"P{i}", i) for i in range(1, 7)]
    queue = FakeQueue(maxSize=6)
    game = Game(
        queue=cast(SixMansQueue, queue),
        players=players,
        teamSelection=GameMode.SELF_PICK,
        text_channel=make_text_channel(),
    )

    original_prompt = SelfPickingView.prompt

    async def prompt_then_pick(self):
        await original_prompt(self)
        await complete_pick(self, players)

    monkeypatch.setattr(SelfPickingView, "prompt", prompt_then_pick)

    await game.self_picking_teams()

    sends = [str(c) for c in cast(MagicMock, game.textChannel).send.call_args_list]
    assert not any("Error during team selection" in s for s in sends), f"Reported an error on a successful pick: {sends}"
    assert len(game.blue) == 3
    assert len(game.orange) == 3
    assert game.state == GameState.ONGOING


@pytest.mark.asyncio
async def test_non_player_cannot_pick_team():
    """Someone who can see the channel but is not in the game must be turned away."""
    players = [make_member(f"P{i}", i) for i in range(1, 7)]
    game = as_game(FakeGame(players=players))
    view = SelfPickingView(game=game)
    await view.prompt()

    outsider = make_interaction(make_member("Helper", 99))
    assert await view.interaction_check(outsider) is False
    outsider.response.send_message.assert_called_once()

    assert await view.interaction_check(make_interaction(players[0])) is True
