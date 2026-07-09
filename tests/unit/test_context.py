"""Unit tests for panel/context.py -- Elo and rest days."""

from __future__ import annotations

import pandas as pd
import pytest
from loserpoint.panel.context import (
    EXPANSION_ELO,
    INITIAL_ELO,
    K_FACTOR,
    MAX_REST_DAYS,
    MEAN_ELO,
    SEASON_CARRYOVER,
    compute_game_context,
    expected_home_win_prob,
)


def _results(rows: list[tuple]) -> pd.DataFrame:
    return pd.DataFrame(
        rows,
        columns=[
            "season",
            "game_id",
            "date",
            "home_team",
            "away_team",
            "home_score",
            "away_score",
        ],
    )


def test_expected_home_win_prob_even_teams_favors_home() -> None:
    p = expected_home_win_prob(1500, 1500)
    assert 0.5 < p < 0.60  # home ice is worth something, not everything


def test_elo_updates_are_zero_sum_and_directional() -> None:
    games = _results([(2013, 20001, "2013-10-01", "TOR", "MTL", 3, 1)])
    ctx = compute_game_context(games)
    assert ctx.iloc[0]["home_elo_pre"] == INITIAL_ELO
    assert ctx.iloc[0]["away_elo_pre"] == INITIAL_ELO

    # Play a second game to observe the post-update ratings.
    games2 = _results(
        [
            (2013, 20001, "2013-10-01", "TOR", "MTL", 3, 1),
            (2013, 20002, "2013-10-03", "MTL", "TOR", 2, 1),
        ]
    )
    ctx2 = compute_game_context(games2)
    second = ctx2.iloc[1]
    p = expected_home_win_prob(INITIAL_ELO, INITIAL_ELO)
    expected_gain = K_FACTOR * (1 - p)
    assert second["away_elo_pre"] == pytest.approx(INITIAL_ELO + expected_gain)  # TOR won g1
    assert second["home_elo_pre"] == pytest.approx(INITIAL_ELO - expected_gain)
    # Zero-sum: total rating mass unchanged.
    assert second["home_elo_pre"] + second["away_elo_pre"] == pytest.approx(2 * INITIAL_ELO)


def test_season_carryover_regresses_toward_mean() -> None:
    games = _results(
        [
            (2013, 20001, "2013-10-01", "TOR", "MTL", 3, 1),
            (2014, 20001, "2014-10-01", "TOR", "MTL", 2, 1),
        ]
    )
    ctx = compute_game_context(games)
    p = expected_home_win_prob(INITIAL_ELO, INITIAL_ELO)
    tor_after = INITIAL_ELO + K_FACTOR * (1 - p)
    expected_tor = MEAN_ELO + SEASON_CARRYOVER * (tor_after - MEAN_ELO)
    assert ctx.iloc[1]["home_elo_pre"] == pytest.approx(expected_tor)


def test_expansion_team_debuts_below_par_but_first_season_teams_do_not() -> None:
    games = _results(
        [
            (2013, 20001, "2013-10-01", "TOR", "MTL", 3, 1),
            (2017, 20001, "2017-10-06", "VGK", "TOR", 2, 1),
        ]
    )
    ctx = compute_game_context(games)
    assert ctx.iloc[0]["home_elo_pre"] == INITIAL_ELO  # 2013 is the first season
    assert ctx.iloc[1]["home_elo_pre"] == EXPANSION_ELO  # VGK debuts in 2017


def test_rest_days_computed_and_capped() -> None:
    games = _results(
        [
            (2013, 20001, "2013-10-01", "TOR", "MTL", 3, 1),
            (2013, 20002, "2013-10-03", "TOR", "BOS", 2, 1),
            (2013, 20003, "2013-10-20", "TOR", "MTL", 2, 1),
        ]
    )
    ctx = compute_game_context(games)
    assert ctx.iloc[0]["home_rest_days"] == MAX_REST_DAYS  # opening night
    assert ctx.iloc[1]["home_rest_days"] == 2
    assert ctx.iloc[2]["home_rest_days"] == MAX_REST_DAYS  # 17 days, capped
    assert ctx.iloc[1]["away_rest_days"] == MAX_REST_DAYS  # BOS's first game


def test_unplayed_game_skipped_with_warning(caplog) -> None:
    games = _results(
        [
            (2013, 20001, "2013-10-01", "TOR", "MTL", 3, 1),
            (2013, 20002, "2013-10-03", "TOR", "BOS", None, None),
        ]
    )
    with caplog.at_level("WARNING"):
        ctx = compute_game_context(games)
    assert len(ctx) == 1
    assert any("no final score" in r.message for r in caplog.records)
