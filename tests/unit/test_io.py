"""Unit tests for loserpoint.utils.io — parquet round-trip and schema
enforcement on read.
"""

from __future__ import annotations

import pandas as pd
import pandera.pandas as pa
import pytest
from loserpoint.utils.io import read_parquet_validated, write_parquet

SIMPLE_SCHEMA = pa.DataFrameSchema(
    {
        "game_id": pa.Column(int),
        "shot_attempts": pa.Column(int, checks=pa.Check.ge(0)),
    }
)


def test_write_then_read_round_trips(tmp_path) -> None:
    df = pd.DataFrame({"game_id": [1, 2], "shot_attempts": [10, 20]})
    path = tmp_path / "nested" / "table.parquet"

    write_parquet(df, path)
    result = read_parquet_validated(path, SIMPLE_SCHEMA)

    pd.testing.assert_frame_equal(result.reset_index(drop=True), df)


def test_read_missing_file_raises_with_guidance(tmp_path) -> None:
    missing = tmp_path / "does_not_exist.parquet"
    with pytest.raises(FileNotFoundError, match="Expected data file not found"):
        read_parquet_validated(missing, SIMPLE_SCHEMA)


def test_read_validates_schema_and_rejects_violations(tmp_path) -> None:
    df = pd.DataFrame({"game_id": [1, 2], "shot_attempts": [-5, 20]})
    path = tmp_path / "bad.parquet"
    write_parquet(df, path)

    with pytest.raises(pa.errors.SchemaErrors):
        read_parquet_validated(path, SIMPLE_SCHEMA)
