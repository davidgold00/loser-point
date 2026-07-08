"""Unit tests for analysis/descriptive.py and the headline figure."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
from loserpoint.analysis.descriptive import (
    ONE_GOAL_LAST_CLEAN_MINUTE,
    analysis_subset,
    headline_contrasts,
    intensity_curves,
)
from loserpoint.viz.figures import divergence_figure


def _toy_panel(n_games: int = 12, seed: int = 0) -> pd.DataFrame:
    """A synthetic panel with known structure: every minute 40-60 exists in
    every state for every game, attempts drawn Poisson around means that
    differ by state.
    """
    rng = np.random.default_rng(seed)
    rows = []
    means = {"tied": 0.6, "down_1": 0.65, "up_1": 0.5}
    for game_id in range(1, n_games + 1):
        for is_home in (True, False):
            for minute in range(40, 61):
                state = list(means)[game_id % 3]
                rows.append(
                    {
                        "season": 2013,
                        "game_id": game_id,
                        "is_home": is_home,
                        "is_playoff": False,
                        "non_5v5_flag": False,
                        "minute": minute,
                        "score_state": state,
                        "attempts_main": int(rng.poisson(means[state])),
                    }
                )
    return pd.DataFrame(rows)


def test_analysis_subset_filters_playoffs_and_non_5v5() -> None:
    panel = _toy_panel()
    panel.loc[panel.index[:10], "is_playoff"] = True
    panel.loc[panel.index[10:20], "non_5v5_flag"] = True
    subset = analysis_subset(panel)
    assert len(subset) == len(panel) - 20
    assert not subset["is_playoff"].any()
    assert not subset["non_5v5_flag"].any()


def test_intensity_curves_shapes_and_truncation() -> None:
    curves = intensity_curves(_toy_panel(), n_boot=20)
    tied = curves[curves["score_state"] == "tied"]
    down = curves[curves["score_state"] == "down_1"]
    # Tied runs through minute 60; one-goal states stop at the last clean
    # minute (decision 0008 artifact 1).
    assert tied["minute"].max() == 60
    assert down["minute"].max() == ONE_GOAL_LAST_CLEAN_MINUTE
    assert (curves["lo"] <= curves["mean"]).all()
    assert (curves["mean"] <= curves["hi"]).all()
    assert (curves["n_obs"] > 0).all()


def test_intensity_curves_recovers_known_means() -> None:
    curves = intensity_curves(_toy_panel(n_games=60, seed=1), n_boot=20)
    for state, expected in (("tied", 0.6), ("down_1", 0.65), ("up_1", 0.5)):
        got = curves[curves["score_state"] == state]["mean"].mean()
        assert got == pytest.approx(expected, abs=0.08)


def test_headline_windows_exclude_contaminated_minutes() -> None:
    # Regression test for bugs_found.md #8: minutes 59-60 must never enter
    # any headline window (they are selection-distorted for one-goal
    # states), even for the tied series, so the three drops are computed
    # over identical windows.
    rows = []
    for state in ("tied", "down_1", "up_1"):
        for minute in range(40, 61):
            # Poison minutes 59-60 with absurd values: if any window
            # includes them, the drop percentages change wildly.
            mean = 100.0 if minute >= 59 else (0.5 if minute >= 56 else 1.0)
            rows.append(
                {
                    "minute": minute,
                    "score_state": state,
                    "mean": mean,
                    "lo": 0,
                    "hi": 200,
                    "n_obs": 10,
                }
            )
    curves = pd.DataFrame(rows)
    contrasts = headline_contrasts(curves)
    for key in ("tied_drop_pct", "down1_drop_pct", "up1_drop_pct"):
        assert contrasts[key] == pytest.approx(-50.0)


def test_divergence_figure_writes_png_and_svg(tmp_path) -> None:
    curves = intensity_curves(_toy_panel(), n_boot=10)
    contrasts = headline_contrasts(curves)
    paths = divergence_figure(curves, contrasts, n_games=12, seasons_label="test", out_dir=tmp_path)
    assert sorted(p.suffix for p in paths) == [".png", ".svg"]
    assert all(p.exists() and p.stat().st_size > 0 for p in paths)
