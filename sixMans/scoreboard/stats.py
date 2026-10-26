"""Score arithmetic with no Discord or config access."""

import datetime

from sixMans.strings import Strings
from sixMans.types import PlayerScore, PlayerStats
from sixMans.utils import parse_score_time

# Commit 78be65a made `give_points` drop players it hadn't seen before, so anyone whose first game came after it
# shipped is missing from (or undercounted in) the stored totals. Production backups show the last new player recorded
# on 2026-03-16 at 13:48 and none recorded from 15:36 that day on.
TOTALS_BUG_INTRODUCED = datetime.datetime(2026, 3, 16, 14, 0).astimezone()  # Host local time, like stored scores


def give_points(players: dict[str, PlayerStats], score: PlayerScore):
    player_score = players.setdefault(str(score["Player"]), PlayerStats(Points=0, Wins=0, GamesPlayed=0))
    player_score["Points"] = player_score["Points"] + score["Points"]
    player_score["GamesPlayed"] = player_score["GamesPlayed"] + 1
    player_score["Wins"] = player_score["Wins"] + score["Win"]


def make_score(queue_id: int, points: dict[str, int], game_id: int, player_id: int, win: int, date_time: str) -> PlayerScore:
    points_earned = points[Strings.PP_PLAY_KEY] + (points[Strings.PP_WIN_KEY] if win else 0)
    return PlayerScore(Game=game_id, Queue=queue_id, Player=player_id, Win=win, Points=points_earned, DateTime=date_time)


def filter_scores(scores: list[PlayerScore], start_date: datetime.datetime, queue_id: int | None, legacy_game_size: int) -> tuple[dict[str, PlayerStats], int]:
    """Totals and game count for scores after `start_date`, optionally for one queue.

    Scores from before game ids were recorded are counted as games by dividing by `legacy_game_size`.
    """
    players: dict[str, PlayerStats] = {}
    games: set[int] = set()
    legacy_scores = 0
    for score in scores:
        date_time = parse_score_time(score["DateTime"])
        # Scores are stored newest first, so everything after this is older
        if date_time <= start_date:
            break
        if queue_id is None or score["Queue"] == queue_id:
            give_points(players, score)
            # Queues have different sizes (Duels has 2 rows per game), so count games by id
            if "Game" in score:
                games.add(score["Game"])
            else:
                legacy_scores += 1
    games_played = len(games) + legacy_scores // legacy_game_size
    return players, games_played


def sort_players(players: dict[str, PlayerStats]) -> list[tuple[str, PlayerStats]]:
    """Most points first, ties broken by most wins."""
    by_wins = sorted(players.items(), key=lambda x: x[1]["Wins"], reverse=True)
    return sorted(by_wins, key=lambda x: x[1]["Points"], reverse=True)


def plan_totals_rebuild(stored: dict[str, PlayerStats], scores: list[PlayerScore], queue_id: int | None = None) -> dict[str, PlayerStats]:
    """Totals rebuilt from score history for players whose stored totals the 78be65a bug lost.

    Stored totals already disagree with score history for some older players for unrelated
    reasons, so only players whose first game in scope came after TOTALS_BUG_INTRODUCED are
    considered, and only if their stored totals are missing or show fewer games. Nobody's
    totals ever go down.
    """
    rebuilt: dict[str, PlayerStats] = {}
    first_played: dict[str, datetime.datetime] = {}
    parsed: dict[str, datetime.datetime] = {}  # Every player in a game shares its timestamp
    for score in scores:
        if queue_id is not None and score["Queue"] != queue_id:
            continue
        player_id = str(score["Player"])
        give_points(rebuilt, score)
        date_time = parsed.get(score["DateTime"])
        if date_time is None:
            date_time = parsed[score["DateTime"]] = parse_score_time(score["DateTime"])
        if player_id not in first_played or date_time < first_played[player_id]:
            first_played[player_id] = date_time

    changes: dict[str, PlayerStats] = {}
    for player_id, totals in rebuilt.items():
        if first_played[player_id] < TOTALS_BUG_INTRODUCED:
            continue
        current = stored.get(player_id)
        if current is None or current["GamesPlayed"] < totals["GamesPlayed"]:
            changes[player_id] = totals
    return changes
