"""Unit tests for analysis/regime_did.py."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
from loserpoint.analysis.regime_did import (
    build_regime_sample,
    extract_regime_estimates,
    fit_regime_model,
    minimum_detectable_effect,
    run_regime_did,
)


def test_minimum_detectable_effect_grows_with_se() -> None:
    small = minimum_detectable_effect(0.05)
    large = minimum_detectable_effect(0.20)
    assert 0 < small < large


def test_minimum_detectable_effect_matches_known_multiplier() -> None:
    # z_{0.975} + z_{0.80} = 1.9600 + 0.8416 = 2.8016 (Cohen 1988).
    mde = minimum_detectable_effect(1.0, power=0.8, alpha=0.05)
    assert mde == pytest.approx(2.8016, abs=1e-3)


def _historical_panel(n_games: int, seed: int = 0) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    rows = []
    for g in range(n_games):
        season = 1999 + (g % 8)  # spans the full historical window
        state = ("tied", "down_1", "up_1")[g % 3]
        team = f"T{g % 6}"
        opp = f"T{(g + 1) % 6}"
        for is_home in (True, False):
            for minute in range(41, 61):
                rows.append(
                    {
                        "season": season,
                        "game_key": f"game{g}",
                        "is_home": is_home,
                        "team_code": team if is_home else opp,
                        "opp_code": opp if is_home else team,
                        "minute": minute,
                        "score_state": state,
                        "goals_for": int(rng.poisson(0.04)),
                    }
                )
    return pd.DataFrame(rows)


def test_build_regime_sample_shapes_and_splits() -> None:
    panel = _historical_panel(24)
    sample = build_regime_sample(panel, post_start_season=2005)
    assert sample["minute"].min() == 41
    assert set(sample["post"].unique()) == {0, 1}
    # pre = seasons 1999-2004 (6 of 8), post = 2005-2006 (2 of 8)
    assert (sample.loc[sample["season"] < 2005, "post"] == 0).all()
    assert (sample.loc[sample["season"] >= 2005, "post"] == 1).all()
    assert set(sample["tied_late_post"].unique()) <= {0, 1}


def test_build_regime_sample_drops_up2plus_and_down2plus() -> None:
    panel = _historical_panel(6)
    panel.loc[panel.index[:5], "score_state"] = "up_2_plus"
    sample = build_regime_sample(panel, post_start_season=2005)
    assert "up_2_plus" not in sample["score_state"].values


def test_fit_regime_model_runs_and_recovers_dummies() -> None:
    panel = _historical_panel(60, seed=3)
    sample = build_regime_sample(panel, post_start_season=2005)
    model = fit_regime_model(sample)
    tidy = model.tidy()
    assert "tied_late_post" in tidy.index
    assert "up1_late_post" in tidy.index
    assert np.isfinite(tidy.loc["tied_late_post", "Estimate"])


def test_extract_regime_estimates_shape_and_arithmetic() -> None:
    panel = _historical_panel(80, seed=4)
    sample = build_regime_sample(panel, post_start_season=2005)
    model = fit_regime_model(sample)
    estimates = extract_regime_estimates(model)
    assert {e.state for e in estimates} == {"tied", "up_1"}
    for e in estimates:
        assert e.pct == pytest.approx(100 * (np.exp(e.coef) - 1))
        assert e.mde_pct > 0  # MDE is always a positive-side detectable magnitude
        assert e.n_obs == len(sample)


def test_run_regime_did_produces_tidy_table() -> None:
    panel = _historical_panel(80, seed=5)
    table = run_regime_did(panel, post_start_season=2005)
    assert set(table["state"]) == {"tied", "up_1"}
    assert {"coef", "se", "pvalue", "pct", "ci_low_pct", "ci_high_pct", "mde_pct"} <= set(
        table.columns
    )
    assert np.isfinite(table[["coef", "se", "pct", "mde_pct"]]).all().all()
