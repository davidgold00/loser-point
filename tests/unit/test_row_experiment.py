"""Unit tests for analysis/row_experiment.py."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
from loserpoint.analysis.row_experiment import (
    build_row_sample,
    extract_row_estimates,
    fit_row_model,
    run_row_experiment,
)


def _panel_and_context(n_games: int = 60, seed: int = 0) -> tuple[pd.DataFrame, pd.DataFrame]:
    rng = np.random.default_rng(seed)
    panel_rows, context_rows = [], []
    for g in range(n_games):
        season = 2007 + (g % 6)  # spans pre- and post-2010 ROW seasons
        state = ("tied", "down_1", "up_1")[g % 3]
        team, opp = f"T{g % 5}", f"T{(g + 1) % 5}"
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


def test_build_row_sample_splits_by_season() -> None:
    panel, context = _panel_and_context()
    sample = build_row_sample(panel, context, post_start_season=2010)
    assert (sample.loc[sample["season"] < 2010, "post_row"] == 0).all()
    assert (sample.loc[sample["season"] >= 2010, "post_row"] == 1).all()
    assert set(sample["tied_late_post"].unique()) <= {0, 1}


def test_fit_row_model_runs() -> None:
    panel, context = _panel_and_context(n_games=120, seed=5)
    sample = build_row_sample(panel, context, post_start_season=2010)
    model = fit_row_model(sample)
    tidy = model.tidy()
    assert "tied_late_post" in tidy.index
    assert "up1_late_post" in tidy.index
    assert np.isfinite(tidy.loc["tied_late_post", "Estimate"])


def test_extract_row_estimates_shape_and_arithmetic() -> None:
    panel, context = _panel_and_context(n_games=140, seed=6)
    sample = build_row_sample(panel, context, post_start_season=2010)
    model = fit_row_model(sample)
    estimates = extract_row_estimates(model)
    assert {e.state for e in estimates} == {"tied", "up_1"}
    for e in estimates:
        assert e.pct == pytest.approx(100 * (np.exp(e.coef) - 1))
        assert e.mde_pct > 0
        assert e.n_obs == len(sample)


def test_run_row_experiment_produces_tidy_table() -> None:
    panel, context = _panel_and_context(n_games=140, seed=7)
    table = run_row_experiment(panel, context, post_start_season=2010)
    assert set(table["state"]) == {"tied", "up_1"}
    assert {"coef", "se", "pvalue", "pct", "ci_low_pct", "ci_high_pct", "mde_pct"} <= set(
        table.columns
    )
    assert np.isfinite(table[["coef", "se", "pct", "mde_pct"]]).all().all()
