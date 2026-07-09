"""Unit tests for cross-source reconciliation and the model sample builder."""

from __future__ import annotations

import pandas as pd
from loserpoint.analysis.models import build_estimation_sample
from loserpoint.validate.checks import reconcile_games_with_nhl_api


def _mp_game(**kw) -> dict:
    base = {
        "season": 2013,
        "game_id": 20001,
        "is_playoff": False,
        "home_team": "TOR",
        "away_team": "MTL",
        "reg_home_goals": 2,
        "reg_away_goals": 1,
        "final_home_goals": 2,
        "final_away_goals": 1,
        "reached_ot": False,
        "decided_by_shootout": False,
        "home_won": True,
        "n_phantom_goals": 0,
    }
    base.update(kw)
    return base


def _api_game(**kw) -> dict:
    base = {
        "season": 2013,
        "game_id": 20001,
        "date": "2013-10-01",
        "home_team": "TOR",
        "away_team": "MTL",
        "home_score": 2,
        "away_score": 1,
        "last_period_type": "REG",
        "game_type": 2,
    }
    base.update(kw)
    return base


def test_reconcile_clean_regulation_game() -> None:
    recs = reconcile_games_with_nhl_api(pd.DataFrame([_mp_game()]), pd.DataFrame([_api_game()]))
    assert recs[0].n_games_sampled == 1
    assert recs[0].n_games_failed == 0


def test_reconcile_shootout_score_convention() -> None:
    # MP records 3-3 (shootout leaves no shot rows); API records 4-3 for
    # the SO winner. This must reconcile cleanly.
    mp = _mp_game(
        reg_home_goals=3,
        reg_away_goals=3,
        final_home_goals=3,
        final_away_goals=3,
        reached_ot=True,
        decided_by_shootout=True,
        home_won=True,
    )
    api = _api_game(home_score=4, away_score=3, last_period_type="SO")
    recs = reconcile_games_with_nhl_api(pd.DataFrame([mp]), pd.DataFrame([api]))
    assert recs[0].n_games_failed == 0


def test_reconcile_catches_score_mismatch_and_outcome_disagreement() -> None:
    mp_rows = [
        _mp_game(game_id=20001, final_home_goals=5),  # score mismatch
        _mp_game(game_id=20002, reached_ot=True),  # API says REG
    ]
    api_rows = [_api_game(game_id=20001), _api_game(game_id=20002)]
    recs = reconcile_games_with_nhl_api(pd.DataFrame(mp_rows), pd.DataFrame(api_rows))
    assert recs[0].n_games_failed == 2


def test_reconcile_catches_shootout_flag_disagreement() -> None:
    # API says shootout (SO); panel doesn't think this game went to a
    # shootout at all.
    mp = _mp_game(decided_by_shootout=False)
    api = _api_game(last_period_type="SO")
    recs = reconcile_games_with_nhl_api(pd.DataFrame([mp]), pd.DataFrame([api]))
    assert recs[0].n_games_failed == 1
    assert any("API says shootout" in i.message for i in recs[0].issues)


def test_reconcile_catches_shootout_with_untied_moneypuck_score() -> None:
    # API says SO, panel agrees it's a shootout, but the panel's own
    # recorded score isn't tied -- internally inconsistent.
    mp = _mp_game(reached_ot=True, decided_by_shootout=True, final_home_goals=3, final_away_goals=2)
    api = _api_game(last_period_type="SO", home_score=4, away_score=2)
    recs = reconcile_games_with_nhl_api(pd.DataFrame([mp]), pd.DataFrame([api]))
    assert recs[0].n_games_failed == 1
    assert any("not tied" in i.message for i in recs[0].issues)


def test_reconcile_catches_shootout_winner_disagreement() -> None:
    # Tied MoneyPuck score, correct SO score convention, but the recorded
    # winner disagrees with which side the API credits the extra goal to.
    mp = _mp_game(
        reached_ot=True,
        decided_by_shootout=True,
        final_home_goals=3,
        final_away_goals=3,
        home_won=True,
    )
    api = _api_game(last_period_type="SO", home_score=3, away_score=4)
    recs = reconcile_games_with_nhl_api(pd.DataFrame([mp]), pd.DataFrame([api]))
    assert recs[0].n_games_failed == 1
    assert any("winner disagrees" in i.message for i in recs[0].issues)


def test_reconcile_catches_ot_flag_disagreement() -> None:
    # Scores agree, API says OT, but panel says this was decided by
    # shootout (or didn't reach OT at all) -- outcome flags disagree.
    mp = _mp_game(reached_ot=False, final_home_goals=3, final_away_goals=2)
    api = _api_game(last_period_type="OT", home_score=3, away_score=2)
    recs = reconcile_games_with_nhl_api(pd.DataFrame([mp]), pd.DataFrame([api]))
    assert recs[0].n_games_failed == 1
    assert any("panel outcome flags disagree" in i.message for i in recs[0].issues)


def test_reconcile_flags_unmatched_games() -> None:
    recs = reconcile_games_with_nhl_api(
        pd.DataFrame([_mp_game(game_id=20099)]), pd.DataFrame([_api_game()])
    )
    assert recs[0].n_games_sampled == 0
    assert any("not found in the NHL API" in i.message for i in recs[0].issues)


def _panel_row(**kw) -> dict:
    base = {
        "season": 2013,
        "game_id": 20001,
        "is_home": True,
        "is_playoff": False,
        "non_5v5_flag": False,
        "minute": 45,
        "score_state": "tied",
        "attempts_main": 1,
        "xg_main": 0.05,
        "team_code": "TOR",
        "opp_code": "MTL",
    }
    base.update(kw)
    return base


def test_build_estimation_sample_filters_and_derives(caplog) -> None:
    panel = pd.DataFrame(
        [
            _panel_row(),
            _panel_row(minute=57),  # late
            _panel_row(minute=59),  # outside 41-58 window
            _panel_row(minute=50, is_playoff=True),
            _panel_row(minute=50, non_5v5_flag=True),
            _panel_row(minute=50, score_state="up_2_plus"),  # excluded state
            _panel_row(minute=50, game_id=20002),  # no context -> dropped
        ]
    )
    context = pd.DataFrame(
        [
            {
                "season": 2013,
                "game_id": 20001,
                "home_elo_pre": 1520.0,
                "away_elo_pre": 1480.0,
                "elo_diff_home": 40.0,
                "home_rest_days": 2,
                "away_rest_days": 1,
            }
        ]
    )
    with caplog.at_level("WARNING"):
        sample = build_estimation_sample(panel, context)

    assert len(sample) == 2  # minutes 45 and 57 only
    assert sample["late"].tolist() == [0, 1]
    # Home perspective: own minus opponent.
    assert (sample["elo_diff_100"] == 0.4).all()
    assert (sample["rest_diff"] == 1).all()
    assert any("no NHL API context" in r.message for r in caplog.records)


def test_build_estimation_sample_away_perspective_flips_signs() -> None:
    panel = pd.DataFrame([_panel_row(is_home=False)])
    context = pd.DataFrame(
        [
            {
                "season": 2013,
                "game_id": 20001,
                "home_elo_pre": 1520.0,
                "away_elo_pre": 1480.0,
                "elo_diff_home": 40.0,
                "home_rest_days": 2,
                "away_rest_days": 1,
            }
        ]
    )
    sample = build_estimation_sample(panel, context)
    assert (sample["elo_diff_100"] == -0.4).all()
    assert (sample["rest_diff"] == -1).all()
