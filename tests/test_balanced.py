"""Tests for balanced team selection (Game.get_balanced_teams).

Covers bugs:
- A perfectly balanced split scored 0, which is falsy, so the next split replaced it.
- The balance score returned was the last split's, not the best one's.
- `balance_score` only existed after balanced selection ran, so `mi` raised AttributeError
  for a balanced game loaded after a restart.
"""

from itertools import combinations
from typing import cast

from sixMans.enums import GameMode
from sixMans.game import Game
from sixMans.queue import SixMansQueue

from .conftest import FakeQueue, make_member, make_text_channel


def make_game(players, win_rates) -> Game:
    queue = FakeQueue(maxSize=len(players))
    queue.id = 1  # ty: ignore[unresolved-attribute]
    stats = {p.id: {"Wins": round(rate * 4), "GamesPlayed": 4} for p, rate in zip(players, win_rates, strict=True)}
    return Game(
        queue=cast(SixMansQueue, queue),
        players=players,
        teamSelection=GameMode.BALANCED,
        text_channel=make_text_channel(),
        stats_lookup=lambda _queue_id, player_id: stats[player_id],  # ty: ignore[invalid-argument-type]
    )


def test_every_perfect_split_is_kept():
    """Four of the six 2v2 splits here balance perfectly. All four must be candidates."""
    players = [make_member(f"P{i}", i) for i in range(1, 5)]
    game = make_game(players, [0.75, 0.25, 0.75, 0.25])
    scores = {p: data["Score"] for p, data in game.get_player_scores().items()}
    half = sum(scores.values()) / 2
    perfect = [team for team in combinations(game.players, 2) if sum(scores[p] for p in team) == half]
    assert len(perfect) == 4

    teams, balance_score = game.get_balanced_teams()

    assert len(teams) == len(perfect)
    assert {frozenset(p.id for p in team) for team in teams} == {frozenset(p.id for p in team) for team in perfect}
    assert balance_score == 0


def test_balance_score_is_the_best_splits():
    """The score returned must be the chosen split's difference, not whichever split came last."""
    players = [make_member(f"P{i}", i) for i in range(1, 5)]
    game = make_game(players, [1.0, 0.75, 0.5, 0.25])
    scores = {p: data["Score"] for p, data in game.get_player_scores().items()}
    half = sum(scores.values()) / 2
    best = min(abs(half - sum(scores[p] for p in team)) for team in combinations(game.players, 2))

    teams, balance_score = game.get_balanced_teams()

    assert balance_score == best
    assert all(abs(half - sum(scores[p] for p in team)) == best for team in teams)


def test_new_game_has_no_balance_score():
    """A game rebuilt from config never ran balanced selection, but `mi` still reads the attribute."""
    players = [make_member(f"P{i}", i) for i in range(1, 7)]
    game = Game(queue=cast(SixMansQueue, FakeQueue()), players=players, teamSelection=GameMode.BALANCED)

    assert game.balance_score is None
