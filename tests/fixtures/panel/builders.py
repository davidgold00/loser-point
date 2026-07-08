"""Fixture builders for score-state and panel tests.

`make_game_from_goals` constructs a MoneyPuck-shaped single-game DataFrame
from a compact goal specification, computing the running score-before
columns by simple tally. The tally here is deliberately trivial (a running
counter over a sorted list) so these fixtures stay independent of the
walk-and-verify logic in `panel/score_state.py` that they exist to test.
"""

from __future__ import annotations

import pandas as pd

from tests.fixtures.moneypuck.builders import make_shot_row


def make_game_from_goals(
    goals: list[tuple[int, bool]],
    *,
    game_id: int = 20001,
    season: int = 2013,
    is_playoff_game: int = 0,
    home_team_won: int | None = None,
    extra_shots: list[tuple[int, bool]] | None = None,
    phantom: set[int] | None = None,
) -> pd.DataFrame:
    """Build a game's shot rows from goal times.

    Args:
        goals: list of (time_seconds, is_home_team) for each goal, in any
            order; rows are emitted sorted by time.
        game_id: NHL game id (2xxxx regular season, 3xxxx playoffs).
        season: season label.
        is_playoff_game: playoff flag for every row.
        home_team_won: winner flag; if None, inferred from the goal tally
            (ties fall to the home team, standing in for a shootout win).
        extra_shots: list of (time_seconds, is_home_team) non-goal SHOT
            rows to interleave, e.g. to give a phantom goal a later row
            that observes it.
        phantom: indices into `goals` that should NOT get a GOAL row --
            their effect appears only in the running score of later rows,
            reproducing the phantom-goal quirk of decision 0003.

    Returns:
        A single-game DataFrame shaped like raw MoneyPuck shot data.
    """
    phantom = phantom or set()
    events: list[tuple[int, bool, str, int | None]] = [
        (time, is_home, "GOAL", idx) for idx, (time, is_home) in enumerate(goals)
    ]
    for time, is_home in extra_shots or []:
        events.append((time, is_home, "SHOT", None))
    # Stable sort by time keeps same-second events in insertion order,
    # letting tests control ordering of simultaneous events.
    events.sort(key=lambda e: e[0])

    # OT periods: regular-season period 4 is 3600-3900; playoff OTs are
    # full 20-minute periods (4 = 3600-4800, 5 = 4800-6000, ...).
    def period_of(time: int) -> int:
        if time <= 3600:
            return max(1, -(-time // 1200))  # ceil(time/1200), 0 -> 1
        if is_playoff_game:
            return 4 + (time - 3601) // 1200
        return 4

    rows = []
    h = a = 0
    for time, is_home, kind, goal_idx in events:
        is_phantom = kind == "GOAL" and goal_idx in phantom
        if not is_phantom:
            rows.append(
                make_shot_row(
                    game_id=game_id,
                    season=season,
                    period=period_of(time),
                    time=time,
                    is_home_team=int(is_home),
                    event=kind,
                    home_team_goals=h,
                    away_team_goals=a,
                    is_playoff_game=is_playoff_game,
                    home_team_won=0,  # overwritten below once known
                )
            )
        if kind == "GOAL":
            if is_home:
                h += 1
            else:
                a += 1

    if home_team_won is None:
        home_team_won = int(h >= a)
    df = pd.DataFrame(rows)
    if len(df):
        df["homeTeamWon"] = home_team_won
    return df
