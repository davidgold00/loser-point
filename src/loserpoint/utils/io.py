"""Parquet read/write helpers with schema enforcement on read.

Downstream analysis code should never call `pandas.read_parquet` directly —
routing every read through `read_parquet_validated` guarantees a pandera
schema mismatch is caught at the point of load, not three functions later
inside a model that silently produces garbage.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import pandas as pd

from loserpoint.utils.logging import get_logger

if TYPE_CHECKING:
    from pandera.pandas import DataFrameSchema

logger = get_logger(__name__)


def write_parquet(df: pd.DataFrame, path: Path | str) -> None:
    """Write `df` to `path` as parquet, creating parent directories as needed.

    Args:
        df: Table to persist.
        path: Destination file path.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(path, index=False)
    logger.info("wrote %s rows to %s", len(df), path)


def read_parquet_validated(path: Path | str, schema: DataFrameSchema) -> pd.DataFrame:
    """Read a parquet file and validate it against a pandera schema.

    Args:
        path: Parquet file to read.
        schema: Pandera schema the table must satisfy.

    Returns:
        The validated DataFrame.

    Raises:
        FileNotFoundError: if `path` does not exist, with a message naming
            the missing file and which pipeline stage should have produced it.
        pandera.errors.SchemaError: if validation fails; pandera's error
            message enumerates the exact rows/columns that violated the schema.
    """
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(
            f"Expected data file not found: {path}. Run the pipeline stage "
            "that produces this file (see Makefile targets) before continuing."
        )
    df = pd.read_parquet(path)
    validated = schema.validate(df, lazy=True)
    logger.info("read+validated %s rows from %s", len(validated), path)
    return validated
