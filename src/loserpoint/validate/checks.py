"""Cross-checks and reconciliation reporting for ingested data.

Phase 1 implements the MoneyPuck-only checks: agreement with MoneyPuck's own
published season row counts, and same-source internal consistency (a game's
running score, as recorded shot-by-shot, must be monotonic non-decreasing
and must match the count of goal events logged for each team). Cross-source
reconciliation against the NHL API's schedule data (final scores must agree
across sources) is added once `ingest/nhl_api.py` exists in Phase 3 -- see
the TODO on `reconcile_season`.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

from loserpoint.ingest.moneypuck import KNOWN_INCOMPLETE_GAMES, PUBLISHED_SEASON_ROW_COUNTS
from loserpoint.utils.logging import get_logger

logger = get_logger(__name__)

Severity = str  # "INFO" | "WARNING" | "HARD_FAILURE"


@dataclass(frozen=True)
class ReconciliationIssue:
    severity: Severity
    season: int
    check: str
    message: str


@dataclass(frozen=True)
class SeasonReconciliation:
    """All reconciliation output for one season: the issues to render in the
    report, plus the game-sample counts needed to compute a *correct*
    failure fraction -- kept as explicit numbers rather than re-derived from
    `issues`, since inferring a fraction from a mixed list of per-game
    warnings and season-level informational notes is exactly the bug this
    dataclass replaced (see docs/decisions/bugs_found.md #5).
    """

    season: int
    issues: list[ReconciliationIssue]
    n_games_sampled: int
    n_games_failed: int

    @property
    def failure_fraction(self) -> float:
        if self.n_games_sampled == 0:
            return 0.0
        return self.n_games_failed / self.n_games_sampled


def check_published_row_count(df: pd.DataFrame, season: int) -> ReconciliationIssue:
    """Compare `df`'s row count against MoneyPuck's own published total for
    `season`, where one exists (only 2007-2018 are published).

    Interpretation: a WARNING here means either our download is corrupt/
    truncated, or MoneyPuck silently revised the season's data since they
    published that total -- either way, worth a human look before trusting
    the season downstream.
    """
    expected = PUBLISHED_SEASON_ROW_COUNTS.get(season)
    if expected is None:
        return ReconciliationIssue(
            "INFO",
            season,
            "published_row_count",
            f"no MoneyPuck-published row count available for season {season} "
            "(their dictionary only lists totals through 2018); skipping this check.",
        )
    actual = len(df)
    if actual != expected:
        return ReconciliationIssue(
            "WARNING",
            season,
            "published_row_count",
            f"{actual} rows loaded vs {expected} published by MoneyPuck's data dictionary.",
        )
    return ReconciliationIssue(
        "INFO",
        season,
        "published_row_count",
        f"{actual} rows loaded, matches MoneyPuck's published total exactly.",
    )


def check_game_goal_counts(
    df: pd.DataFrame,
    season: int,
    *,
    sample_games: int = 200,
    seed: int = 0,
) -> tuple[list[ReconciliationIssue], int, int]:
    """For a random sample of games, verify that the shot-by-shot recorded
    score (`homeTeamGoals`/`awayTeamGoals`) never decreases within a game.
    This is a same-source check -- it catches ingestion bugs and truncated
    files, not MoneyPuck's own data-collection errors, which is why
    cross-source reconciliation against the NHL API is also needed
    (Phase 3).

    This deliberately does NOT check that the final tally equals the count
    of `GOAL`-tagged rows: real MoneyPuck data contains "phantom" goals that
    increment the running score with no corresponding `GOAL` (or any) row
    nearby -- confirmed on 2013 game 20451, where `awayTeamGoals` jumps from
    2 to 3 on a plain `SHOT` row with no `GOAL` row anywhere near it. See
    docs/decisions/0003-moneypuck-data-quirks.md. Monotonicity is the only
    invariant `panel/score_state.py` actually depends on (it reads the
    running score columns directly, never derives score from counting GOAL
    rows), so that's the only invariant enforced here.

    Games MoneyPuck itself discloses as having incomplete data
    (`KNOWN_INCOMPLETE_GAMES`) are skipped rather than flagged.

    Returns:
        A tuple of (one WARNING issue per failing game, number of games
        sampled, number of games that failed). The counts are returned
        alongside the issues -- rather than left for the caller to infer by
        counting issues -- because the issue list's length is not the
        sample size (a clean season produces zero issues from this
        function).
    """
    issues: list[ReconciliationIssue] = []
    incomplete = set(KNOWN_INCOMPLETE_GAMES.get(season, []))
    game_ids = np.array(sorted(set(df["game_id"]) - incomplete))
    if len(game_ids) == 0:
        return issues, 0, 0
    rng = np.random.default_rng(seed)
    sample_size = min(sample_games, len(game_ids))
    sample = rng.choice(game_ids, size=sample_size, replace=False)

    n_failed = 0
    for game_id in sample:
        game = df.loc[df["game_id"] == game_id].sort_values("shotID")
        if not game["homeTeamGoals"].is_monotonic_increasing:
            issues.append(
                ReconciliationIssue(
                    "WARNING",
                    season,
                    "game_goal_counts",
                    f"game {game_id}: homeTeamGoals decreases within the game.",
                )
            )
            n_failed += 1
            continue
        if not game["awayTeamGoals"].is_monotonic_increasing:
            issues.append(
                ReconciliationIssue(
                    "WARNING",
                    season,
                    "game_goal_counts",
                    f"game {game_id}: awayTeamGoals decreases within the game.",
                )
            )
            n_failed += 1

    return issues, sample_size, n_failed


def reconcile_season(
    df: pd.DataFrame, season: int, *, sample_games: int = 200, seed: int = 0
) -> SeasonReconciliation:
    """Run every Phase-1 reconciliation check for one season's shot data.

    TODO(Phase 3): once `ingest/nhl_api.py` exists, add a check here that
    reconstructed final scores agree with the NHL API's schedule data for
    the same sample of games -- true cross-source reconciliation, which this
    phase cannot do with MoneyPuck data alone.
    """
    issues = [check_published_row_count(df, season)]
    game_issues, n_sampled, n_failed = check_game_goal_counts(
        df, season, sample_games=sample_games, seed=seed
    )
    issues.extend(game_issues)
    issues.append(
        ReconciliationIssue(
            "INFO",
            season,
            "game_goal_counts_summary",
            f"{n_sampled - n_failed}/{n_sampled} sampled games internally consistent.",
        )
    )
    return SeasonReconciliation(
        season=season, issues=issues, n_games_sampled=n_sampled, n_games_failed=n_failed
    )


def write_validation_report(
    reconciliations: list[SeasonReconciliation],
    out_path: Path,
    *,
    hard_failure_mismatch_threshold: float = 0.02,
) -> None:
    """Render every season's reconciliation issues to a single markdown
    report, regenerated in full on every run (never appended to).

    Raises:
        RuntimeError: if any season's fraction of failing per-game checks
            exceeds `hard_failure_mismatch_threshold` -- a hard stop, since
            silently proceeding with a season this inconsistent would
            contaminate every downstream model.
    """
    lines = ["# MoneyPuck ingest validation report", ""]
    hard_failures: list[str] = []

    for rec in sorted(reconciliations, key=lambda r: r.season):
        lines.append(f"## Season {rec.season}")
        lines.append("")
        for issue in rec.issues:
            lines.append(f"- **{issue.severity}** [{issue.check}] {issue.message}")
        lines.append("")
        lines.append(
            f"Per-game check failure rate: {rec.failure_fraction:.1%} "
            f"(threshold: {hard_failure_mismatch_threshold:.1%})"
        )
        lines.append("")
        if rec.failure_fraction > hard_failure_mismatch_threshold:
            hard_failures.append(
                f"season {rec.season}: {rec.failure_fraction:.1%} of sampled games failed "
                f"internal consistency checks (threshold {hard_failure_mismatch_threshold:.1%})"
            )

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("\n".join(lines))
    logger.info("wrote validation report to %s", out_path)

    if hard_failures:
        raise RuntimeError(
            "Validation hard failure(s) -- see "
            + str(out_path)
            + " for detail:\n"
            + "\n".join(hard_failures)
        )
