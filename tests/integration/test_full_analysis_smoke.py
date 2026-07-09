"""Smoke tests: run_main_models and the full robustness battery execute
end-to-end on a compact synthetic panel shaped exactly like the real one.

These are not statistical tests (test_recovery.py owns correctness); they
guarantee every spec in the battery *runs* -- formulas parse, samples are
non-empty, outputs are finite and complete -- so a refactor can't silently
break a robustness row that only ever executes in the production run.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
from loserpoint.analysis.models import run_main_models
from loserpoint.analysis.robustness import run_robustness_battery

N_GAMES = 240
STATES = ("tied", "down_1", "up_1")


@pytest.fixture(scope="module")
def synthetic_panel_and_context() -> tuple[pd.DataFrame, pd.DataFrame]:
    rng = np.random.default_rng(0)
    teams = [f"T{i}" for i in range(8)]
    panel_rows, context_rows = [], []
    for g in range(N_GAMES):
        season = 2013 + g % 4  # includes a "COVID" season (2019) analog? no --
        # seasons 2013-2016 here; the drop_covid spec simply drops nothing,
        # which still exercises its code path.
        home, away = rng.choice(teams, size=2, replace=False)
        is_playoff = g % 8 == 0  # ~12% playoff games for the playoff spec
        context_rows.append(
            {
                "season": season,
                "game_id": 20000 + g,
                "home_elo_pre": 1500 + rng.normal(0, 30),
                "away_elo_pre": 1500 + rng.normal(0, 30),
                "elo_diff_home": 0.0,
                "home_rest_days": int(rng.integers(1, 4)),
                "away_rest_days": int(rng.integers(1, 4)),
            }
        )
        for is_home, team, opp in ((True, home, away), (False, away, home)):
            state = STATES[g % 3]
            for minute in range(21, 59):
                attempts = int(rng.poisson(0.6))
                panel_rows.append(
                    {
                        "season": season,
                        "game_id": 20000 + g,
                        "is_home": is_home,
                        "is_playoff": is_playoff,
                        "non_5v5_flag": bool(rng.random() < 0.1),
                        "minute": minute,
                        "score_state": state,
                        "attempts_main": attempts,
                        "xg_main": attempts * 0.05,
                        "attempts_5v5_incl_en": attempts,
                        "attempts_all_ex_en": attempts,
                        "attempts_naive": attempts + int(rng.random() < 0.05),
                        "team_code": team,
                        "opp_code": opp,
                    }
                )
    return pd.DataFrame(panel_rows), pd.DataFrame(context_rows)


@pytest.mark.slow
def test_run_main_models_produces_complete_table(synthetic_panel_and_context) -> None:
    panel, context = synthetic_panel_and_context
    table = run_main_models(panel, context)
    assert len(table) == 4  # 2 outcomes x 2 non-reference states
    assert set(table["outcome"]) == {"attempts_main", "xg_main"}
    assert set(table["state"]) == {"tied", "up_1"}
    assert np.isfinite(table[["coef", "se", "pct", "ci_low_pct", "ci_high_pct"]]).all().all()


@pytest.mark.slow
def test_robustness_battery_runs_every_spec(synthetic_panel_and_context) -> None:
    panel, context = synthetic_panel_and_context
    table = run_robustness_battery(panel, context)
    expected_specs = {
        "late_window_55",
        "late_window_56",
        "late_window_57",
        "placebo_period2",
        "placebo_playoffs",
        "naive_all_situations",
        "all_strengths_ex_empty_net",
        "drop_covid_seasons",
        "cluster_team_season",
        "negative_binomial_season_fe",
    }
    assert set(table["spec"]) == expected_specs
    assert np.isfinite(table["pct"]).all()
    # No injected effect -> the main-window tied estimate is a clean null.
    tied_main = table[(table.spec == "late_window_56") & (table.state == "tied")].iloc[0]
    assert tied_main["ci_low_pct"] < 0.0 < tied_main["ci_high_pct"]
