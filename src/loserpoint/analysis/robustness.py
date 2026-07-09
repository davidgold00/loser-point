"""Robustness battery for the main model.

Every entry re-runs the exact production estimation code
(build_estimation_sample + fit_main_model + extract_estimates) under one
perturbation, so a robustness row can never silently drift from the main
specification. Output is one tidy table: spec x outcome x state.

The battery (see docs/methodology.md for predicted signs):
- late-window sensitivity: late = 55/56/57 onward (within the minute-58
  sample boundary of decision 0008);
- second-period placebo: the same design run on minutes 21-38 with a fake
  "late" window at 36-38 -- no OT point is bankable from the second
  period, so the tied differential should vanish;
- playoff placebo: playoff games only -- there is no loser point in the
  playoffs, so the tied differential should vanish or attenuate sharply;
- empty-net policy variants: 5v5-including-EN and fully naive counts
  (mode (b) of config.yaml -- dropping minutes 59-60 -- is already the
  primary sample's boundary, so it needs no separate row);
- COVID exclusion: drop the pandemic-shortened 2019 and 2020 seasons;
- alternative clustering: team-season instead of game;
- overdispersion check: negative binomial (NB2) with season dummies only.
  NB2 with full team/opponent FE is computationally hostile in
  statsmodels; since the NB row exists only to show the interaction is
  not a Poisson-variance artifact, the slimmer FE set is acceptable and
  is labeled as such.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from loserpoint.analysis.models import (
    build_estimation_sample,
    extract_estimates,
    fit_main_model,
)
from loserpoint.utils.logging import get_logger

logger = get_logger(__name__)

COVID_SEASONS = (2019, 2020)


def _rows(model, outcome: str, spec: str) -> list[dict]:
    return [dict(vars(e), spec=spec) for e in extract_estimates(model, outcome=outcome)]


def run_robustness_battery(game_minutes: pd.DataFrame, context: pd.DataFrame) -> pd.DataFrame:
    """Run every robustness specification; returns the tidy results table.

    Interpretation: the loser-point reading survives if (a) the tied x late
    differential is stable across late windows, EN policies, clustering,
    and season exclusions, and (b) it disappears in the two placebos,
    where the incentive it measures does not exist.
    """
    results: list[dict] = []

    # -- late-window sensitivity ------------------------------------------
    for late_start in (55, 56, 57):
        sample = build_estimation_sample(game_minutes, context, late_start=late_start)
        model = fit_main_model(sample)
        results += _rows(model, "attempts_main", f"late_window_{late_start}")

    # -- second-period placebo --------------------------------------------
    placebo = build_estimation_sample(
        game_minutes, context, first_minute=21, last_minute=38, late_start=36
    )
    results += _rows(fit_main_model(placebo), "attempts_main", "placebo_period2")

    # -- playoff placebo ----------------------------------------------------
    playoff_rows = game_minutes[game_minutes["is_playoff"]]
    playoff = build_estimation_sample(playoff_rows, context, include_playoffs=True)
    results += _rows(fit_main_model(playoff), "attempts_main", "placebo_playoffs")

    # -- empty-net / situation policy variants -------------------------------
    # Within the primary sample (5v5-flagged minutes through 58) the four
    # count columns are nearly identical by construction -- a 5v5 minute
    # before minute 59 contains almost no empty-net shots. The informative
    # sensitivity therefore INCLUDES the non-5v5 minutes and varies the
    # count column: naive counts everything; all_ex_en keeps all strengths
    # but applies the empty-net exclusion.
    main_sample = build_estimation_sample(game_minutes, context)
    all_minutes = build_estimation_sample(game_minutes, context, include_non_5v5=True)
    for outcome, spec in (
        ("attempts_naive", "naive_all_situations"),
        ("attempts_all_ex_en", "all_strengths_ex_empty_net"),
    ):
        results += _rows(fit_main_model(all_minutes, outcome=outcome), outcome, spec)

    # -- drop COVID-shortened seasons ----------------------------------------
    no_covid = build_estimation_sample(
        game_minutes[~game_minutes["season"].isin(COVID_SEASONS)], context
    )
    results += _rows(fit_main_model(no_covid), "attempts_main", "drop_covid_seasons")

    # -- alternative clustering ----------------------------------------------
    import pyfixest as pf

    from loserpoint.analysis.models import FORMULA, REFERENCE_STATE

    clustered = main_sample.assign(
        team_season=main_sample["team_code"] + "_" + main_sample["season"].astype(str)
    )
    model_ts = pf.fepois(
        FORMULA.format(outcome="attempts_main", ref=REFERENCE_STATE),
        data=clustered,
        vcov={"CRV1": "team_season"},
    )
    results += _rows(model_ts, "attempts_main", "cluster_team_season")

    # -- negative binomial overdispersion check -------------------------------
    results += _negative_binomial_check(main_sample)

    table = pd.DataFrame(results)
    logger.info("robustness battery: %d rows across %d specs", len(table), table["spec"].nunique())
    return table


def _negative_binomial_check(sample: pd.DataFrame) -> list[dict]:
    """NB2 with season dummies only (see module docstring for why the FE
    set is slimmer here). Reported for the tied and up_1 interactions."""
    import statsmodels.formula.api as smf

    df = sample.copy()
    df["tied_late"] = ((df["score_state"] == "tied") & (df["late"] == 1)).astype(int)
    df["up1_late"] = ((df["score_state"] == "up_1") & (df["late"] == 1)).astype(int)
    model = smf.negativebinomial(
        "attempts_main ~ tied_late + up1_late + C(score_state) + late"
        " + is_home + rest_diff + elo_diff_100 + C(season)",
        data=df,
    ).fit(disp=0)
    rows = []
    for state, term in (("tied", "tied_late"), ("up_1", "up1_late")):
        coef = float(model.params[term])
        se = float(model.bse[term])
        rows.append(
            {
                "outcome": "attempts_main",
                "state": state,
                "coef": coef,
                "se": se,
                "pvalue": float(model.pvalues[term]),
                "irr": float(np.exp(coef)),
                "pct": float(100 * (np.exp(coef) - 1)),
                "ci_low_pct": float(100 * (np.exp(coef - 1.96 * se) - 1)),
                "ci_high_pct": float(100 * (np.exp(coef + 1.96 * se) - 1)),
                "n_obs": int(model.nobs),
                "spec": "negative_binomial_season_fe",
            }
        )
    return rows


def main() -> None:
    from pathlib import Path

    from loserpoint.utils.io import write_parquet

    game_minutes = pd.read_parquet("data/processed/game_minutes.parquet")
    context = pd.read_parquet("data/processed/game_context.parquet")
    table = run_robustness_battery(game_minutes, context)
    write_parquet(table, Path("data/processed/robustness.parquet"))


if __name__ == "__main__":
    main()
