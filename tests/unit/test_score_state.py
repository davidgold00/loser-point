"""Unit tests for panel/score_state.py -- written BEFORE the implementation
(TDD, per the Phase 2 plan). This module is the project's single biggest
bug risk (off-by-one errors in minute boundaries), so every rule in
docs/decisions/0006-score-state-construction.md has a test here, and the
golden games in tests/golden/ lock the same rules against real data.
"""

from __future__ import annotations

import pytest
from loserpoint.panel.score_state import (
    GoalEvent,
    InconsistentGameError,
    extract_goal_events,
    game_outcomes,
    minute_of_time,
    minute_states,
    score_state_label,
)

from tests.fixtures.panel.builders import make_game_from_goals

# ---------------------------------------------------------------------------
# minute_of_time: the boundary convention (decision 0001 / 0006 rule 1)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("time", "expected_minute"),
    [
        (0, 1),  # t=0 clamp: the only closed-left minute
        (1, 1),
        (59, 1),
        (60, 1),  # exactly 1:00 belongs to minute 1 -- (0, 60]
        (61, 2),
        (3240, 54),  # exactly 54:00 belongs to minute 54, not 55
        (3241, 55),
        (3540, 59),
        (3541, 60),
        (3599, 60),
        (3600, 60),  # final second of regulation
        (3601, 61),  # first second of OT (excluded from panel downstream)
    ],
)
def test_minute_of_time_boundaries(time: int, expected_minute: int) -> None:
    assert minute_of_time(time) == expected_minute


# ---------------------------------------------------------------------------
# score_state_label: the five bins from config.yaml
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("diff", "label"),
    [
        (-5, "down_2_plus"),
        (-2, "down_2_plus"),
        (-1, "down_1"),
        (0, "tied"),
        (1, "up_1"),
        (2, "up_2_plus"),
        (5, "up_2_plus"),
    ],
)
def test_score_state_label_bins(diff: int, label: str) -> None:
    assert score_state_label(diff) == label


# ---------------------------------------------------------------------------
# extract_goal_events: goal timeline reconstruction (0006 rule 3)
# ---------------------------------------------------------------------------


def test_extract_clean_game_goals_in_order() -> None:
    game = make_game_from_goals([(300, True), (1500, False), (3500, True)])
    goals = extract_goal_events(game)
    assert [(g.time, g.is_home_team, g.is_phantom) for g in goals] == [
        (300, True, False),
        (1500, False, False),
        (3500, True, False),
    ]


def test_extract_recovers_phantom_goal_at_observing_row_time() -> None:
    # Goal at index 1 (away, t=1500) gets no GOAL row; a SHOT at t=1600
    # is the first row whose score-before reveals it. The phantom is
    # timestamped 1600 (the observing row), the documented upper bound.
    game = make_game_from_goals(
        [(300, True), (1500, False)],
        phantom={1},
        extra_shots=[(1600, True)],
    )
    goals = extract_goal_events(game)
    assert [(g.time, g.is_home_team, g.is_phantom) for g in goals] == [
        (300, True, False),
        (1600, False, True),
    ]


def test_extract_raises_on_decreasing_recorded_score() -> None:
    game = make_game_from_goals([(300, True)], extra_shots=[(400, True), (500, True)])
    # Corrupt the last row: recorded score-before drops below the tally.
    game.loc[game.index[-1], "homeTeamGoals"] = 0
    with pytest.raises(InconsistentGameError):
        extract_goal_events(game)


def test_extract_goal_on_final_row_is_counted() -> None:
    game = make_game_from_goals([(3599, True)])
    goals = extract_goal_events(game)
    assert len(goals) == 1
    assert goals[0].time == 3599


# ---------------------------------------------------------------------------
# minute_states: score state entering each minute (0006 rule 2)
# ---------------------------------------------------------------------------


def _goal(time: int, is_home: bool, period: int | None = None) -> GoalEvent:
    if period is None:
        period = max(1, -(-min(time, 3600) // 1200))
    return GoalEvent(time=time, is_home_team=is_home, is_phantom=False, period=period)


def test_no_goal_game_is_tied_all_sixty_minutes() -> None:
    states = minute_states([])
    assert len(states) == 60
    assert (states["home_state"] == "tied").all()
    assert (states["away_state"] == "tied").all()


def test_goal_in_final_minute_never_changes_any_entering_state() -> None:
    # A goal at 59:59 is in minute 60; it would change the state entering
    # minute 61, which does not exist. All 60 rows stay tied.
    states = minute_states([_goal(3599, True)])
    assert (states["home_state"] == "tied").all()


def test_goal_at_exact_minute_boundary_changes_next_minute_only() -> None:
    # Goal at exactly 54:00 (3240s) is in minute 54 -> tied entering 54,
    # up_1 entering 55. This is the single most bug-prone rule in the
    # project; see decision 0001.
    states = minute_states([_goal(3240, True)]).set_index("minute")
    assert states.loc[54, "home_state"] == "tied"
    assert states.loc[55, "home_state"] == "up_1"
    assert states.loc[54, "away_state"] == "tied"
    assert states.loc[55, "away_state"] == "down_1"


def test_goal_one_second_after_boundary_lands_one_minute_later() -> None:
    # Goal at 54:01 (3241s) is in minute 55 -> still tied entering 55,
    # up_1 entering 56.
    states = minute_states([_goal(3241, True)]).set_index("minute")
    assert states.loc[55, "home_state"] == "tied"
    assert states.loc[56, "home_state"] == "up_1"


def test_goal_at_time_zero_does_not_leak_into_minute_one_entering_state() -> None:
    # A goal at t=0 is in (clamped) minute 1, so minute 1 is still entered
    # tied; minute 2 is entered up_1. Guards the t=0 clamp interaction
    # with the threshold rule (0006 rule 1).
    states = minute_states([_goal(0, True)]).set_index("minute")
    assert states.loc[1, "home_state"] == "tied"
    assert states.loc[2, "home_state"] == "up_1"


def test_three_goals_in_one_minute_all_land_in_next_minute() -> None:
    goals = [_goal(1210, True), _goal(1225, False), _goal(1250, True)]
    states = minute_states(goals).set_index("minute")
    assert states.loc[21, "home_state"] == "tied"  # all three are in minute 21
    assert states.loc[22, "home_state"] == "up_1"  # 2-1 entering minute 22
    assert states.loc[22, "away_state"] == "down_1"
    assert states.loc[22, "home_score"] == 2
    assert states.loc[22, "away_score"] == 1


def test_comeback_path_is_consistent() -> None:
    # Away scores at 5:00 and 10:00; home scores at 30:00, 40:00, 50:00.
    goals = [
        _goal(300, False),
        _goal(600, False),
        _goal(1800, True),
        _goal(2400, True),
        _goal(3000, True),
    ]
    states = minute_states(goals).set_index("minute")
    assert states.loc[6, "home_state"] == "down_1"
    assert states.loc[11, "home_state"] == "down_2_plus"
    assert states.loc[31, "home_state"] == "down_1"
    assert states.loc[41, "home_state"] == "tied"
    assert states.loc[51, "home_state"] == "up_1"
    assert states.loc[60, "home_state"] == "up_1"


def test_overtime_goals_never_affect_regulation_states() -> None:
    states = minute_states([_goal(3700, True, period=4)])
    assert (states["home_state"] == "tied").all()


def test_mirror_consistency_between_home_and_away() -> None:
    goals = [_goal(500, True), _goal(900, True), _goal(2000, False)]
    states = minute_states(goals)
    mirror = {
        "tied": "tied",
        "up_1": "down_1",
        "down_1": "up_1",
        "up_2_plus": "down_2_plus",
        "down_2_plus": "up_2_plus",
    }
    assert (states["away_state"] == states["home_state"].map(mirror)).all()


# ---------------------------------------------------------------------------
# game_outcomes (0006 rule 4)
# ---------------------------------------------------------------------------


def test_regulation_win_outcomes() -> None:
    game = make_game_from_goals([(300, True), (1500, True), (2000, False)])
    out = game_outcomes(game)
    assert out.reg_home_goals == 2
    assert out.reg_away_goals == 1
    assert not out.reached_ot
    assert not out.decided_by_shootout
    assert out.home_won


def test_overtime_goal_game_outcomes() -> None:
    game = make_game_from_goals([(300, True), (1500, False), (3700, True)])
    out = game_outcomes(game)
    assert out.reg_home_goals == 1
    assert out.reg_away_goals == 1
    assert out.reached_ot
    assert not out.decided_by_shootout
    assert out.final_home_goals == 2


def test_shootout_game_outcomes() -> None:
    # Tied through OT; homeTeamWon=1 with no goal row explaining it is the
    # only shootout signature MoneyPuck data carries (decision 0003).
    game = make_game_from_goals(
        [(300, True), (1500, False)],
        extra_shots=[(3700, True), (3850, False)],
        home_team_won=1,
    )
    out = game_outcomes(game)
    assert out.reached_ot
    assert out.decided_by_shootout
    assert out.home_won


def test_playoff_multi_overtime_outcomes() -> None:
    game = make_game_from_goals(
        [(300, True), (1500, False), (5200, False)],
        game_id=30111,
        is_playoff_game=1,
    )
    out = game_outcomes(game)
    assert out.is_playoff
    assert out.reached_ot
    assert not out.decided_by_shootout
    assert out.final_away_goals == 2


def test_goal_at_3600_counts_as_regulation() -> None:
    game = make_game_from_goals([(3600, True)])
    out = game_outcomes(game)
    assert out.reg_home_goals == 1
    assert not out.reached_ot


def test_playoff_game_with_tied_recorded_final_warns_and_is_not_shootout(caplog) -> None:
    # Playoff games cannot end tied; a tied recorded final means the shot
    # data is incomplete. It must warn loudly and never be labeled a
    # shootout (there are no playoff shootouts).
    game = make_game_from_goals(
        [(300, True), (900, False)], game_id=30001, is_playoff_game=1, home_team_won=1
    )
    with caplog.at_level("WARNING"):
        out = game_outcomes(game)
    assert not out.decided_by_shootout
    assert any("cannot end tied" in r.message for r in caplog.records)
