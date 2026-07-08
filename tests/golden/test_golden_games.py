"""Golden-game tests: real games, hand-verified expectations.

Each committed CSV in tests/golden/games/ holds the *raw* rows of one real
game (pre-ingest-cleaning, so the 2007 duplicated-block game exercises the
dedup path too). The test runs the same cleaning steps as ingest_season,
then the full score-state reconstruction, and compares against the
hand-derived expectations in expectations.py. Any refactor that breaks a
golden game is wrong by definition.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest
from loserpoint.ingest.moneypuck import (
    _drop_duplicated_game_blocks,
    _drop_impossible_skater_count_rows,
)
from loserpoint.panel.score_state import extract_goal_events, game_outcomes, minute_states

from tests.golden.expectations import GOLDEN_GAMES

GAMES_DIR = Path(__file__).parent / "games"


def _load_cleaned(season: int, game_id: int) -> pd.DataFrame:
    raw = pd.read_csv(GAMES_DIR / f"{season}_{game_id}.csv")
    cleaned = _drop_impossible_skater_count_rows(raw, season)
    return _drop_duplicated_game_blocks(cleaned, season)


def _expected_state_by_minute(ranges: list[tuple[int, int, str]]) -> dict[int, str]:
    by_minute = {}
    for first, last, state in ranges:
        for minute in range(first, last + 1):
            by_minute[minute] = state
    return by_minute


@pytest.mark.parametrize(("season", "game_id"), sorted(GOLDEN_GAMES))
def test_golden_expectations_cover_all_sixty_minutes(season: int, game_id: int) -> None:
    # Guard the fixture itself: the hand-written ranges must tile 1-60
    # exactly, with no gaps or overlaps.
    ranges = GOLDEN_GAMES[(season, game_id)]["home_states"]
    covered = sorted(m for first, last, _ in ranges for m in range(first, last + 1))
    assert covered == list(range(1, 61))


@pytest.mark.parametrize(("season", "game_id"), sorted(GOLDEN_GAMES))
def test_golden_minute_states(season: int, game_id: int) -> None:
    game = _load_cleaned(season, game_id)
    states = minute_states(extract_goal_events(game)).set_index("minute")
    expected = _expected_state_by_minute(GOLDEN_GAMES[(season, game_id)]["home_states"])
    mismatches = {
        minute: (states.loc[minute, "home_state"], want)
        for minute, want in expected.items()
        if states.loc[minute, "home_state"] != want
    }
    assert not mismatches, f"{season} game {game_id}: (got, want) by minute: {mismatches}"


@pytest.mark.parametrize(("season", "game_id"), sorted(GOLDEN_GAMES))
def test_golden_outcomes(season: int, game_id: int) -> None:
    game = _load_cleaned(season, game_id)
    expected = GOLDEN_GAMES[(season, game_id)]
    out = game_outcomes(game)
    assert (out.reg_home_goals, out.reg_away_goals) == expected["reg_score"]
    assert (out.final_home_goals, out.final_away_goals) == expected["final_score"]
    assert out.reached_ot == expected["reached_ot"]
    assert out.decided_by_shootout == expected["decided_by_shootout"]
    assert out.home_won == expected["home_won"]
    assert out.is_playoff == expected["is_playoff"]
    assert out.n_phantom_goals == expected["n_phantom_goals"]
