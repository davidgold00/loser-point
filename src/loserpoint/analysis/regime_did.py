"""Regime difference-in-differences: did the tied-late differential
change after the 2005 shootout?

The historical panel (ingest/hockey_reference.py) has no shot-location
data, so the outcome here is goals per team-minute, not shot attempts --
the only outcome available before 2007-08. The specification mirrors
Phase 3's main model (down-1 as reference state, since it has nothing
banked under either regime) but adds a third interaction dimension: the
regime itself.

Because state x late x regime is a three-way interaction, it is built as
explicit dummy products rather than fought into pyfixest's `i()` syntax
(which is designed for two-way interactions). The coefficient of interest,
`tied_late_post`, is the DiD-in-DiD: how much MORE the tied-late goal
suppression changed from the pre-shootout to the post-shootout regime,
beyond what the main effects alone predict.

Goals are rare per team-minute (a few percent), so this design is
underpowered relative to the shot-attempt models -- `minimum_detectable_effect`
reports what the achieved sample could actually detect, per the project's
pre-registered commitment to disclose this honestly rather than only
reporting a point estimate.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
import pyfixest as pf
from scipy import stats

from loserpoint.utils.logging import get_logger

logger = get_logger(__name__)

MODEL_STATES = ("down_1", "tied", "up_1")
REFERENCE_STATE = "down_1"
DEFAULT_LATE_START = 56

REGIME_FORMULA = (
    "goals_for ~ is_tied + is_up1 + late + post"
    " + tied_late + up1_late + tied_post + up1_post + late_post"
    " + tied_late_post + up1_late_post | team_code + season"
)


@dataclass(frozen=True)
class RegimeEstimate:
    """One regime-interaction estimate.

    Interpretation: `pct` is the percentage change in the tied (or up-1)
    late-window goal rate, ATTRIBUTABLE TO THE REGIME CHANGE, beyond the
    pooled pre+post tied/up-1-late effect already captured by
    `tied_late`/`up1_late`. A positive `pct` for tied means the shootout
    era shows LESS additional suppression than the pre-shootout era
    (attenuation); negative means MORE (intensification) -- the
    pre-registered prediction (decision 0009 / original methodology) was
    intensification.
    """

    state: str
    coef: float
    se: float
    pvalue: float
    pct: float
    ci_low_pct: float
    ci_high_pct: float
    mde_pct: float
    n_obs: int


def minimum_detectable_effect(se: float, *, power: float = 0.8, alpha: float = 0.05) -> float:
    """The smallest true log-effect this sample could detect at the given
    power and significance level, given the model's own standard error.

    Interpretation: report this alongside every regime estimate. A
    statistically null result with a wide MDE (e.g. "could not have
    detected anything smaller than a 25% change") is a very different
    finding from a null result with a narrow MDE (e.g. "we could detect
    changes as small as 3% and found none") -- the first is inconclusive,
    the second is informative. Standard formula: MDE = (z_{1-alpha/2} +
    z_power) * SE (Cohen 1988).
    """
    z_alpha = stats.norm.ppf(1 - alpha / 2)
    z_power = stats.norm.ppf(power)
    return (z_alpha + z_power) * se


def build_regime_sample(
    historical_panel: pd.DataFrame,
    *,
    post_start_season: int,
    late_start: int = DEFAULT_LATE_START,
    states: tuple[str, ...] = MODEL_STATES,
) -> pd.DataFrame:
    """Assemble the regime-DiD sample from the historical game-minute panel.

    Args:
        historical_panel: output of
            ingest.hockey_reference.build_historical_panel (season,
            game_key, is_home, minute, score_state, score_diff, goals_for).
        post_start_season: first season of the "post" (shootout) regime;
            everything before it is "pre".
        late_start: first minute of the late window (56 by default,
            matching the modern main spec).
        states: score states retained (down_1 is dropped as the reference
            after building the dummies).

    Returns:
        One row per team-minute (minutes 41-60 of the historical panel,
        i.e. the full third period -- there is no goalie-pull-driven 5v5
        collapse issue here since the historical outcome is goals, not
        shots, and this project bins goals across all situations for the
        pre-tracking era) with the dummy columns REGIME_FORMULA needs.
    """
    rows = historical_panel[
        (historical_panel["minute"] >= 41) & historical_panel["score_state"].isin(states)
    ].copy()
    rows["is_tied"] = (rows["score_state"] == "tied").astype(int)
    rows["is_up1"] = (rows["score_state"] == "up_1").astype(int)
    rows["late"] = (rows["minute"] >= late_start).astype(int)
    rows["post"] = (rows["season"] >= post_start_season).astype(int)
    rows["tied_late"] = rows["is_tied"] * rows["late"]
    rows["up1_late"] = rows["is_up1"] * rows["late"]
    rows["tied_post"] = rows["is_tied"] * rows["post"]
    rows["up1_post"] = rows["is_up1"] * rows["post"]
    rows["late_post"] = rows["late"] * rows["post"]
    rows["tied_late_post"] = rows["is_tied"] * rows["late"] * rows["post"]
    rows["up1_late_post"] = rows["is_up1"] * rows["late"] * rows["post"]
    logger.info(
        "regime sample: %d team-minute rows, %d games, pre=%d post=%d (split at %d)",
        len(rows),
        rows["game_key"].nunique(),
        int((rows["post"] == 0).sum()),
        int((rows["post"] == 1).sum()),
        post_start_season,
    )
    return rows


def fit_regime_model(sample: pd.DataFrame):
    return pf.fepois(REGIME_FORMULA, data=sample, vcov={"CRV1": "game_key"})


def extract_regime_estimates(model) -> list[RegimeEstimate]:
    tidy = model.tidy()
    estimates = []
    for state, term in (("tied", "tied_late_post"), ("up_1", "up1_late_post")):
        row = tidy.loc[term]
        coef = float(row["Estimate"])
        se = float(row["Std. Error"])
        estimates.append(
            RegimeEstimate(
                state=state,
                coef=coef,
                se=se,
                pvalue=float(row["Pr(>|t|)"]),
                pct=float(100 * (np.exp(coef) - 1)),
                ci_low_pct=float(100 * (np.exp(coef - 1.96 * se) - 1)),
                ci_high_pct=float(100 * (np.exp(coef + 1.96 * se) - 1)),
                mde_pct=float(100 * (np.exp(minimum_detectable_effect(se)) - 1)),
                n_obs=int(model._N),
            )
        )
    return estimates


def run_regime_did(historical_panel: pd.DataFrame, *, post_start_season: int) -> pd.DataFrame:
    """The regime-DiD headline table: one row per state's triple interaction."""
    sample = build_regime_sample(historical_panel, post_start_season=post_start_season)
    model = fit_regime_model(sample)
    estimates = extract_regime_estimates(model)
    for est in estimates:
        logger.info(
            "regime DiD | %s x late x post: %+.1f%% (95%% CI %.1f to %.1f, p=%.4f, MDE ~%.1f%%)",
            est.state,
            est.pct,
            est.ci_low_pct,
            est.ci_high_pct,
            est.pvalue,
            est.mde_pct,
        )
    return pd.DataFrame([vars(e) for e in estimates])


def main() -> None:
    from pathlib import Path

    from loserpoint.utils.config import load_config
    from loserpoint.utils.io import write_parquet

    config = load_config()
    panel = pd.read_parquet("data/interim/hockey_reference/game_minutes.parquet")
    table = run_regime_did(
        panel, post_start_season=config.regime_split["historical_post_start_season"]
    )
    write_parquet(table, Path("data/processed/regime_did.parquet"))


if __name__ == "__main__":
    main()
