"""Tests for score aggregation behind the queue leaderboard (qlb) commands."""

import datetime
import time
from unittest.mock import MagicMock, patch

import pytest

from sixMans.sixMans import SixMans
from sixMans.types import PlayerScore
from sixMans.utils import format_score_time, parse_score_time, utc_now


def make_score(player, queue=1, win=1, points=15, days_ago=0.0, game=1) -> PlayerScore:
    when = utc_now() - datetime.timedelta(days=days_ago)
    return PlayerScore(Game=game, Queue=queue, Player=player, Win=win, Points=points, DateTime=format_score_time(when))


@pytest.fixture
def guild():
    return MagicMock()


@pytest.fixture
def cog(guild):
    with patch("sixMans.sixMans.Config.get_conf") as mock_conf, patch("sixMans.sixMans.asyncio.create_task"):
        mock_conf.return_value.register_guild = MagicMock()
        cog = SixMans(MagicMock())
    cog.queueMaxSize = {guild: 2}
    return cog


@pytest.fixture
def new_york_host(monkeypatch):
    """Run the test as if the bot host's local time were US Eastern."""
    monkeypatch.setenv("TZ", "America/New_York")
    time.tzset()
    yield
    monkeypatch.undo()
    time.tzset()


class TestGivePoints:
    def test_new_player_is_added(self, cog):
        players = {}
        cog._give_points(players, make_score(42, win=1, points=15))
        assert players == {"42": {"Points": 15, "Wins": 1, "GamesPlayed": 1}}

    def test_existing_player_accumulates(self, cog):
        players = {}
        cog._give_points(players, make_score(42, win=1, points=15))
        cog._give_points(players, make_score(42, win=0, points=5))
        assert players["42"] == {"Points": 20, "Wins": 1, "GamesPlayed": 2}


class TestFilterScores:
    def test_recent_scores_are_counted(self, cog, guild):
        # Stored newest first, matching _finish_game's insert(0, ...)
        scores = [make_score(1, days_ago=0.1), make_score(2, win=0, points=5, days_ago=0.1), make_score(3, days_ago=10)]
        week_ago = utc_now() - datetime.timedelta(weeks=1)

        players, games_played = cog._filter_scores(guild, scores, week_ago, None)

        assert set(players) == {"1", "2"}
        assert games_played == 1

    def test_other_queue_does_not_stop_the_scan(self, cog, guild):
        scores = [make_score(1, queue=2, days_ago=0.1), make_score(2, queue=1, days_ago=0.2), make_score(3, queue=1, days_ago=0.3)]
        week_ago = utc_now() - datetime.timedelta(weeks=1)

        players, games_played = cog._filter_scores(guild, scores, week_ago, 1)

        assert set(players) == {"2", "3"}
        assert games_played == 1

    def test_games_are_counted_by_id_not_guild_queue_size(self, cog, guild):
        """A Duels game has 2 score rows. Dividing by a 6 player guild size reported 0 games."""
        cog.queueMaxSize = {guild: 6}
        scores = [make_score(1, queue=7, game=10), make_score(2, queue=7, game=10, win=0), make_score(3, queue=7, game=11), make_score(4, queue=7, game=11, win=0)]
        week_ago = utc_now() - datetime.timedelta(weeks=1)

        assert cog._filter_scores(guild, scores, week_ago, 7)[1] == 2
        assert cog._filter_scores(guild, scores, week_ago, None)[1] == 2

    def test_scores_without_game_ids_fall_back_to_queue_size(self, cog, guild):
        legacy = [{k: v for k, v in make_score(p).items() if k != "Game"} for p in (1, 2, 3, 4)]
        week_ago = utc_now() - datetime.timedelta(weeks=1)

        assert cog._filter_scores(guild, [make_score(5, game=10), *legacy], week_ago, None)[1] == 1 + 4 // 2

    @pytest.mark.usefixtures("new_york_host")
    def test_day_cutoff_is_exact_on_non_utc_host(self, cog, guild):
        scores = [make_score(1, days_ago=23.5 / 24), make_score(2, days_ago=23.5 / 24), make_score(3, days_ago=24.5 / 24)]
        day_ago = utc_now() - datetime.timedelta(days=1)

        players, games_played = cog._filter_scores(guild, scores, day_ago, None)

        assert set(players) == {"1", "2"}
        assert games_played == 1


class TestScoreTime:
    def test_round_trip_keeps_the_instant(self):
        when = utc_now()
        assert parse_score_time(format_score_time(when)) == when

    @pytest.mark.usefixtures("new_york_host")
    def test_stored_strings_are_host_local_time(self):
        parsed = parse_score_time("16-Mar-2026 (14:00:00.000000)")
        assert parsed == datetime.datetime(2026, 3, 16, 18, 0, tzinfo=datetime.UTC)
        assert format_score_time(parsed) == "16-Mar-2026 (14:00:00.000000)"
