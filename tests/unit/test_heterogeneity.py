"""Unit tests for analysis/heterogeneity.py."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
from loserpoint.analysis.heterogeneity import (
    add_even_matchup,
    add_interaction_dummies,
    add_intra_division,
    add_playoff_race,
    extract_estimates,
    fit_heterogeneity_model,
    playoff_distance,
    run_heterogeneity,
)
from loserpoint.analysis.models import build_estimation_sample


def _panel_and_context(n_games: int = 60, seed: int = 0) -> tuple[pd.DataFrame, pd.DataFrame]:
    rng = np.random.default_rng(seed)
    panel_rows, context_rows = [], []
    for g in range(n_games):
        season = 2014
        # State must be random, not g-dependent: the team pair is g % 6, so
        # any g-derived state is perfectly determined by the pair and the
        # dimension interactions become collinear with the fixed effects.
        state = ("tied", "down_1", "up_1")[int(rng.integers(0, 3))]
        team, opp = f"T{g % 6}", f"T{(g + 1) % 6}"
        home_elo = 1500.0 + rng.normal(0, 40)
        away_elo = 1500.0 + rng.normal(0, 40)
        context_rows.append(
            {
                "season": season,
                "game_id": g,
                "home_elo_pre": home_elo,
                "away_elo_pre": away_elo,
                "elo_diff_home": home_elo - away_elo,
                "home_rest_days": int(rng.integers(1, 4)),
                "away_rest_days": int(rng.integers(1, 4)),
            }
        )
        for is_home in (True, False):
            for minute in range(41, 59):
                panel_rows.append(
                    {
                        "season": season,
                        "game_id": g,
                        "is_home": is_home,
                        "is_playoff": False,
                        "non_5v5_flag": False,
                        "minute": minute,
                        "score_state": state,
                        "attempts_main": int(rng.poisson(0.5)),
                        "team_code": team if is_home else opp,
                        "opp_code": opp if is_home else team,
                    }
                )
    return pd.DataFrame(panel_rows), pd.DataFrame(context_rows)


def _game_results(n_games: int = 60) -> pd.DataFrame:
    rows = []
    for g in range(n_games):
        # First half of the schedule in November, second half in March.
        date = f"2014-11-{(g % 28) + 1:02d}" if g < n_games // 2 else f"2015-03-{(g % 28) + 1:02d}"
        rows.append(
            {
                "season": 2014,
                "game_id": g,
                "date": date,
                "home_team": f"T{g % 6}",
                "away_team": f"T{(g + 1) % 6}",
                "game_type": 2,
            }
        )
    return pd.DataFrame(rows)


def _alignment() -> pd.DataFrame:
    # T0-T2 in one division, T3-T5 in the other, all one conference.
    return pd.DataFrame(
        {
            "season": 2014,
            "team": [f"T{i}" for i in range(6)],
            "conference": "East",
            "division": ["Atlantic"] * 3 + ["Metropolitan"] * 3,
        }
    )


def test_add_interaction_dummies_products() -> None:
    sample = pd.DataFrame(
        {
            "score_state": ["tied", "up_1", "down_1", "tied"],
            "late": [1, 1, 0, 0],
            "flag": [True, False, True, True],
        }
    )
    out = add_interaction_dummies(sample, "flag")
    assert out["tied_late_dim"].tolist() == [1, 0, 0, 0]
    assert out["up1_late_dim"].tolist() == [0, 0, 0, 0]
    assert out["late_dim"].tolist() == [1, 0, 0, 0]
    assert out["tied_dim"].tolist() == [1, 0, 0, 1]


def test_add_intra_division_flags_same_division_games() -> None:
    panel, context = _panel_and_context(n_games=12)
    sample = build_estimation_sample(panel, context)
    out = add_intra_division(sample, _game_results(12), _alignment())
    by_game = out.groupby("game_id")["intra_division"].first()
    # Game g is Tg vs T(g+1): same division iff both in {0,1,2} or {3,4,5}.
    assert bool(by_game[0]) and bool(by_game[1])  # T0-T1, T1-T2
    assert not by_game[2]  # T2-T3 crosses divisions
    assert bool(by_game[3]) and bool(by_game[4])  # T3-T4, T4-T5
    assert not by_game[5]  # T5-T0 crosses divisions


def test_add_even_matchup_median_split() -> None:
    panel, context = _panel_and_context(n_games=30, seed=2)
    sample = build_estimation_sample(panel, context)
    out = add_even_matchup(sample)
    per_game = out.groupby("game_key")[["elo_diff_100", "even"]].first()
    median_gap = per_game["elo_diff_100"].abs().median()
    assert (per_game["even"] == (per_game["elo_diff_100"].abs() <= median_gap)).all()
    assert 0 < per_game["even"].mean() < 1


def test_playoff_distance_conference_cutline() -> None:
    standings = pd.DataFrame(
        {
            "date": "2015-03-01",
            "season": 2014,
            "team": [f"T{i}" for i in range(10)],
            "conference": "East",
            "division": ["Atlantic"] * 5 + ["Metropolitan"] * 5,
            "points": [100, 95, 90, 85, 80, 75, 70, 65, 60, 55],
        }
    )
    flags = pd.DataFrame([{"season": 2014, "conferences_in_use": True}])
    distance = playoff_distance(standings, flags).set_index("team")["cutline_distance"]
    # 8th-highest points in the conference = 65.
    assert distance["T7"] == 0
    assert distance["T0"] == 35
    assert distance["T9"] == -10


def test_playoff_distance_division_cutline_when_no_conferences() -> None:
    standings = pd.DataFrame(
        {
            "date": "2021-04-01",
            "season": 2020,
            "team": [f"T{i}" for i in range(5)],
            "conference": None,
            "division": "Scotia North",
            "points": [60, 55, 50, 45, 40],
        }
    )
    flags = pd.DataFrame([{"season": 2020, "conferences_in_use": False}])
    distance = playoff_distance(standings, flags).set_index("team")["cutline_distance"]
    # 4th-highest in the division = 45.
    assert distance["T3"] == 0
    assert distance["T0"] == 15
    assert distance["T4"] == -5


def _standings_by_date(game_results: pd.DataFrame, bubble_teams: set[str]) -> pd.DataFrame:
    """Pre-game snapshots for every second-half game date: bubble teams sit
    on the cutline, everyone else 20 points clear of it."""
    second_half = game_results[game_results["date"] >= "2015-01-01"]
    dates = sorted(
        (pd.to_datetime(second_half["date"]) - pd.Timedelta(days=1)).dt.strftime("%Y-%m-%d")
    )
    rows = []
    for date in dict.fromkeys(dates):
        for i in range(6):
            team = f"T{i}"
            rows.append(
                {
                    "date": date,
                    "season": 2014,
                    "team": team,
                    "conference": "East",
                    "division": "Atlantic",
                    # 8th-highest doesn't exist in a 6-team conference, so
                    # the cutline is the lowest team's points; spread the
                    # non-bubble teams 20 points above it.
                    "points": 50 if team in bubble_teams else 70,
                }
            )
    return pd.DataFrame(rows)


def test_add_playoff_race_restricts_and_flags() -> None:
    panel, context = _panel_and_context(n_games=12)
    sample = build_estimation_sample(panel, context)
    games = _game_results(12)
    flags = pd.DataFrame([{"season": 2014, "conferences_in_use": True}])
    second_half_start = pd.Series({2014: pd.Timestamp("2015-01-01")})
    standings = _standings_by_date(games, bubble_teams={"T0", "T1"})

    out = add_playoff_race(sample, games, standings, flags, second_half_start)
    # Only second-half games (ids 6-11) survive.
    assert set(out["game_id"].unique()) <= set(range(6, 12))
    by_game = out.groupby("game_id")["race"].first()
    # Game 6 is T0 vs T1 -- the only game where BOTH teams are on the bubble.
    assert bool(by_game[6])
    assert not by_game.drop(6).any()


def test_add_playoff_race_drops_games_missing_snapshots(caplog) -> None:
    panel, context = _panel_and_context(n_games=12)
    sample = build_estimation_sample(panel, context)
    games = _game_results(12)
    flags = pd.DataFrame([{"season": 2014, "conferences_in_use": True}])
    second_half_start = pd.Series({2014: pd.Timestamp("2015-01-01")})
    standings = _standings_by_date(games, bubble_teams=set())
    # Remove one date's snapshot entirely.
    first_date = standings["date"].min()
    standings = standings[standings["date"] != first_date]

    with caplog.at_level("WARNING"):
        out = add_playoff_race(sample, games, standings, flags, second_half_start)
    assert any("no pre-game standings snapshot" in r.message for r in caplog.records)
    assert out["game_id"].nunique() < 6


def test_fit_and_extract_heterogeneity_estimates() -> None:
    panel, context = _panel_and_context(n_games=120, seed=5)
    sample = build_estimation_sample(panel, context)
    out = add_even_matchup(sample).rename(columns={"even": "_dim"})
    model = fit_heterogeneity_model(add_interaction_dummies(out, "_dim"))
    estimates = extract_estimates(model, hypothesis="even", share_dim=0.5)
    assert {e.state for e in estimates} == {"tied", "up_1"}
    for e in estimates:
        assert e.hypothesis == "even"
        assert e.pct == pytest.approx(100 * (np.exp(e.coef) - 1))
        assert e.mde_pct > 0


def test_run_heterogeneity_produces_all_three_hypotheses() -> None:
    panel, context = _panel_and_context(n_games=120, seed=7)
    games = _game_results(120)
    flags = pd.DataFrame([{"season": 2014, "conferences_in_use": True}])
    second_half_start = pd.Series({2014: pd.Timestamp("2015-01-01")})
    # Four bubble teams so race games (consecutive-team pairs) land in all
    # three score states -- otherwise a dummy is all-zero and pyfixest
    # drops it for collinearity.
    standings = _standings_by_date(games, bubble_teams={"T0", "T1", "T2", "T3"})

    table = run_heterogeneity(
        panel, context, games, _alignment(), standings, flags, second_half_start
    )
    assert set(table["hypothesis"]) == {"race", "intra_division", "even"}
    assert len(table) == 6  # two states per hypothesis
    assert np.isfinite(table[["coef", "se", "pct", "mde_pct"]]).all().all()
    assert ((table["share_dim"] >= 0) & (table["share_dim"] <= 1)).all()
