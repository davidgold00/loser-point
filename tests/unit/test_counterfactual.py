"""Unit tests for analysis/counterfactual.py."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
from loserpoint.analysis.counterfactual import (
    POINT_SYSTEMS,
    PointSystem,
    compute_standings,
    playoff_qualifiers,
    rank_teams,
    run_counterfactual,
    validate_actual_standings,
)

ACTUAL, THREE_TWO_ONE, NO_LOSER_POINT = POINT_SYSTEMS


def _game(**kw) -> dict:
    base = {
        "season": 2014,
        "game_id": 20001,
        "date": "2015-01-01",
        "home_team": "AAA",
        "away_team": "BBB",
        "home_score": 3,
        "away_score": 2,
        "last_period_type": "REG",
        "game_type": 2,
    }
    base.update(kw)
    return base


def test_compute_standings_actual_system() -> None:
    games = pd.DataFrame(
        [
            _game(game_id=1),  # AAA reg win
            _game(game_id=2, last_period_type="OT"),  # AAA OT win, BBB loser point
            _game(game_id=3, home_score=2, away_score=3, last_period_type="SO"),
            _game(game_id=4, game_type=3),  # playoff game must be ignored
        ]
    )
    standings = compute_standings(games, ACTUAL).set_index("team")
    assert standings.loc["AAA", "games_played"] == 3
    # reg win (2) + OT win (2) + SO loss (1)
    assert standings.loc["AAA", "points"] == 5
    # reg loss (0) + OT loss (1) + SO win (2)
    assert standings.loc["BBB", "points"] == 3
    assert standings.loc["AAA", "wins"] == 2
    # SO wins don't count toward regulation+OT wins
    assert standings.loc["BBB", "row_wins"] == 0
    assert standings.loc["AAA", "row_wins"] == 2
    assert standings.loc["AAA", "goal_diff"] == -standings.loc["BBB", "goal_diff"]


def test_compute_standings_counterfactual_systems() -> None:
    games = pd.DataFrame(
        [
            _game(game_id=1),  # AAA reg win
            _game(game_id=2, last_period_type="OT"),  # AAA OT win
        ]
    )
    three = compute_standings(games, THREE_TWO_ONE).set_index("team")
    assert three.loc["AAA", "points"] == 5  # 3 + 2
    assert three.loc["BBB", "points"] == 1  # 0 + 1
    flat = compute_standings(games, NO_LOSER_POINT).set_index("team")
    assert flat.loc["AAA", "points"] == 4
    assert flat.loc["BBB", "points"] == 0


def test_compute_standings_applies_rule_84_2_forfeiture() -> None:
    # The real key: 2023-24 game 21166, MIN lost in OT with the goalie
    # pulled and forfeited the loser point (decision 0015).
    games = pd.DataFrame(
        [
            _game(
                season=2023,
                game_id=21166,
                home_team="MIN",
                away_team="VGK",
                home_score=1,
                away_score=2,
                last_period_type="OT",
            )
        ]
    )
    standings = compute_standings(games, ACTUAL).set_index("team")
    assert standings.loc["MIN", "points"] == 0
    assert standings.loc["VGK", "points"] == 2


def test_rank_teams_tiebreak_cascade() -> None:
    standings = pd.DataFrame(
        {
            "season": [2014] * 3,
            "team": ["AAA", "BBB", "CCC"],
            "points": [90, 90, 95],
            "row_wins": [40, 38, 30],
            "wins": [42, 42, 40],
            "goal_diff": [10, 20, 5],
        }
    )
    standings["rank"] = rank_teams(standings, ["season"])
    by_team = standings.set_index("team")["rank"]
    assert by_team["CCC"] == 1  # most points
    assert by_team["AAA"] == 2  # ties BBB on points, wins ROW tiebreak
    assert by_team["BBB"] == 3


def _league(season: int, n_per_division: int = 5) -> pd.DataFrame:
    """A synthetic 2-conference x 2-division league with strictly ordered
    points so qualification is unambiguous. Division names are unique
    across conferences, as they are in every real NHL era."""
    rows = []
    points = 100
    for conference in ("East", "West"):
        for division in (f"{conference[0]}D1", f"{conference[0]}D2"):
            for i in range(n_per_division):
                rows.append(
                    {
                        "season": season,
                        "team": f"{division}{i}",
                        "conference": conference,
                        "division": division,
                        "points": points,
                        "row_wins": 1,
                        "wins": 1,
                        "goal_diff": 0,
                        "games_played": 82,
                        "system": "actual",
                    }
                )
                points -= 1
    return pd.DataFrame(rows)


def _alignment(league: pd.DataFrame) -> pd.DataFrame:
    return league[["season", "team", "conference", "division"]]


def test_playoff_qualifiers_wildcard_era() -> None:
    league = _league(2014)
    flags = pd.DataFrame([{"season": 2014, "wildcard_in_use": True, "conferences_in_use": True}])
    result = playoff_qualifiers(
        league.drop(columns=["conference", "division"]), _alignment(league), flags
    )
    assert int(result["qualified"].sum()) == 16
    # Top 3 in each division qualify even though East D1's 4th/5th teams
    # outrank everyone in D2 on points: the wildcard spots then go to the
    # two best remaining, which ARE ED1's 4th and 5th teams.
    by_team = result.set_index("team")["qualified"]
    assert by_team[["ED10", "ED11", "ED12", "ED13", "ED14"]].all()
    assert by_team[["ED20", "ED21", "ED22"]].all()
    assert not by_team[["ED23", "ED24"]].any()


def test_playoff_qualifiers_conference_era_top_8() -> None:
    league = _league(2010)
    flags = pd.DataFrame([{"season": 2010, "wildcard_in_use": False, "conferences_in_use": True}])
    result = playoff_qualifiers(
        league.drop(columns=["conference", "division"]), _alignment(league), flags
    )
    by_team = result.set_index("team")["qualified"]
    # Pure top-8 by points per conference: all of ED1 (5) + ED2's top 3.
    assert by_team[[f"ED1{i}" for i in range(5)]].all()
    assert by_team[["ED20", "ED21", "ED22"]].all()
    assert not by_team[["ED23", "ED24"]].any()


def test_playoff_qualifiers_no_conference_era_top_4_per_division() -> None:
    league = _league(2020)
    flags = pd.DataFrame([{"season": 2020, "wildcard_in_use": False, "conferences_in_use": False}])
    result = playoff_qualifiers(
        league.drop(columns=["conference", "division"]), _alignment(league), flags
    )
    per_division = result[result["qualified"]].groupby("division")["team"].count()
    assert (per_division == 4).all()  # top 4 in each of the 4 divisions


def test_playoff_qualifiers_excludes_covid_2019() -> None:
    league = _league(2019)
    flags = pd.DataFrame([{"season": 2019, "wildcard_in_use": False, "conferences_in_use": True}])
    result = playoff_qualifiers(
        league.drop(columns=["conference", "division"]), _alignment(league), flags
    )
    assert not result["qualified"].any()


def test_validate_actual_standings_passes_and_catches() -> None:
    computed = pd.DataFrame(
        [
            {
                "season": 2014,
                "team": "AAA",
                "games_played": 82,
                "points": 100,
                "wins": 45,
                "row_wins": 40,
                "goal_diff": 30,
            }
        ]
    )
    official = computed.copy()
    assert validate_actual_standings(computed, official) == []
    official.loc[0, "points"] = 99
    problems = validate_actual_standings(computed, official)
    assert len(problems) == 1
    assert "points computed=100 official=99" in problems[0]


def test_run_counterfactual_summary_shape() -> None:
    rng = np.random.default_rng(3)
    league = _league(2014)
    games = []
    teams = list(league["team"])
    for i in range(300):
        home, away = rng.choice(teams, size=2, replace=False)
        outcome = ("REG", "OT", "SO")[int(rng.integers(0, 3))]
        home_score, away_score = (3, 2) if rng.random() < 0.5 else (2, 3)
        games.append(
            _game(
                game_id=i,
                home_team=home,
                away_team=away,
                home_score=home_score,
                away_score=away_score,
                last_period_type=outcome,
            )
        )
    flags = pd.DataFrame([{"season": 2014, "wildcard_in_use": True, "conferences_in_use": True}])
    standings, summary = run_counterfactual(pd.DataFrame(games), _alignment(league), flags)
    assert set(standings["system"]) == {"actual", "three_two_one", "no_loser_point"}
    assert set(summary["system"]) == {"three_two_one", "no_loser_point"}
    assert (summary["berth_flips"] >= 0).all()
    assert (summary["mean_abs_points_delta"] >= 0).all()


def test_point_system_is_frozen() -> None:
    with pytest.raises(AttributeError):
        PointSystem("x", reg_win=2, ot_win=2, ot_loss=1, reg_loss=0).reg_win = 3
