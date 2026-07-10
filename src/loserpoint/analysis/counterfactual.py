"""Counterfactual standings: what the league table looks like if the same
game outcomes are scored under a different point system.

This is the mechanical half of the policy question (the memo's
"flipped-playoff-berth counts and standings deltas"). It holds every game
outcome fixed and re-scores the season under alternative rules, so it
deliberately does NOT model the behavioral response the rest of this
project measures -- if the loser point were removed, teams would play
tied-late minutes differently, and the standings would shift further.
That Lucas-critique caveat is stated wherever these numbers are reported
(docs/methodology.md item 10).

Point systems compared (decision 0015):

* ``actual``          -- 2 any win / 1 OT-SO loss / 0 regulation loss
* ``three_two_one``   -- 3 regulation win / 2 OT-SO win / 1 OT-SO loss / 0
* ``no_loser_point``  -- 2 any win / 0 any loss (pre-1999 scoring, minus ties)

Game outcomes come from the NHL API results table (not MoneyPuck): it
shares the standings' team-abbreviation space and its final scores are the
project's cross-source ground truth. The computed actual-rules standings
are validated against the API's official season-end standings before any
counterfactual number is trusted (``validate_actual_standings``).
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from loserpoint.utils.logging import get_logger

logger = get_logger(__name__)

REGULAR_SEASON = 2

# The 2019-20 season was halted by COVID with teams at unequal games
# played; qualification was a 24-team play-in seeded by points percentage,
# so a 16-team cutline does not exist and berth flips are undefined.
# Points deltas are still computed for it. See decision 0015.
BERTH_EXCLUDED_SEASONS = frozenset({2019})

# NHL Rule 84.2: a team that loses in overtime after pulling its goalie for
# an extra attacker forfeits the point it earned by reaching overtime. It
# has bitten exactly once in this panel: 2024-03-30, VGK at MIN, where
# Minnesota -- needing 2 points in a playoff race where 1 was worthless --
# pulled its goalie in OT and lost to an empty-net goal (verified against
# the NHL gamecenter record and the day-over-day official standings; the
# validation gate below caught the 1-point discrepancy). The forfeiture is
# an outcome-level fact, so it applies under any point system that awards
# an OT-loss point. See decision 0015.
OT_LOSER_POINT_FORFEITURES = frozenset({(2023, 21166, "MIN")})


@dataclass(frozen=True)
class PointSystem:
    """Points awarded by game outcome (regulation vs overtime/shootout)."""

    name: str
    reg_win: int
    ot_win: int
    ot_loss: int
    reg_loss: int


POINT_SYSTEMS = (
    PointSystem("actual", reg_win=2, ot_win=2, ot_loss=1, reg_loss=0),
    PointSystem("three_two_one", reg_win=3, ot_win=2, ot_loss=1, reg_loss=0),
    PointSystem("no_loser_point", reg_win=2, ot_win=2, ot_loss=0, reg_loss=0),
)


def compute_standings(game_results: pd.DataFrame, system: PointSystem) -> pd.DataFrame:
    """Season standings under `system`, from per-game API results.

    Args:
        game_results: the NHL API results table (one row per game with
            home/away scores and last_period_type REG/OT/SO). Playoff rows
            are ignored.
        system: the point schedule to apply.

    Returns:
        One row per (season, team): games_played, points, wins, row_wins
        (regulation+OT wins, the tiebreak input), goal_diff. Goal
        differential follows the NHL convention of crediting the shootout
        winner's deciding goal (the API scores already include it), which
        is exactly what makes the actual-system output comparable to the
        official standings.
    """
    games = game_results[game_results["game_type"] == REGULAR_SEASON]
    reached_ot = games["last_period_type"].isin(["OT", "SO"])
    home_won = games["home_score"] > games["away_score"]

    def side(team_col: str, won: pd.Series, goal_diff: pd.Series) -> pd.DataFrame:
        points = pd.Series(0, index=games.index)
        points[won & ~reached_ot] = system.reg_win
        points[won & reached_ot] = system.ot_win
        points[~won & reached_ot] = system.ot_loss
        points[~won & ~reached_ot] = system.reg_loss
        frame = pd.DataFrame(
            {
                "season": games["season"],
                "game_id": games["game_id"],
                "team": games[team_col],
                "points": points,
                "win": won.astype(int),
                "row_win": (won & (games["last_period_type"] != "SO")).astype(int),
                "goal_diff": goal_diff,
            }
        )
        forfeited = frame.apply(
            lambda row: (row["season"], row["game_id"], row["team"]) in OT_LOSER_POINT_FORFEITURES,
            axis=1,
        )
        frame.loc[forfeited, "points"] = system.reg_loss
        return frame

    margin = games["home_score"] - games["away_score"]
    long = pd.concat(
        [side("home_team", home_won, margin), side("away_team", ~home_won, -margin)],
        ignore_index=True,
    )
    standings = (
        long.groupby(["season", "team"], as_index=False)
        .agg(
            games_played=("points", "size"),
            points=("points", "sum"),
            wins=("win", "sum"),
            row_wins=("row_win", "sum"),
            goal_diff=("goal_diff", "sum"),
        )
        .assign(system=system.name)
    )
    return standings


def rank_teams(standings: pd.DataFrame, group_cols: list[str]) -> pd.Series:
    """1-based rank within `group_cols` by the project's fixed tiebreak
    order: points, then regulation+OT wins, then total wins, then goal
    differential, then team code (a deterministic last resort).

    This is a documented approximation of the NHL's era-specific tiebreak
    cascades (which end in head-to-head records) -- see decision 0015 for
    why the approximation is acceptable for counting berth flips.
    """
    keyed = standings.sort_values(
        ["points", "row_wins", "wins", "goal_diff", "team"],
        ascending=[False, False, False, False, True],
    )
    return keyed.groupby(group_cols).cumcount() + 1


def playoff_qualifiers(
    standings: pd.DataFrame, alignment: pd.DataFrame, season_flags: pd.DataFrame
) -> pd.DataFrame:
    """Mark each (season, team) row qualified/not under that season's format.

    Args:
        standings: one system's output of compute_standings.
        alignment: (season, team) -> conference, division, from the real
            season-end API standings (realignment/expansion handled by data,
            not code).
        season_flags: per season, `wildcard_in_use` and `conferences_in_use`
            from the NHL season manifest.

    Formats (verified against the manifest, decision 0015):
        * wildcard era: top 3 per division + next 2 best per conference
        * conference era (2007-2012): top 8 per conference
        * 2020-21 (no conferences): top 4 per division
        * 2019-20: excluded (COVID play-in; no defined cutline)
    """
    merged = standings.merge(alignment, on=["season", "team"], validate="one_to_one")
    if len(merged) != len(standings):
        raise ValueError(
            "standings and alignment disagree on (season, team) coverage -- "
            f"{len(standings)} standings rows vs {len(merged)} after the join."
        )
    merged["division_rank"] = rank_teams(merged, ["season", "division"])
    merged["conference_rank"] = rank_teams(merged, ["season", "conference"])

    flags = season_flags.set_index("season")
    qualified = pd.Series(False, index=merged.index)
    for season, group in merged.groupby("season"):
        if season in BERTH_EXCLUDED_SEASONS:
            continue
        if flags.loc[season, "wildcard_in_use"]:
            division_spots = group["division_rank"] <= 3
            remainder = group[~division_spots]
            wildcard_rank = rank_teams(remainder, ["season", "conference"])
            # wildcard_rank is in sorted-row order; select by label, never
            # positionally, or the boolean mask lands on the wrong teams.
            wildcards = wildcard_rank.index[wildcard_rank <= 2]
            qualified.loc[group.index[division_spots]] = True
            qualified.loc[wildcards] = True
        elif flags.loc[season, "conferences_in_use"]:
            qualified.loc[group.index[group["conference_rank"] <= 8]] = True
        else:
            qualified.loc[group.index[group["division_rank"] <= 4]] = True
    merged["qualified"] = qualified
    return merged


def validate_actual_standings(computed: pd.DataFrame, official: pd.DataFrame) -> list[str]:
    """Compare the computed actual-rules standings to the API's official
    season-end standings; returns one message per disagreeing team-season.

    An empty list is the license to trust the counterfactual re-scoring:
    it means the game-results table and the scoring logic jointly reproduce
    every official points/wins/ROW/goal-diff figure exactly.
    """
    merged = computed.merge(
        official,
        on=["season", "team"],
        suffixes=("_computed", "_official"),
        validate="one_to_one",
    )
    problems = []
    checks = [
        ("points_computed", "points_official"),
        ("wins_computed", "wins_official"),
        ("row_wins_computed", "row_wins_official"),
        ("goal_diff_computed", "goal_diff_official"),
        ("games_played_computed", "games_played_official"),
    ]
    for _, row in merged.iterrows():
        for computed_col, official_col in checks:
            if row[computed_col] != row[official_col]:
                problems.append(
                    f"season {row['season']} {row['team']}: "
                    f"{computed_col.removesuffix('_computed')} "
                    f"computed={row[computed_col]} official={row[official_col]}"
                )
    return problems


def run_counterfactual(
    game_results: pd.DataFrame,
    alignment: pd.DataFrame,
    season_flags: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Standings and berth flips under every point system.

    Returns:
        (standings, summary): `standings` has one row per season x team x
        system with points, ranks, and qualification; `summary` has one row
        per season x counterfactual system with the number of teams whose
        playoff berth flips versus the actual system and the mean absolute
        points change.
    """
    per_system = {
        system.name: playoff_qualifiers(
            compute_standings(game_results, system), alignment, season_flags
        )
        for system in POINT_SYSTEMS
    }
    standings = pd.concat(per_system.values(), ignore_index=True)

    actual = per_system["actual"].set_index(["season", "team"])
    summaries = []
    for system in POINT_SYSTEMS:
        if system.name == "actual":
            continue
        alt = per_system[system.name].set_index(["season", "team"])
        for season in sorted(alt.index.get_level_values("season").unique()):
            a = actual.xs(season, level="season")
            b = alt.xs(season, level="season")
            flips = (
                float("nan")
                if season in BERTH_EXCLUDED_SEASONS
                else int((a["qualified"] != b["qualified"]).sum()) // 2
            )
            summaries.append(
                {
                    "season": season,
                    "system": system.name,
                    "berth_flips": flips,
                    "mean_abs_points_delta": float((b["points"] - a["points"]).abs().mean()),
                    "max_abs_points_delta": int((b["points"] - a["points"]).abs().max()),
                }
            )
    summary = pd.DataFrame(summaries)
    for _, row in summary.iterrows():
        logger.info(
            "counterfactual %s | season %s: %s berth flips, mean |points delta| %.1f",
            row["system"],
            row["season"],
            row["berth_flips"],
            row["mean_abs_points_delta"],
        )
    return standings, summary


def main() -> None:
    from pathlib import Path

    from loserpoint.ingest.nhl_api import NHLApiClient
    from loserpoint.utils.io import write_parquet

    game_results = pd.read_parquet("data/interim/nhl_api/game_results.parquet")
    official = pd.read_parquet("data/interim/nhl_api/season_end_standings.parquet")
    alignment = official[["season", "team", "conference", "division"]]

    seasons = sorted(game_results["season"].unique())
    manifest = NHLApiClient(Path("data/raw/nhl_api")).season_manifest()
    by_id = {entry["id"]: entry for entry in manifest}
    season_flags = pd.DataFrame(
        {
            "season": season,
            "wildcard_in_use": by_id[season * 10000 + season + 1]["wildcardInUse"],
            "conferences_in_use": by_id[season * 10000 + season + 1]["conferencesInUse"],
        }
        for season in seasons
    )

    computed_actual = compute_standings(game_results, POINT_SYSTEMS[0])
    problems = validate_actual_standings(computed_actual, official)
    if problems:
        for problem in problems[:20]:
            logger.error("standings validation: %s", problem)
        raise RuntimeError(
            f"computed actual-rules standings disagree with the official NHL "
            f"season-end standings on {len(problems)} team-season figures -- "
            "fix the scoring logic or the game-results ingest before trusting "
            "any counterfactual number (first mismatches logged above)."
        )
    logger.info(
        "standings validation: computed actual standings match the official "
        "API standings exactly for all %d team-seasons.",
        len(computed_actual),
    )

    standings, summary = run_counterfactual(game_results, alignment, season_flags)
    write_parquet(standings, Path("data/processed/counterfactual_standings.parquet"))
    write_parquet(summary, Path("data/processed/counterfactual_summary.parquet"))


if __name__ == "__main__":
    main()
