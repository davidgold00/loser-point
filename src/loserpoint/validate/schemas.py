"""Pandera schemas for every table at every pipeline stage.

Only the columns this project's analysis actually depends on are validated
in detail; MoneyPuck ships ~124 columns per shot and this project does not
encode correctness constraints for player-level time-on-ice diagnostics it
never reads (see `docs/data_dictionaries/moneypuck_shots_raw.md` for the
full column list and `docs/decisions/0003-moneypuck-data-quirks.md` for why).
Schemas are non-strict: unrecognized extra columns pass through unchanged
rather than failing validation.
"""

from __future__ import annotations

from pandera.pandas import Check, Column, DataFrameSchema

# Regulation is periods 1-3. Period 4 is overtime (3-on-3, 5 minutes, in the
# regular season; 5-on-5, 20 minutes, in the playoffs). Periods 5+ occur only
# in playoff games that reach a second-or-later overtime. 12 is a generous
# sanity ceiling (no NHL game has approached double-digit overtimes), not a
# rule derived from anything -- it exists purely to catch corrupted data.
MAX_PLAUSIBLE_PERIOD = 12

RAW_SHOTS_SCHEMA = DataFrameSchema(
    {
        # Despite the upstream dictionary calling shotID "a unique id for
        # each shot", it is only unique *within a game* -- it's a per-game
        # sequential counter (0, 1, 2, ...) that resets every game_id, not a
        # season-wide id. The real primary key is (game_id, shotID); see the
        # schema-level `unique=` below and decision 0003.
        "shotID": Column(int, nullable=False),
        "game_id": Column(int, Check.gt(0), nullable=False),
        "season": Column(int, Check.in_range(1999, 2100), nullable=False),
        "isPlayoffGame": Column(int, Check.isin([0, 1]), nullable=False),
        "homeTeamCode": Column(str, Check.str_length(min_value=2, max_value=4), nullable=False),
        "awayTeamCode": Column(str, Check.str_length(min_value=2, max_value=4), nullable=False),
        # The only reliable source of the shootout winner: goals scored in a
        # shootout are not recorded as shot events at all. See decision 0003.
        "homeTeamWon": Column(int, Check.isin([0, 1]), nullable=False),
        "period": Column(int, Check.in_range(1, MAX_PLAUSIBLE_PERIOD), nullable=False),
        "time": Column(int, Check.ge(0), nullable=False),
        "team": Column(str, Check.isin(["HOME", "AWAY"]), nullable=False),
        "isHomeTeam": Column(int, Check.isin([0, 1]), nullable=False),
        "event": Column(str, Check.isin(["SHOT", "MISS", "GOAL"]), nullable=False),
        "goal": Column(int, Check.isin([0, 1]), nullable=False),
        # Score entering this shot, i.e. before it resolves; add `goal` to
        # get the score after.
        "homeTeamGoals": Column(int, Check.ge(0), nullable=False),
        "awayTeamGoals": Column(int, Check.ge(0), nullable=False),
        "xGoal": Column(float, Check.in_range(0.0, 1.0), nullable=False),
        "homeSkatersOnIce": Column(int, Check.in_range(0, 6), nullable=False),
        "awaySkatersOnIce": Column(int, Check.in_range(0, 6), nullable=False),
        "homeEmptyNet": Column(int, Check.isin([0, 1]), nullable=False),
        "awayEmptyNet": Column(int, Check.isin([0, 1]), nullable=False),
        "shotOnEmptyNet": Column(int, Check.isin([0, 1]), nullable=False),
        "teamCode": Column(str, Check.str_length(min_value=2, max_value=4), nullable=False),
    },
    unique=["game_id", "shotID"],
    strict=False,
    coerce=False,
)

_SCORE_STATES = ["down_2_plus", "down_1", "tied", "up_1", "up_2_plus"]

# One row per game x team x regulation minute. See build_panel.py and
# docs/data_dictionaries/panel_tables.md for column semantics.
PANEL_MINUTES_SCHEMA = DataFrameSchema(
    {
        "game_id": Column(int, Check.gt(0), nullable=False),
        "season": Column(int, Check.in_range(1999, 2100), nullable=False),
        "is_playoff": Column(bool, nullable=False),
        "is_home": Column(bool, nullable=False),
        "team_code": Column(str, Check.str_length(min_value=2, max_value=4), nullable=False),
        "opp_code": Column(str, Check.str_length(min_value=2, max_value=4), nullable=False),
        "minute": Column(int, Check.in_range(1, 60), nullable=False),
        "score_state": Column(str, Check.isin(_SCORE_STATES), nullable=False),
        # A team can't lead by more than the max goals ever scored in an
        # NHL game; +/-20 is a corruption guard, not a rule.
        "score_diff": Column(int, Check.in_range(-20, 20), nullable=False),
        "goals_for": Column(int, Check.in_range(0, 10), nullable=False),
        "attempts_main": Column(int, Check.ge(0), nullable=False),
        "xg_main": Column(float, Check.ge(0.0), nullable=False),
        "attempts_5v5_incl_en": Column(int, Check.ge(0), nullable=False),
        "xg_5v5_incl_en": Column(float, Check.ge(0.0), nullable=False),
        "attempts_all_ex_en": Column(int, Check.ge(0), nullable=False),
        "xg_all_ex_en": Column(float, Check.ge(0.0), nullable=False),
        "attempts_naive": Column(int, Check.ge(0), nullable=False),
        "xg_naive": Column(float, Check.ge(0.0), nullable=False),
        "non_5v5_flag": Column(bool, nullable=False),
    },
    # NHL game_ids restart every season; the panel key is (season, game_id).
    unique=["season", "game_id", "is_home", "minute"],
    strict=False,
    coerce=False,
)

# One row per game: outcome variables for the reached-OT analyses.
PANEL_GAMES_SCHEMA = DataFrameSchema(
    {
        "game_id": Column(int, Check.gt(0), nullable=False),
        "season": Column(int, Check.in_range(1999, 2100), nullable=False),
        "is_playoff": Column(bool, nullable=False),
        "home_team": Column(str, nullable=False),
        "away_team": Column(str, nullable=False),
        "reg_home_goals": Column(int, Check.in_range(0, 20), nullable=False),
        "reg_away_goals": Column(int, Check.in_range(0, 20), nullable=False),
        "final_home_goals": Column(int, Check.in_range(0, 20), nullable=False),
        "final_away_goals": Column(int, Check.in_range(0, 20), nullable=False),
        "reached_ot": Column(bool, nullable=False),
        "decided_by_shootout": Column(bool, nullable=False),
        "home_won": Column(bool, nullable=False),
        "n_phantom_goals": Column(int, Check.ge(0), nullable=False),
    },
    unique=["season", "game_id"],
    strict=False,
    coerce=False,
)
