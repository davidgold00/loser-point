"""The 2010-11 ROW-tiebreaker natural experiment.

Starting in 2010-11, "regulation + overtime wins" (ROW) became the NHL's
first tiebreaker for teams level on points -- a shootout win counts less
than a regulation/OT win when the standings are tied. This partially
repairs the loser-point distortion: a team that turtles to a shootout win
now risks losing a tiebreaker to a team that wins the same number of games
in regulation. If the turtling behavior documented in Phase 3 is a
response to the point *system* rather than pure risk-aversion, the ROW
change should measurably attenuate it.

This reuses Phase 3's main-model machinery on the modern shot-attempt
panel (unlike regime_did.py, no separate outcome definition is needed --
2007-2025 all has MoneyPuck shot data) with the same explicit-dummy,
three-way-interaction approach as regime_did.py: state x late x post_row.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
import pyfixest as pf

from loserpoint.analysis.models import build_estimation_sample
from loserpoint.analysis.regime_did import minimum_detectable_effect
from loserpoint.utils.logging import get_logger

logger = get_logger(__name__)

ROW_FORMULA = (
    "attempts_main ~ is_tied + is_up1 + late + post_row"
    " + tied_late + up1_late + tied_post + up1_post + late_post"
    " + tied_late_post + up1_late_post"
    " + is_home + rest_diff + elo_diff_100 | team_code + opp_code + season"
)


@dataclass(frozen=True)
class RowEstimate:
    """One ROW-regime interaction estimate; same interpretation as
    RegimeEstimate in regime_did.py, but on the modern shot-attempt panel.
    A negative `pct` for tied means turtling INTENSIFIED after ROW
    (contrary to the repair hypothesis); positive means it ATTENUATED
    (consistent with the repair hypothesis)."""

    state: str
    coef: float
    se: float
    pvalue: float
    pct: float
    ci_low_pct: float
    ci_high_pct: float
    mde_pct: float
    n_obs: int


def build_row_sample(
    game_minutes: pd.DataFrame,
    context: pd.DataFrame,
    *,
    post_start_season: int,
) -> pd.DataFrame:
    """Assemble the ROW-experiment sample: Phase 3's estimation sample
    (build_estimation_sample) with the regime dummies added."""
    sample = build_estimation_sample(game_minutes, context)
    sample = sample.assign(
        is_tied=(sample["score_state"] == "tied").astype(int),
        is_up1=(sample["score_state"] == "up_1").astype(int),
        post_row=(sample["season"] >= post_start_season).astype(int),
    )
    sample["tied_late"] = sample["is_tied"] * sample["late"]
    sample["up1_late"] = sample["is_up1"] * sample["late"]
    sample["tied_post"] = sample["is_tied"] * sample["post_row"]
    sample["up1_post"] = sample["is_up1"] * sample["post_row"]
    sample["late_post"] = sample["late"] * sample["post_row"]
    sample["tied_late_post"] = sample["is_tied"] * sample["late"] * sample["post_row"]
    sample["up1_late_post"] = sample["is_up1"] * sample["late"] * sample["post_row"]
    logger.info(
        "ROW sample: %d rows, pre-ROW=%d post-ROW=%d (split at season %d)",
        len(sample),
        int((sample["post_row"] == 0).sum()),
        int((sample["post_row"] == 1).sum()),
        post_start_season,
    )
    return sample


def fit_row_model(sample: pd.DataFrame):
    return pf.fepois(ROW_FORMULA, data=sample, vcov={"CRV1": "game_key"})


def extract_row_estimates(model) -> list[RowEstimate]:
    tidy = model.tidy()
    estimates = []
    for state, term in (("tied", "tied_late_post"), ("up_1", "up1_late_post")):
        row = tidy.loc[term]
        coef = float(row["Estimate"])
        se = float(row["Std. Error"])
        estimates.append(
            RowEstimate(
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


def run_row_experiment(
    game_minutes: pd.DataFrame, context: pd.DataFrame, *, post_start_season: int
) -> pd.DataFrame:
    sample = build_row_sample(game_minutes, context, post_start_season=post_start_season)
    model = fit_row_model(sample)
    estimates = extract_row_estimates(model)
    for est in estimates:
        logger.info(
            "ROW experiment | %s x late x post-ROW: %+.1f%% (95%% CI %.1f to %.1f, "
            "p=%.4f, MDE ~%.1f%%)",
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
    game_minutes = pd.read_parquet("data/processed/game_minutes.parquet")
    context = pd.read_parquet("data/processed/game_context.parquet")
    table = run_row_experiment(
        game_minutes, context, post_start_season=config.regime_split["row_post_start_season"]
    )
    write_parquet(table, Path("data/processed/row_experiment.parquet"))


if __name__ == "__main__":
    main()
