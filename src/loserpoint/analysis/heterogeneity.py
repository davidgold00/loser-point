"""Pre-registered heterogeneity: where is the turtling strongest?

Three hypotheses, registered in docs/decisions/0014 BEFORE estimation:

* H1 `race`  — both teams within 6 points of the playoff cutline in the
  pre-game standings, second half of the schedule. Predicted: suppression
  STRONGER (`tied x late x race` < 0).
* H2 `intra_division` — both teams in the same division that season.
  Predicted: suppression WEAKER (`tied x late x intra_division` > 0), via
  the direct-rival externality of gifting a seeding rival a point.
* H3 `even` — pre-game Elo gap at or below the sample's median (computed
  over distinct games). Predicted: suppression STRONGER
  (`tied x late x even` < 0).

Each hypothesis is the Phase 3 main specification plus one binary
dimension and its full interaction set, built as explicit dummy products
exactly like analysis/row_experiment.py. All three are reported with MDEs
regardless of sign or significance.
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

BUBBLE_POINTS = 6  # fixed in decision 0014, before estimation

HETEROGENEITY_FORMULA = (
    "attempts_main ~ is_tied + is_up1 + late + dim"
    " + tied_late + up1_late + tied_dim + up1_dim + late_dim"
    " + tied_late_dim + up1_late_dim"
    " + is_home + rest_diff + elo_diff_100 | team_code + opp_code + season"
)


@dataclass(frozen=True)
class HeterogeneityEstimate:
    """One `state x late x dimension` estimate. Negative `pct` means the
    late-game suppression is STRONGER where the dimension is 1."""

    hypothesis: str
    state: str
    coef: float
    se: float
    pvalue: float
    pct: float
    ci_low_pct: float
    ci_high_pct: float
    mde_pct: float
    share_dim: float
    n_obs: int


def add_interaction_dummies(sample: pd.DataFrame, dim: str) -> pd.DataFrame:
    """The explicit dummy products for one dimension column `dim`."""
    out = sample.assign(
        is_tied=(sample["score_state"] == "tied").astype(int),
        is_up1=(sample["score_state"] == "up_1").astype(int),
        dim=sample[dim].astype(int),
    )
    out["tied_late"] = out["is_tied"] * out["late"]
    out["up1_late"] = out["is_up1"] * out["late"]
    out["tied_dim"] = out["is_tied"] * out["dim"]
    out["up1_dim"] = out["is_up1"] * out["dim"]
    out["late_dim"] = out["late"] * out["dim"]
    out["tied_late_dim"] = out["tied_late"] * out["dim"]
    out["up1_late_dim"] = out["up1_late"] * out["dim"]
    return out


def add_intra_division(
    sample: pd.DataFrame, game_results: pd.DataFrame, alignment: pd.DataFrame
) -> pd.DataFrame:
    """H2 dimension: both teams in the same division that season.

    Divisions come from the season-end API standings, so realignment and
    expansion are handled by data (decision 0015). Team codes stay in NHL
    abbreviation space throughout -- the join to the panel is on
    (season, game_id), never on team code.
    """
    games = game_results[["season", "game_id", "home_team", "away_team"]].drop_duplicates()
    div = alignment.set_index(["season", "team"])["division"]
    keyed = games.set_index(["season", "home_team"]).index.map(div)
    games = games.assign(home_division=keyed)
    games["away_division"] = games.set_index(["season", "away_team"]).index.map(div)
    games["intra_division"] = games["home_division"] == games["away_division"]
    return sample.merge(
        games[["season", "game_id", "intra_division"]],
        on=["season", "game_id"],
        how="inner",
        validate="many_to_one",
    )


def add_even_matchup(sample: pd.DataFrame) -> pd.DataFrame:
    """H3 dimension: |Elo gap| at or below the median across distinct games."""
    per_game = sample.groupby("game_key")["elo_diff_100"].first().abs()
    median_gap = per_game.median()
    logger.info("even-matchup split: median |elo_diff_100| = %.3f", median_gap)
    return sample.assign(even=sample["elo_diff_100"].abs() <= median_gap)


def playoff_distance(standings: pd.DataFrame, season_flags: pd.DataFrame) -> pd.DataFrame:
    """Each team's points distance from the playoff cutline, per standings
    date: the 8th-highest point total in the team's conference (4th in the
    division for 2020-21, which had no conferences). Positive = above the
    line. The approximation to the wildcard rule is registered in 0014."""
    flags = season_flags.set_index("season")
    rows = []
    for (date, season), day in standings.groupby(["date", "season"]):
        if flags.loc[season, "conferences_in_use"]:
            group_col, slot = "conference", 8
        else:
            group_col, slot = "division", 4
        for _, group in day.groupby(group_col):
            points = group["points"].sort_values(ascending=False)
            cutline = points.iloc[min(slot, len(points)) - 1]
            rows.append(
                pd.DataFrame(
                    {
                        "date": date,
                        "team": group["team"],
                        "cutline_distance": group["points"] - cutline,
                    }
                )
            )
    return pd.concat(rows, ignore_index=True)


def add_playoff_race(
    sample: pd.DataFrame,
    game_results: pd.DataFrame,
    standings_by_date: pd.DataFrame,
    season_flags: pd.DataFrame,
    second_half_start: pd.Series,
) -> pd.DataFrame:
    """H1 dimension AND sample restriction: second-half games where both
    teams are within BUBBLE_POINTS of the cutline in the previous day's
    standings. Games whose pre-game snapshot is missing are dropped (with
    a count logged) rather than imputed."""
    games = game_results[["season", "game_id", "date", "home_team", "away_team"]].copy()
    games["date_ts"] = pd.to_datetime(games["date"])
    games = games[games["date_ts"] >= games["season"].map(second_half_start)]
    games["pregame_date"] = (games["date_ts"] - pd.Timedelta(days=1)).dt.strftime("%Y-%m-%d")

    distance = playoff_distance(standings_by_date, season_flags)
    keyed = distance.set_index(["date", "team"])["cutline_distance"]
    games["home_distance"] = games.set_index(["pregame_date", "home_team"]).index.map(keyed)
    games["away_distance"] = games.set_index(["pregame_date", "away_team"]).index.map(keyed)

    missing = games["home_distance"].isna() | games["away_distance"].isna()
    if missing.any():
        logger.warning(
            "playoff-race dimension: dropping %d second-half games with no "
            "pre-game standings snapshot.",
            int(missing.sum()),
        )
        games = games[~missing]
    games["race"] = (games["home_distance"].abs() <= BUBBLE_POINTS) & (
        games["away_distance"].abs() <= BUBBLE_POINTS
    )
    merged = sample.merge(
        games[["season", "game_id", "race"]],
        on=["season", "game_id"],
        how="inner",
        validate="many_to_one",
    )
    logger.info(
        "playoff-race sample: %d rows (%d games), race share %.1f%%",
        len(merged),
        merged["game_key"].nunique(),
        100 * merged["race"].mean(),
    )
    return merged


def fit_heterogeneity_model(sample: pd.DataFrame):
    return pf.fepois(HETEROGENEITY_FORMULA, data=sample, vcov={"CRV1": "game_key"})


def extract_estimates(model, *, hypothesis: str, share_dim: float) -> list[HeterogeneityEstimate]:
    tidy = model.tidy()
    estimates = []
    for state, term in (("tied", "tied_late_dim"), ("up_1", "up1_late_dim")):
        row = tidy.loc[term]
        coef = float(row["Estimate"])
        se = float(row["Std. Error"])
        estimates.append(
            HeterogeneityEstimate(
                hypothesis=hypothesis,
                state=state,
                coef=coef,
                se=se,
                pvalue=float(row["Pr(>|t|)"]),
                pct=float(100 * (np.exp(coef) - 1)),
                ci_low_pct=float(100 * (np.exp(coef - 1.96 * se) - 1)),
                ci_high_pct=float(100 * (np.exp(coef + 1.96 * se) - 1)),
                mde_pct=float(100 * (np.exp(minimum_detectable_effect(se)) - 1)),
                share_dim=share_dim,
                n_obs=int(model._N),
            )
        )
    return estimates


def run_heterogeneity(
    game_minutes: pd.DataFrame,
    context: pd.DataFrame,
    game_results: pd.DataFrame,
    alignment: pd.DataFrame,
    standings_by_date: pd.DataFrame,
    season_flags: pd.DataFrame,
    second_half_start: pd.Series,
) -> pd.DataFrame:
    """All three pre-registered hypotheses; one tidy row per estimate."""
    base = build_estimation_sample(game_minutes, context)

    prepared = {
        "race": add_playoff_race(
            base, game_results, standings_by_date, season_flags, second_half_start
        ).rename(columns={"race": "_dim"}),
        "intra_division": add_intra_division(base, game_results, alignment).rename(
            columns={"intra_division": "_dim"}
        ),
        "even": add_even_matchup(base).rename(columns={"even": "_dim"}),
    }

    all_estimates: list[HeterogeneityEstimate] = []
    for hypothesis, sample in prepared.items():
        with_dummies = add_interaction_dummies(sample, "_dim")
        model = fit_heterogeneity_model(with_dummies)
        share = float(with_dummies["dim"].mean())
        estimates = extract_estimates(model, hypothesis=hypothesis, share_dim=share)
        for est in estimates:
            logger.info(
                "heterogeneity %s | %s x late x dim: %+.1f%% (95%% CI %.1f to %.1f, "
                "p=%.4f, MDE ~%.1f%%, dim share %.1f%%)",
                hypothesis,
                est.state,
                est.pct,
                est.ci_low_pct,
                est.ci_high_pct,
                est.pvalue,
                est.mde_pct,
                100 * est.share_dim,
            )
        all_estimates.extend(estimates)
    return pd.DataFrame([vars(e) for e in all_estimates])


def main() -> None:
    from pathlib import Path

    from loserpoint.ingest.nhl_api import NHLApiClient, season_second_half_start_dates
    from loserpoint.utils.io import write_parquet

    game_minutes = pd.read_parquet("data/processed/game_minutes.parquet")
    context = pd.read_parquet("data/processed/game_context.parquet")
    game_results = pd.read_parquet("data/interim/nhl_api/game_results.parquet")
    official = pd.read_parquet("data/interim/nhl_api/season_end_standings.parquet")
    standings_by_date = pd.read_parquet("data/interim/nhl_api/standings_by_date.parquet")

    seasons = sorted(game_results["season"].unique())
    manifest = NHLApiClient(Path("data/raw/nhl_api")).season_manifest()
    by_id = {entry["id"]: entry for entry in manifest}
    season_flags = pd.DataFrame(
        {
            "season": season,
            "conferences_in_use": by_id[season * 10000 + season + 1]["conferencesInUse"],
        }
        for season in seasons
    )

    table = run_heterogeneity(
        game_minutes,
        context,
        game_results,
        official[["season", "team", "conference", "division"]],
        standings_by_date,
        season_flags,
        season_second_half_start_dates(game_results),
    )
    write_parquet(table, Path("data/processed/heterogeneity.parquet"))


if __name__ == "__main__":
    main()
