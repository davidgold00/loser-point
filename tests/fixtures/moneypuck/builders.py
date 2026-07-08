"""Fixture builders for MoneyPuck-shaped shot rows.

These are hand-built rows that mimic the real column set closely enough to
exercise this project's ingest/schema/reconciliation logic without any
network access. Each `make_*_game` function exists to catch one specific
edge case -- see its docstring.
"""

from __future__ import annotations

import itertools

import pandas as pd

_id_counter = itertools.count(1)


def make_shot_row(
    *,
    game_id: int,
    season: int,
    is_home_team: int,
    home_team_goals: int,
    away_team_goals: int,
    period: int = 1,
    time: int = 30,
    event: str = "SHOT",
    is_playoff_game: int = 0,
    home_team_won: int = 1,
    x_goal: float = 0.05,
) -> dict:
    return {
        "shotID": next(_id_counter),
        "game_id": game_id,
        "season": season,
        "isPlayoffGame": is_playoff_game,
        "homeTeamCode": "TOR",
        "awayTeamCode": "MTL",
        "homeTeamWon": home_team_won,
        "period": period,
        "time": time,
        "team": "HOME" if is_home_team else "AWAY",
        "isHomeTeam": is_home_team,
        "event": event,
        "goal": 1 if event == "GOAL" else 0,
        "homeTeamGoals": home_team_goals,
        "awayTeamGoals": away_team_goals,
        "xGoal": max(x_goal, 0.5) if event == "GOAL" else x_goal,
        "homeSkatersOnIce": 5,
        "awaySkatersOnIce": 5,
        "homeEmptyNet": 0,
        "awayEmptyNet": 0,
        "shotOnEmptyNet": 0,
        "teamCode": "TOR" if is_home_team else "MTL",
    }


def make_clean_game(game_id: int, season: int) -> list[dict]:
    """A simple, internally consistent game: home scores twice, away once,
    home wins 2-1 in regulation.
    """
    return [
        make_shot_row(
            game_id=game_id,
            season=season,
            period=1,
            time=100,
            is_home_team=1,
            event="SHOT",
            home_team_goals=0,
            away_team_goals=0,
        ),
        make_shot_row(
            game_id=game_id,
            season=season,
            period=1,
            time=300,
            is_home_team=1,
            event="GOAL",
            home_team_goals=0,
            away_team_goals=0,
        ),
        make_shot_row(
            game_id=game_id,
            season=season,
            period=2,
            time=800,
            is_home_team=0,
            event="GOAL",
            home_team_goals=1,
            away_team_goals=0,
        ),
        make_shot_row(
            game_id=game_id,
            season=season,
            period=3,
            time=3500,
            is_home_team=1,
            event="GOAL",
            home_team_goals=1,
            away_team_goals=1,
        ),
    ]


def make_shootout_game(game_id: int, season: int) -> list[dict]:
    """Regulation + OT end tied 1-1; homeTeamWon=1 reflects a shootout
    decision that leaves no shot-event trace at all, per
    docs/decisions/0003-moneypuck-data-quirks.md.
    """
    return [
        make_shot_row(
            game_id=game_id,
            season=season,
            period=1,
            time=200,
            is_home_team=1,
            event="GOAL",
            home_team_goals=0,
            away_team_goals=0,
        ),
        make_shot_row(
            game_id=game_id,
            season=season,
            period=2,
            time=1500,
            is_home_team=0,
            event="GOAL",
            home_team_goals=1,
            away_team_goals=0,
        ),
        make_shot_row(
            game_id=game_id,
            season=season,
            period=4,
            time=3660,
            is_home_team=1,
            event="SHOT",
            home_team_goals=1,
            away_team_goals=1,
        ),
    ]


def make_phantom_goal_game(game_id: int, season: int) -> list[dict]:
    """Not broken: reproduces a confirmed real MoneyPuck quirk where a
    team's running score increments with no corresponding `GOAL`-tagged row
    anywhere nearby (confirmed on 2013 game 20451 -- see
    docs/decisions/0003-moneypuck-data-quirks.md). The running score is
    still monotonic, so `check_game_goal_counts` must NOT flag this: score
    monotonicity is the only invariant it enforces, deliberately not
    equality against counted GOAL rows.
    """
    return [
        make_shot_row(
            game_id=game_id,
            season=season,
            period=1,
            time=100,
            is_home_team=1,
            event="SHOT",
            home_team_goals=0,
            away_team_goals=0,
        ),
        # The score jumps to 1 with no GOAL row anywhere causing it.
        make_shot_row(
            game_id=game_id,
            season=season,
            period=2,
            time=800,
            is_home_team=1,
            event="SHOT",
            home_team_goals=1,
            away_team_goals=0,
        ),
    ]


def make_decreasing_score_game(game_id: int, season: int) -> list[dict]:
    """Broken: homeTeamGoals decreases within the game. Exercises the
    monotonicity branch of check_game_goal_counts.
    """
    return [
        make_shot_row(
            game_id=game_id,
            season=season,
            period=1,
            time=100,
            is_home_team=1,
            event="SHOT",
            home_team_goals=1,
            away_team_goals=0,
        ),
        make_shot_row(
            game_id=game_id,
            season=season,
            period=2,
            time=800,
            is_home_team=1,
            event="SHOT",
            home_team_goals=0,
            away_team_goals=0,
        ),
    ]


def games_to_frame(*games: list[dict]) -> pd.DataFrame:
    rows = [row for game in games for row in game]
    return pd.DataFrame(rows)
