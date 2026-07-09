"""Golden test for the historical (pre-shootout) era: a real Hockey-
Reference boxscore, parsed and checked against hand-derived expectations,
exactly like tests/golden/test_golden_games.py but for the 1999-2006
goals-only data source (ingest.hockey_reference, not moneypuck).
"""

from __future__ import annotations

from pathlib import Path

import pytest
from loserpoint.ingest.hockey_reference import parse_boxscore_goals
from loserpoint.panel.score_state import minute_states

from tests.golden.expectations import HISTORICAL_GOLDEN_GAMES

GAMES_DIR = Path(__file__).parent / "games"


def _expected_state_by_minute(ranges: list[tuple[int, int, str]]) -> dict[int, str]:
    return {m: state for first, last, state in ranges for m in range(first, last + 1)}


@pytest.mark.parametrize(("season", "game_key"), sorted(HISTORICAL_GOLDEN_GAMES))
def test_historical_golden_expectations_cover_all_sixty_minutes(season: str, game_key: str) -> None:
    ranges = HISTORICAL_GOLDEN_GAMES[(season, game_key)]["home_states"]
    covered = sorted(m for first, last, _ in ranges for m in range(first, last + 1))
    assert covered == list(range(1, 61))


@pytest.mark.parametrize(("season", "game_key"), sorted(HISTORICAL_GOLDEN_GAMES))
def test_historical_golden_minute_states_and_tie_outcome(season: str, game_key: str) -> None:
    expected = HISTORICAL_GOLDEN_GAMES[(season, game_key)]
    html = (GAMES_DIR / f"historical_{season}_{game_key}.html").read_text()
    goals = parse_boxscore_goals(html, home_team=expected["home_team"])
    states = minute_states(goals).set_index("minute")

    expected_by_minute = _expected_state_by_minute(expected["home_states"])
    mismatches = {
        minute: (states.loc[minute, "home_state"], want)
        for minute, want in expected_by_minute.items()
        if states.loc[minute, "home_state"] != want
    }
    assert not mismatches, f"{game_key}: (got, want) by minute: {mismatches}"

    # parse_boxscore_goals only ever returns regulation (period<=3) goals
    # -- OT/SO rows are dropped by design (module docstring). That's exact
    # for this game, which had no OT goals at all (a real tie); it would
    # UNDERSTATE the final score for a game actually decided in OT, which
    # is why the historical panel's regime DiD (regime_did.py) only ever
    # needs regulation-window goals_for, never a reconstructed final score.
    final_home = states.iloc[-1]["home_score"]
    final_away = states.iloc[-1]["away_score"]
    assert (final_home, final_away) == expected["final_score"]
    assert (final_home == final_away) == expected["is_tie"]
