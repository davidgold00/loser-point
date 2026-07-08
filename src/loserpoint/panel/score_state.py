"""Score-state reconstruction: the panel's load-bearing module.

Reconstructs, for one game at a time, the goal timeline and the score state
*entering* every regulation minute (1-60), from raw MoneyPuck shot rows.
Every convention here is specified in
docs/decisions/0006-score-state-construction.md and locked by both unit
tests (tests/unit/test_score_state.py) and hand-verified real games
(tests/golden/). The three rules most worth restating at the top:

1. **Minute boundary:** minute N covers seconds (60*(N-1), 60*N] --
   `minute_of_time(t) = max(1, ceil(t/60))`. The max() clamp puts real
   t=0 rows into minute 1.
2. **Entering state:** the state entering minute N counts goals whose
   *minute* is <= N-1. Comparing minutes (not raw second thresholds) keeps
   the t=0 clamp consistent: a goal at t=0 is in minute 1, so minute 1 is
   still entered tied.
3. **Running score is ground truth:** goals are reconstructed by walking
   the running score-before columns, not by counting GOAL rows, because
   real data contains "phantom" goals with no GOAL row of their own
   (decision 0003).
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from loserpoint.utils.logging import get_logger

logger = get_logger(__name__)

REGULATION_SECONDS = 3600
REGULATION_MINUTES = 60
REGULATION_MAX_PERIOD = 3

STATE_BINS = ("down_2_plus", "down_1", "tied", "up_1", "up_2_plus")

MIRROR_STATE = {
    "tied": "tied",
    "up_1": "down_1",
    "down_1": "up_1",
    "up_2_plus": "down_2_plus",
    "down_2_plus": "up_2_plus",
}


class InconsistentGameError(ValueError):
    """A game's recorded running score decreased -- the data is corrupt and
    the game must be rejected, never silently patched."""


@dataclass(frozen=True)
class GoalEvent:
    """One reconstructed goal.

    `is_phantom` marks goals recovered from running-score jumps rather than
    a GOAL row; their `time` is the observing row's time, an upper bound on
    the true goal time (decision 0006, rule 3).
    """

    time: int
    is_home_team: bool
    is_phantom: bool
    period: int

    @property
    def is_regulation(self) -> bool:
        return self.period <= REGULATION_MAX_PERIOD and self.time <= REGULATION_SECONDS


@dataclass(frozen=True)
class GameOutcomes:
    """Game-level outcome variables derived from the goal timeline.

    Interpretation: `reached_ot` is the paper's key *outcome* (the panel
    itself is regulation-only); `decided_by_shootout` refines it;
    `final_*_goals` are recorded (shot-data) totals and exclude shootout
    deciders, which leave no shot rows.
    """

    game_id: int
    season: int
    is_playoff: bool
    reg_home_goals: int
    reg_away_goals: int
    final_home_goals: int
    final_away_goals: int
    reached_ot: bool
    decided_by_shootout: bool
    home_won: bool
    n_phantom_goals: int


def minute_of_time(time: int) -> int:
    """Map game seconds to the game minute containing them.

    Minute N covers (60*(N-1), 60*N]; t=0 clamps into minute 1 (the only
    closed-left minute -- see decision 0006, rule 1).
    """
    return max(1, -(-time // 60))  # -(-x // 60) is ceil(x/60) for ints


def score_state_label(diff: int) -> str:
    """Bin a goal differential into the five score states of config.yaml."""
    if diff <= -2:
        return "down_2_plus"
    if diff == -1:
        return "down_1"
    if diff == 0:
        return "tied"
    if diff == 1:
        return "up_1"
    return "up_2_plus"


def extract_goal_events(game: pd.DataFrame) -> list[GoalEvent]:
    """Reconstruct a single game's goal timeline from its shot rows.

    Walks rows in shotID order maintaining a running tally. GOAL rows add a
    goal at their exact time; rows whose recorded score-before exceeds the
    tally reveal phantom goals, emitted at the observing row's time.

    Args:
        game: all shot rows of exactly one game.

    Returns:
        Goals in chronological (walk) order, including overtime goals --
        callers filter to regulation via `GoalEvent.is_regulation`.

    Raises:
        InconsistentGameError: if the recorded running score ever decreases
            below the tally. Games passing ingest reconciliation can't
            trigger this, but the module defends itself rather than
            trusting its caller.
    """
    goals: list[GoalEvent] = []
    home_tally = away_tally = 0
    for row in game.sort_values("shotID").itertuples(index=False):
        if row.homeTeamGoals < home_tally or row.awayTeamGoals < away_tally:
            raise InconsistentGameError(
                f"game {row.game_id}: recorded score {row.homeTeamGoals}-"
                f"{row.awayTeamGoals} before shotID {row.shotID} is below the "
                f"reconstructed tally {home_tally}-{away_tally}. This game's "
                "data is corrupt; it should have been caught by ingest "
                "reconciliation (validate/checks.py)."
            )
        while home_tally < row.homeTeamGoals:
            goals.append(
                GoalEvent(time=row.time, is_home_team=True, is_phantom=True, period=row.period)
            )
            home_tally += 1
        while away_tally < row.awayTeamGoals:
            goals.append(
                GoalEvent(time=row.time, is_home_team=False, is_phantom=True, period=row.period)
            )
            away_tally += 1
        if row.event == "GOAL":
            goals.append(
                GoalEvent(
                    time=row.time,
                    is_home_team=bool(row.isHomeTeam),
                    is_phantom=False,
                    period=row.period,
                )
            )
            if row.isHomeTeam:
                home_tally += 1
            else:
                away_tally += 1
    return goals


def minute_states(goals: list[GoalEvent]) -> pd.DataFrame:
    """Compute the score entering every regulation minute from a goal list.

    Interpretation: row N answers "what was the score when minute N began?"
    -- the decision-relevant state for teams choosing how hard to play
    during minute N. A goal scored *during* minute N first appears in row
    N+1 (and a goal in minute 60 therefore never appears at all).

    Args:
        goals: the game's goal events; overtime goals are ignored here.

    Returns:
        DataFrame with one row per minute 1-60 and columns `minute`,
        `home_score`, `away_score`, `home_state`, `away_state`.
    """
    reg_goal_minutes = [(minute_of_time(g.time), g.is_home_team) for g in goals if g.is_regulation]
    rows = []
    for minute in range(1, REGULATION_MINUTES + 1):
        home = sum(1 for m, is_home in reg_goal_minutes if m < minute and is_home)
        away = sum(1 for m, is_home in reg_goal_minutes if m < minute and not is_home)
        diff = home - away
        rows.append(
            {
                "minute": minute,
                "home_score": home,
                "away_score": away,
                "home_state": score_state_label(diff),
                "away_state": score_state_label(-diff),
            }
        )
    return pd.DataFrame(rows)


def game_outcomes(game: pd.DataFrame) -> GameOutcomes:
    """Derive game-level outcomes from one game's shot rows.

    See GameOutcomes for interpretation. Shootout detection relies on
    decision 0003: a regular-season game whose entire recorded goal
    timeline ends tied, yet has a recorded winner, was decided in a
    shootout (shootout goals leave no shot rows).
    """
    goals = extract_goal_events(game)
    first = game.iloc[0]
    is_playoff = bool(first["isPlayoffGame"])

    reg_home = sum(1 for g in goals if g.is_regulation and g.is_home_team)
    reg_away = sum(1 for g in goals if g.is_regulation and not g.is_home_team)
    final_home = sum(1 for g in goals if g.is_home_team)
    final_away = sum(1 for g in goals if not g.is_home_team)

    decided_by_shootout = not is_playoff and final_home == final_away
    if is_playoff and final_home == final_away:
        logger.warning(
            "playoff game %s has a tied recorded final score %d-%d -- playoff "
            "games cannot end tied, so this game's shot data is incomplete.",
            first["game_id"],
            final_home,
            final_away,
        )

    return GameOutcomes(
        game_id=int(first["game_id"]),
        season=int(first["season"]),
        is_playoff=is_playoff,
        reg_home_goals=reg_home,
        reg_away_goals=reg_away,
        final_home_goals=final_home,
        final_away_goals=final_away,
        reached_ot=reg_home == reg_away,
        decided_by_shootout=decided_by_shootout,
        home_won=bool(first["homeTeamWon"]),
        n_phantom_goals=sum(1 for g in goals if g.is_phantom),
    )
