"""Unit tests for validate.checks -- reconciliation and report generation."""

from __future__ import annotations

import pytest
from loserpoint.validate.checks import (
    ReconciliationIssue,
    SeasonReconciliation,
    check_game_goal_counts,
    check_published_row_count,
    reconcile_season,
    write_validation_report,
)

from tests.fixtures.moneypuck.builders import (
    games_to_frame,
    make_clean_game,
    make_decreasing_score_game,
    make_phantom_goal_game,
)


def test_published_row_count_matches(monkeypatch) -> None:
    df = games_to_frame(make_clean_game(game_id=20001, season=2013))
    monkeypatch.setattr("loserpoint.validate.checks.PUBLISHED_SEASON_ROW_COUNTS", {2013: len(df)})
    issue = check_published_row_count(df, 2013)
    assert issue.severity == "INFO"
    assert "matches" in issue.message


def test_published_row_count_mismatch_warns(monkeypatch) -> None:
    df = games_to_frame(make_clean_game(game_id=20001, season=2013))
    monkeypatch.setattr(
        "loserpoint.validate.checks.PUBLISHED_SEASON_ROW_COUNTS", {2013: len(df) + 5}
    )
    issue = check_published_row_count(df, 2013)
    assert issue.severity == "WARNING"


def test_published_row_count_no_reference_available_for_unlisted_season() -> None:
    df = games_to_frame(make_clean_game(game_id=20001, season=2022))
    issue = check_published_row_count(df, 2022)
    assert issue.severity == "INFO"
    assert "no MoneyPuck-published row count" in issue.message


def test_check_game_goal_counts_passes_on_clean_game() -> None:
    df = games_to_frame(make_clean_game(game_id=20001, season=2013))
    issues, n_sampled, n_failed = check_game_goal_counts(df, 2013, sample_games=1)
    assert issues == []
    assert n_sampled == 1
    assert n_failed == 0


def test_check_game_goal_counts_does_not_flag_phantom_goals() -> None:
    # Real MoneyPuck data occasionally increments the running score with no
    # corresponding GOAL row; monotonicity is the only invariant enforced.
    df = games_to_frame(make_phantom_goal_game(game_id=20002, season=2013))
    issues, n_sampled, n_failed = check_game_goal_counts(df, 2013, sample_games=1)
    assert issues == []
    assert n_sampled == 1
    assert n_failed == 0


def test_check_game_goal_counts_detects_decreasing_score() -> None:
    df = games_to_frame(make_decreasing_score_game(game_id=20003, season=2013))
    issues, n_sampled, n_failed = check_game_goal_counts(df, 2013, sample_games=1)
    assert n_sampled == 1
    assert n_failed == 1
    assert len(issues) == 1
    assert "decreases within the game" in issues[0].message


def test_check_game_goal_counts_skips_known_incomplete_games() -> None:
    # Game 259 in season 2008 is on MoneyPuck's own disclosed incomplete list.
    df = games_to_frame(make_decreasing_score_game(game_id=259, season=2008))
    issues, n_sampled, n_failed = check_game_goal_counts(df, 2008, sample_games=5)
    assert issues == []
    assert n_sampled == 0
    assert n_failed == 0


def test_season_reconciliation_failure_fraction() -> None:
    rec = SeasonReconciliation(season=2013, issues=[], n_games_sampled=200, n_games_failed=6)
    assert rec.failure_fraction == pytest.approx(0.03)


def test_season_reconciliation_failure_fraction_zero_sampled() -> None:
    rec = SeasonReconciliation(season=2013, issues=[], n_games_sampled=0, n_games_failed=0)
    assert rec.failure_fraction == 0.0


def test_reconcile_season_combines_both_checks_and_tracks_counts() -> None:
    df = games_to_frame(
        make_clean_game(game_id=20001, season=2013),
        make_decreasing_score_game(game_id=20002, season=2013),
    )
    rec = reconcile_season(df, 2013, sample_games=2)
    checks_run = {issue.check for issue in rec.issues}
    assert checks_run == {"published_row_count", "game_goal_counts", "game_goal_counts_summary"}
    assert rec.n_games_sampled == 2
    assert rec.n_games_failed == 1
    assert rec.failure_fraction == pytest.approx(0.5)


def test_write_validation_report_writes_markdown(tmp_path) -> None:
    rec = SeasonReconciliation(
        season=2013,
        issues=[ReconciliationIssue("INFO", 2013, "published_row_count", "matches exactly")],
        n_games_sampled=1,
        n_games_failed=0,
    )
    out_path = tmp_path / "validation_report.md"
    write_validation_report([rec], out_path)
    text = out_path.read_text()
    assert "Season 2013" in text
    assert "matches exactly" in text
    assert "0.0%" in text


def test_write_validation_report_raises_on_hard_failure(tmp_path) -> None:
    rec = SeasonReconciliation(
        season=2013,
        issues=[
            ReconciliationIssue("WARNING", 2013, "game_goal_counts", "bad game 1"),
            ReconciliationIssue("WARNING", 2013, "game_goal_counts", "bad game 2"),
        ],
        n_games_sampled=200,
        n_games_failed=2,
    )
    out_path = tmp_path / "validation_report.md"
    with pytest.raises(RuntimeError, match="Validation hard failure"):
        write_validation_report([rec], out_path, hard_failure_mismatch_threshold=0.005)
    # The report is still written even though it then raises.
    assert out_path.exists()


def test_write_validation_report_passes_under_threshold(tmp_path) -> None:
    rec = SeasonReconciliation(
        season=2013,
        issues=[ReconciliationIssue("WARNING", 2013, "game_goal_counts", "bad game 1")],
        n_games_sampled=200,
        n_games_failed=1,
    )
    out_path = tmp_path / "validation_report.md"
    write_validation_report([rec], out_path, hard_failure_mismatch_threshold=0.02)
    assert out_path.exists()
