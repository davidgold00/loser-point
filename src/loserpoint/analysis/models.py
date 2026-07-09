"""Main estimation: fixed-effects Poisson on team-minute shot output.

The estimand, in plain English: *how much more do tied teams cut their
late-game offense than down-one teams do?* Down-one teams are the
reference state because they have nothing banked (a regulation loss is 0
points either way), so their late-game behavior is the cleanest available
benchmark for "how teams play when only winning matters." The loser-point
hypothesis says tied teams -- who can lock in 1 point by reaching overtime
-- pull back relative to that benchmark.

Specification (per docs/methodology.md):

    attempts ~ state x late + state + late + home + rest_diff + elo_diff
               | team FE + opponent FE + season FE,   SEs clustered by game

estimated as Poisson QMLE (pyfixest.fepois) on the game x team x minute
panel, third period through minute 58 (minutes 59-60 are excluded from the
primary sample because goalie pulls destroy the one-goal states' 5v5
sample there -- decision 0008). The xG variant re-runs the identical
specification with the xG sum as the outcome; Poisson QMLE is consistent
for any non-negative outcome (Gourieroux-Monfort-Trognon / Santos
Silva-Tenreyro), so no separate gamma machinery is needed.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
import pyfixest as pf

from loserpoint.utils.logging import get_logger

logger = get_logger(__name__)

MODEL_STATES = ("down_1", "tied", "up_1")
REFERENCE_STATE = "down_1"
DEFAULT_FIRST_MINUTE = 41
DEFAULT_LAST_MINUTE = 58
DEFAULT_LATE_START = 56

FORMULA = (
    "{outcome} ~ i(score_state, late, ref='{ref}') + score_state + late"
    " + is_home + rest_diff + elo_diff_100 | team_code + opp_code + season"
)


@dataclass(frozen=True)
class MainEstimate:
    """One interaction estimate from the main model.

    Interpretation: `irr` is the incidence-rate ratio -- tied teams'
    late-window shot output changes by a factor of `irr` MORE than
    down-one teams' does (e.g. irr=0.94 reads "tied teams cut attempts 6%
    more than down-one teams over the same minutes"). `pct` is
    100*(irr-1), the interview-friendly version.
    """

    outcome: str
    state: str
    coef: float
    se: float
    pvalue: float
    irr: float
    pct: float
    ci_low_pct: float
    ci_high_pct: float
    n_obs: int


def build_estimation_sample(
    game_minutes: pd.DataFrame,
    context: pd.DataFrame,
    *,
    first_minute: int = DEFAULT_FIRST_MINUTE,
    last_minute: int = DEFAULT_LAST_MINUTE,
    late_start: int = DEFAULT_LATE_START,
    states: tuple[str, ...] = MODEL_STATES,
    include_playoffs: bool = False,
    include_non_5v5: bool = False,
) -> pd.DataFrame:
    """Assemble the model-ready sample from the panel plus game context.

    Args:
        game_minutes: the game x team x minute panel.
        context: per-game Elo/rest table from panel.context (joined on
            season + game_id; panel rows without context -- games the NHL
            API doesn't know -- are dropped with a warning).
        first_minute/last_minute: sample window (third period through 58
            by default; see module docstring for why not 60).
        late_start: first minute of the late window ("late" dummy).
        states: score states retained.
        include_playoffs / include_non_5v5: robustness switches; the
            primary sample excludes both.

    Returns:
        One row per team-minute with the model's columns, including
        `late`, `rest_diff` (own minus opponent rest days), `elo_diff_100`
        (own minus opponent pre-game Elo, in hundreds), and `game_key`
        (the cluster variable).
    """
    rows = game_minutes[
        game_minutes["minute"].between(first_minute, last_minute)
        & game_minutes["score_state"].isin(states)
    ]
    if not include_playoffs:
        rows = rows[~rows["is_playoff"]]
    if not include_non_5v5:
        rows = rows[~rows["non_5v5_flag"]]

    merged = rows.merge(context, on=["season", "game_id"], how="left", validate="many_to_one")
    missing = merged["home_elo_pre"].isna()
    if missing.any():
        n_games = merged.loc[missing, ["season", "game_id"]].drop_duplicates()
        logger.warning(
            "dropping %d team-minute rows from %d games with no NHL API context "
            "(games the API schedule doesn't carry).",
            int(missing.sum()),
            len(n_games),
        )
        merged = merged[~missing]

    own_elo = np.where(merged["is_home"], merged["home_elo_pre"], merged["away_elo_pre"])
    opp_elo = np.where(merged["is_home"], merged["away_elo_pre"], merged["home_elo_pre"])
    own_rest = np.where(merged["is_home"], merged["home_rest_days"], merged["away_rest_days"])
    opp_rest = np.where(merged["is_home"], merged["away_rest_days"], merged["home_rest_days"])

    sample = merged.assign(
        late=(merged["minute"] >= late_start).astype(int),
        elo_diff_100=(own_elo - opp_elo) / 100.0,
        rest_diff=own_rest - opp_rest,
        is_home=merged["is_home"].astype(int),
        game_key=merged["season"].astype(int) * 1_000_000 + merged["game_id"].astype(int),
    )
    logger.info(
        "estimation sample: %d team-minute rows, %d games, minutes %d-%d (late >= %d)",
        len(sample),
        sample["game_key"].nunique(),
        first_minute,
        last_minute,
        late_start,
    )
    return sample


def fit_main_model(sample: pd.DataFrame, *, outcome: str = "attempts_main"):
    """Fit the FE-Poisson specification; returns the pyfixest model object."""
    formula = FORMULA.format(outcome=outcome, ref=REFERENCE_STATE)
    model = pf.fepois(formula, data=sample, vcov={"CRV1": "game_key"})
    logger.info("fit %s on %d rows: %s", outcome, model._N, formula)
    return model


def extract_estimates(model, *, outcome: str) -> list[MainEstimate]:
    """Pull the state x late interaction rows out of a fitted model.

    Interpretation note: with down_1 as the reference, the coefficient
    `score_state::tied:late` IS the difference-in-differences -- (tied
    late vs tied mid) minus (down-1 late vs down-1 mid) -- in log points.
    """
    tidy = model.tidy()
    estimates = []
    for state in MODEL_STATES:
        if state == REFERENCE_STATE:
            continue
        row = tidy.loc[f"score_state::{state}:late"]
        coef = float(row["Estimate"])
        se = float(row["Std. Error"])
        estimates.append(
            MainEstimate(
                outcome=outcome,
                state=state,
                coef=coef,
                se=se,
                pvalue=float(row["Pr(>|t|)"]),
                irr=float(np.exp(coef)),
                pct=float(100 * (np.exp(coef) - 1)),
                ci_low_pct=float(100 * (np.exp(coef - 1.96 * se) - 1)),
                ci_high_pct=float(100 * (np.exp(coef + 1.96 * se) - 1)),
                n_obs=int(model._N),
            )
        )
    return estimates


def run_main_models(game_minutes: pd.DataFrame, context: pd.DataFrame) -> pd.DataFrame:
    """The paper's main table: attempts and xG variants of the main spec.

    Returns:
        Tidy DataFrame of MainEstimate rows (one per non-reference state
        per outcome), written to data/processed/main_estimates.parquet by
        the module CLI.
    """
    sample = build_estimation_sample(game_minutes, context)
    all_estimates: list[MainEstimate] = []
    for outcome in ("attempts_main", "xg_main"):
        model = fit_main_model(sample, outcome=outcome)
        estimates = extract_estimates(model, outcome=outcome)
        for est in estimates:
            logger.info(
                "%s | %s x late: %+.1f%% vs down-1 (95%% CI %.1f to %.1f, p=%.4f)",
                outcome,
                est.state,
                est.pct,
                est.ci_low_pct,
                est.ci_high_pct,
                est.pvalue,
            )
        all_estimates.extend(estimates)
    return pd.DataFrame([vars(e) for e in all_estimates])


def main() -> None:
    from pathlib import Path

    from loserpoint.utils.io import write_parquet

    game_minutes = pd.read_parquet("data/processed/game_minutes.parquet")
    context = pd.read_parquet("data/processed/game_context.parquet")
    estimates = run_main_models(game_minutes, context)
    write_parquet(estimates, Path("data/processed/main_estimates.parquet"))


if __name__ == "__main__":
    main()
