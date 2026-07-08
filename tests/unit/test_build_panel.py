"""Unit tests for panel/build_panel.py -- aggregation of shots into the
game x team x minute panel, and the invariant checker that guards it.
"""

from __future__ import annotations

import pandas as pd
import pytest
from loserpoint.panel.build_panel import (
    PanelInvariantError,
    build_panel,
    check_panel_invariants,
)

from tests.fixtures.moneypuck.builders import make_shot_row
from tests.fixtures.panel.builders import make_game_from_goals


def _row(**kwargs) -> dict:
    defaults = {
        "game_id": 20001,
        "season": 2013,
        "is_home_team": 1,
        "home_team_goals": 0,
        "away_team_goals": 0,
        "period": 1,
        "time": 30,
        "event": "SHOT",
    }
    defaults.update(kwargs)
    return make_shot_row(**defaults)


def test_every_game_contributes_exactly_120_rows() -> None:
    shots = make_game_from_goals([(300, True), (2000, False)])
    minutes, games = build_panel(shots)
    assert len(minutes) == 120
    assert len(games) == 1
    assert set(minutes["minute"]) == set(range(1, 61))
    assert minutes.groupby("is_home").size().tolist() == [60, 60]


def test_attempts_land_in_the_right_minute_and_team() -> None:
    # Home shot at t=100 (minute 2), away shot at t=3600 (minute 60).
    shots = pd.DataFrame(
        [_row(time=100, is_home_team=1), _row(time=3600, period=3, is_home_team=0)]
    )
    minutes, _ = build_panel(shots)
    home = minutes[minutes["is_home"]].set_index("minute")
    away = minutes[~minutes["is_home"]].set_index("minute")
    assert home.loc[2, "attempts_naive"] == 1
    assert away.loc[60, "attempts_naive"] == 1
    assert home["attempts_naive"].sum() == 1
    assert away["attempts_naive"].sum() == 1


def test_overtime_shots_are_excluded_from_the_panel() -> None:
    shots = pd.DataFrame([_row(time=100), _row(time=3700, period=4), _row(time=3601, period=4)])
    minutes, _ = build_panel(shots)
    assert minutes["attempts_naive"].sum() == 1


def test_non_5v5_shots_are_excluded_from_main_but_kept_in_naive() -> None:
    pp_shot = _row(time=100)
    pp_shot["homeSkatersOnIce"] = 5
    pp_shot["awaySkatersOnIce"] = 4
    shots = pd.DataFrame([pp_shot, _row(time=200)])
    minutes, _ = build_panel(shots)
    home = minutes[minutes["is_home"]]
    assert home["attempts_naive"].sum() == 2
    assert home["attempts_main"].sum() == 1


def test_non_5v5_flag_marks_the_minute_for_both_teams() -> None:
    pp_shot = _row(time=100, is_home_team=1)  # minute 2
    pp_shot["awaySkatersOnIce"] = 4
    shots = pd.DataFrame([pp_shot, _row(time=500, is_home_team=0)])
    minutes, _ = build_panel(shots)
    flagged = minutes[minutes["non_5v5_flag"]]
    assert set(flagged["minute"]) == {2}
    assert len(flagged) == 2  # both team rows of minute 2


def test_empty_net_policy_excludes_shot_on_empty_net_from_main() -> None:
    en_shot = _row(time=3550, period=3)  # minute 60
    en_shot["shotOnEmptyNet"] = 1
    shots = pd.DataFrame([en_shot, _row(time=3555, period=3)])
    minutes, _ = build_panel(shots)
    home = minutes[minutes["is_home"]].set_index("minute")
    assert home.loc[60, "attempts_naive"] == 2
    assert home.loc[60, "attempts_main"] == 1
    assert home.loc[60, "attempts_all_ex_en"] == 1
    assert home.loc[60, "attempts_5v5_incl_en"] == 2


def test_empty_net_policy_excludes_shots_by_team_with_goalie_pulled() -> None:
    pulled = _row(time=3550, period=3, is_home_team=1)
    pulled["homeEmptyNet"] = 1  # shooter's own net is empty
    shots = pd.DataFrame([pulled, _row(time=3555, period=3)])
    minutes, _ = build_panel(shots)
    home = minutes[minutes["is_home"]].set_index("minute")
    assert home.loc[60, "attempts_main"] == 1
    assert home.loc[60, "attempts_naive"] == 2


def test_score_states_joined_onto_panel_rows() -> None:
    shots = make_game_from_goals([(300, True)])  # home goal, minute 5
    minutes, _ = build_panel(shots)
    home = minutes[minutes["is_home"]].set_index("minute")
    away = minutes[~minutes["is_home"]].set_index("minute")
    assert home.loc[5, "score_state"] == "tied"
    assert home.loc[6, "score_state"] == "up_1"
    assert away.loc[6, "score_state"] == "down_1"
    assert home.loc[6, "score_diff"] == 1
    assert away.loc[6, "score_diff"] == -1


def test_goals_for_sums_to_regulation_score() -> None:
    shots = make_game_from_goals([(300, True), (900, True), (2000, False), (3700, True)])
    minutes, games = build_panel(shots)
    home_goals = minutes[minutes["is_home"]]["goals_for"].sum()
    away_goals = minutes[~minutes["is_home"]]["goals_for"].sum()
    assert home_goals == games.iloc[0]["reg_home_goals"] == 2  # OT goal excluded
    assert away_goals == games.iloc[0]["reg_away_goals"] == 1


def test_games_table_carries_outcomes() -> None:
    shots = make_game_from_goals(
        [(300, True), (900, False)], extra_shots=[(3700, True)], home_team_won=1
    )
    _, games = build_panel(shots)
    row = games.iloc[0]
    assert row["reached_ot"]
    assert row["decided_by_shootout"]
    assert row["home_won"]


def test_multiple_games_stack() -> None:
    g1 = make_game_from_goals([(300, True)], game_id=20001)
    g2 = make_game_from_goals([(500, False)], game_id=20002)
    minutes, games = build_panel(pd.concat([g1, g2], ignore_index=True))
    assert len(minutes) == 240
    assert len(games) == 2


def test_same_game_id_in_different_seasons_stays_separate() -> None:
    # NHL game_ids restart every season: game 20001 exists in every season.
    # The panel key is (season, game_id) -- multi-season input must never
    # merge two seasons' games (bugs_found.md #7).
    g1 = make_game_from_goals([(300, True)], game_id=20001, season=2013)
    g2 = make_game_from_goals([(500, False)], game_id=20001, season=2014)
    minutes, games = build_panel(pd.concat([g1, g2], ignore_index=True))
    assert len(games) == 2
    assert len(minutes) == 240
    check_panel_invariants(minutes, games)  # must not raise or mix games


def test_corrupt_game_is_dropped_with_warning(caplog) -> None:
    # A game whose recorded running score decreases (real example: 2007
    # game 20274, decision 0007) must be dropped loudly, not crash the
    # build or silently contaminate the panel.
    good = make_game_from_goals([(300, True)], game_id=20001)
    corrupt = make_game_from_goals([(300, True)], game_id=20002, extra_shots=[(400, True)])
    corrupt.loc[corrupt.index[-1], "homeTeamGoals"] = 0  # decrease after the goal
    import logging

    with caplog.at_level(logging.WARNING):
        minutes, games = build_panel(pd.concat([good, corrupt], ignore_index=True))
    assert len(games) == 1
    assert games.iloc[0]["game_id"] == 20001
    assert len(minutes) == 120
    assert any("dropping corrupt game 20002" in r.message for r in caplog.records)


def test_invariants_pass_on_clean_panel() -> None:
    shots = make_game_from_goals([(300, True), (2000, False)])
    minutes, games = build_panel(shots)
    check_panel_invariants(minutes, games)  # must not raise


def test_invariants_catch_missing_rows() -> None:
    shots = make_game_from_goals([(300, True)])
    minutes, games = build_panel(shots)
    with pytest.raises(PanelInvariantError, match="120"):
        check_panel_invariants(minutes.iloc[:-1], games)


def test_invariants_catch_goal_sum_mismatch() -> None:
    shots = make_game_from_goals([(300, True)])
    minutes, games = build_panel(shots)
    minutes = minutes.copy()
    minutes.loc[minutes.index[0], "goals_for"] += 1
    with pytest.raises(PanelInvariantError, match="goals"):
        check_panel_invariants(minutes, games)


def test_invariants_catch_mirror_violation() -> None:
    shots = make_game_from_goals([(300, True)])
    minutes, games = build_panel(shots)
    minutes = minutes.copy()
    victim = minutes[(minutes["minute"] == 10) & minutes["is_home"]].index[0]
    minutes.loc[victim, "score_diff"] = 3
    minutes.loc[victim, "score_state"] = "up_2_plus"
    # Keep the goal sum intact so the mirror check is what fires.
    with pytest.raises(PanelInvariantError, match="[Mm]irror"):
        check_panel_invariants(minutes, games)


def test_invariants_catch_nonzero_minute_one_state() -> None:
    # Corrupt minute 1 for both teams in a mirror-consistent way so the
    # minute-one check specifically (not the mirror check) is what fires.
    shots = make_game_from_goals([(300, True)])
    minutes, games = build_panel(shots)
    minutes = minutes.copy()
    m1_home = minutes[(minutes["minute"] == 1) & minutes["is_home"]].index
    m1_away = minutes[(minutes["minute"] == 1) & ~minutes["is_home"]].index
    minutes.loc[m1_home, ["score_state", "score_diff"]] = ["up_1", 1]
    minutes.loc[m1_away, ["score_state", "score_diff"]] = ["down_1", -1]
    with pytest.raises(PanelInvariantError, match="minute 1"):
        check_panel_invariants(minutes, games)


def test_invariants_catch_duplicate_game_team_minute_rows() -> None:
    shots = make_game_from_goals([(300, True)])
    minutes, games = build_panel(shots)
    # Keep the 120-row count intact while creating a duplicate key: drop
    # one row and duplicate another.
    corrupted = pd.concat([minutes.iloc[:-1], minutes.iloc[[0]]], ignore_index=True)
    with pytest.raises(PanelInvariantError, match="duplicate"):
        check_panel_invariants(corrupted, games)


def test_invariants_catch_invalid_state_labels() -> None:
    shots = make_game_from_goals([(300, True)])
    minutes, games = build_panel(shots)
    minutes = minutes.copy()
    minutes.loc[minutes.index[0], "score_state"] = "winning_bigly"
    with pytest.raises(PanelInvariantError, match="invalid score_state"):
        check_panel_invariants(minutes, games)


def test_invariants_catch_mirrored_state_mismatch() -> None:
    # Valid labels, untouched (symmetric) diffs, but states that don't
    # mirror: home is up_1 at minute 10 (goal at t=300), so away must be
    # down_1 -- corrupt it to tied.
    shots = make_game_from_goals([(300, True)])
    minutes, games = build_panel(shots)
    minutes = minutes.copy()
    away10 = minutes[(minutes["minute"] == 10) & ~minutes["is_home"]].index
    minutes.loc[away10, "score_state"] = "tied"
    with pytest.raises(PanelInvariantError, match="score_state does not mirror"):
        check_panel_invariants(minutes, games)


def test_invariants_catch_negative_counts() -> None:
    shots = make_game_from_goals([(300, True)])
    minutes, games = build_panel(shots)
    minutes = minutes.copy()
    minutes.loc[minutes.index[5], "attempts_naive"] = -1
    with pytest.raises(PanelInvariantError, match="negative"):
        check_panel_invariants(minutes, games)
