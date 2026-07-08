"""Unit tests for validate.schemas.RAW_SHOTS_SCHEMA."""

from __future__ import annotations

import pandera.errors
import pytest
from loserpoint.validate.schemas import RAW_SHOTS_SCHEMA

from tests.fixtures.moneypuck.builders import games_to_frame, make_clean_game


def test_clean_game_passes_schema() -> None:
    df = games_to_frame(make_clean_game(game_id=20001, season=2013))
    validated = RAW_SHOTS_SCHEMA.validate(df, lazy=True)
    assert len(validated) == len(df)


def test_out_of_range_xgoal_fails() -> None:
    df = games_to_frame(make_clean_game(game_id=20001, season=2013))
    df.loc[0, "xGoal"] = 1.5
    with pytest.raises(pandera.errors.SchemaErrors):
        RAW_SHOTS_SCHEMA.validate(df, lazy=True)


def test_unknown_event_value_fails() -> None:
    df = games_to_frame(make_clean_game(game_id=20001, season=2013))
    df.loc[0, "event"] = "BLOCK"
    with pytest.raises(pandera.errors.SchemaErrors):
        RAW_SHOTS_SCHEMA.validate(df, lazy=True)


def test_duplicate_game_id_shot_id_pair_fails() -> None:
    df = games_to_frame(make_clean_game(game_id=20001, season=2013))
    df.loc[1, "shotID"] = df.loc[0, "shotID"]
    with pytest.raises(pandera.errors.SchemaErrors):
        RAW_SHOTS_SCHEMA.validate(df, lazy=True)


def test_shot_id_repeating_across_different_games_is_valid() -> None:
    # shotID is a per-game sequential counter in real MoneyPuck data, not a
    # season-wide unique id -- see docs/decisions/0003-moneypuck-data-quirks.md.
    # The same shotID value appearing in two different games must pass.
    game_a = make_clean_game(game_id=20001, season=2013)
    game_b = make_clean_game(game_id=20002, season=2013)
    game_b[0]["shotID"] = game_a[0]["shotID"]
    df = games_to_frame(game_a, game_b)
    validated = RAW_SHOTS_SCHEMA.validate(df, lazy=True)
    assert len(validated) == len(df)


def test_extra_columns_pass_through() -> None:
    df = games_to_frame(make_clean_game(game_id=20001, season=2013))
    df["someObscureToiColumn"] = 42
    validated = RAW_SHOTS_SCHEMA.validate(df, lazy=True)
    assert "someObscureToiColumn" in validated.columns
