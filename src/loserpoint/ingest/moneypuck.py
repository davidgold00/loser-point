"""MoneyPuck shot-level data ingest.

Downloads season-level shot zips from MoneyPuck's CDN host, tracks a
per-season manifest (content hash, row count, download time) so re-runs can
detect upstream data drift, extracts and schema-validates each season, and
loads it into a typed DataFrame. See
`docs/decisions/0003-moneypuck-data-quirks.md` for the upstream quirks this
module was written to account for.
"""

from __future__ import annotations

import hashlib
import json
import zipfile
from pathlib import Path

import pandas as pd
import requests

from loserpoint.utils.logging import get_logger
from loserpoint.validate.schemas import RAW_SHOTS_SCHEMA

logger = get_logger(__name__)

MONEYPUCK_BASE_URL = "https://peter-tanner.com/moneypuck/downloads"
SHOTS_URL_TEMPLATE = MONEYPUCK_BASE_URL + "/shots_{season}.zip"
DATA_DICTIONARY_URL = MONEYPUCK_BASE_URL + "/MoneyPuck_Shot_Data_Dictionary.csv"

# Row counts MoneyPuck itself published in the shot data dictionary's notes
# section (docs/data_dictionaries/MoneyPuck_Shot_Data_Dictionary.csv). Only
# seasons 2007-2018 are listed there; later seasons have no independent
# published total, so reconciliation treats those as "no reference
# available" rather than failing. Verified against a direct download of the
# 2007 and 2013 files during Phase 1 (both matched exactly).
PUBLISHED_SEASON_ROW_COUNTS: dict[int, int] = {
    2007: 106_243,
    2008: 110_023,
    2009: 110_895,
    2010: 111_405,
    2011: 108_753,
    2012: 66_087,
    2013: 110_682,
    2014: 109_627,
    2015: 109_461,
    2016: 110_953,
    2017: 119_715,
    2018: 117_622,
}

# Games MoneyPuck's own dictionary discloses as having missing/incomplete
# shot data. Excluded from reconciliation sampling.
KNOWN_INCOMPLETE_GAMES: dict[int, list[int]] = {
    2008: [259, 409, 1077],
    2009: [81],
}

# Columns this project depends on getting the *numeric* dtype right for;
# string columns are left as pandas' own CSV-inferred object dtype since
# they need no arithmetic. Presence of all of these is checked explicitly
# so a silently renamed/dropped upstream column fails loudly at load time
# rather than surfacing later as a confusing KeyError deep in the panel code.
REQUIRED_COLUMNS: tuple[str, ...] = (
    "shotID",
    "game_id",
    "season",
    "isPlayoffGame",
    "homeTeamCode",
    "awayTeamCode",
    "homeTeamWon",
    "period",
    "time",
    "team",
    "isHomeTeam",
    "event",
    "goal",
    "homeTeamGoals",
    "awayTeamGoals",
    "xGoal",
    "homeSkatersOnIce",
    "awaySkatersOnIce",
    "homeEmptyNet",
    "awayEmptyNet",
    "shotOnEmptyNet",
    "teamCode",
)

_NUMERIC_DTYPES: dict[str, str] = {
    "shotID": "int64",
    "game_id": "int64",
    "season": "int64",
    "isPlayoffGame": "int64",
    "homeTeamWon": "int64",
    "period": "int64",
    "time": "int64",
    "isHomeTeam": "int64",
    "goal": "int64",
    "homeTeamGoals": "int64",
    "awayTeamGoals": "int64",
    "xGoal": "float64",
    "homeSkatersOnIce": "int64",
    "awaySkatersOnIce": "int64",
    "homeEmptyNet": "int64",
    "awayEmptyNet": "int64",
    "shotOnEmptyNet": "int64",
}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _download(url: str, dest: Path, *, timeout: int = 60) -> None:
    """Stream `url` to `dest`, writing through a `.part` temp file so a
    killed download never leaves a corrupt file at the final path.
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".part")
    try:
        with requests.get(url, stream=True, timeout=timeout) as resp:
            if resp.status_code != 200:
                raise RuntimeError(
                    f"MoneyPuck download failed: GET {url} returned "
                    f"HTTP {resp.status_code}. Check https://moneypuck.com/data.htm "
                    "to confirm the file still exists at this URL -- MoneyPuck "
                    "occasionally reorganizes its download host."
                )
            with tmp.open("wb") as f:
                for chunk in resp.iter_content(chunk_size=1 << 20):
                    f.write(chunk)
    except requests.RequestException as exc:
        raise RuntimeError(
            f"MoneyPuck download failed: could not reach {url} ({exc}). "
            "Check your network connection, then https://moneypuck.com/data.htm "
            "for an announced outage."
        ) from exc
    tmp.replace(dest)


def _manifest_path(raw_dir: Path) -> Path:
    return raw_dir / "manifest.json"


def _load_manifest(raw_dir: Path) -> dict[str, dict]:
    path = _manifest_path(raw_dir)
    if not path.exists():
        return {}
    return json.loads(path.read_text())


def _write_manifest(raw_dir: Path, manifest: dict[str, dict]) -> None:
    _manifest_path(raw_dir).write_text(json.dumps(manifest, indent=2, sort_keys=True))


def download_season(season: int, raw_dir: Path, *, force: bool = False) -> Path:
    """Download one season's shot zip, skipping if already cached on disk.

    Args:
        season: MoneyPuck season label (e.g. 2013 for the 2013-14 season).
        raw_dir: Directory to save the zip into (created if missing).
        force: Re-download even if the zip already exists.

    Returns:
        Path to the downloaded (or already-cached) zip file.
    """
    zip_path = raw_dir / f"shots_{season}.zip"
    if zip_path.exists() and not force:
        logger.info("season %s already downloaded at %s, skipping", season, zip_path)
        return zip_path
    url = SHOTS_URL_TEMPLATE.format(season=season)
    logger.info("downloading season %s from %s", season, url)
    _download(url, zip_path)
    logger.info("downloaded season %s (%d bytes)", season, zip_path.stat().st_size)
    return zip_path


def extract_season(season: int, raw_dir: Path, interim_dir: Path) -> Path:
    """Unzip a downloaded season into `interim_dir`, returning the CSV path.

    Raises:
        FileNotFoundError: if the season hasn't been downloaded yet.
        RuntimeError: if the zip's internal file name doesn't match the
            expected `shots_<season>.csv` -- signals MoneyPuck changed their
            zip layout and this function's assumption needs updating.
    """
    zip_path = raw_dir / f"shots_{season}.zip"
    if not zip_path.exists():
        raise FileNotFoundError(
            f"No downloaded zip for season {season} at {zip_path}. "
            "Call download_season() first (or run `make data`)."
        )
    interim_dir.mkdir(parents=True, exist_ok=True)
    csv_name = f"shots_{season}.csv"
    csv_path = interim_dir / csv_name
    with zipfile.ZipFile(zip_path) as zf:
        names = zf.namelist()
        if csv_name not in names:
            raise RuntimeError(
                f"Expected {csv_name} inside {zip_path} but found {names}. "
                "MoneyPuck may have changed their zip's internal file naming -- "
                "update extract_season() to match the new layout."
            )
        with zf.open(csv_name) as src, csv_path.open("wb") as dst:
            dst.write(src.read())
    return csv_path


def load_raw_shots(csv_path: Path) -> pd.DataFrame:
    """Load one season's extracted shot CSV with the numeric dtypes this
    project depends on, failing loudly if a depended-on column is missing.

    Raises:
        FileNotFoundError: if `csv_path` does not exist.
        RuntimeError: if a required column is missing from the file.
    """
    if not csv_path.exists():
        raise FileNotFoundError(
            f"Expected extracted CSV not found: {csv_path}. Call "
            "extract_season() first (or run `make data`)."
        )
    df = pd.read_csv(csv_path, low_memory=False)
    missing = set(REQUIRED_COLUMNS) - set(df.columns)
    if missing:
        raise RuntimeError(
            f"{csv_path} is missing columns this project depends on: "
            f"{sorted(missing)}. MoneyPuck may have renamed or dropped a "
            "column -- check docs/data_dictionaries/MoneyPuck_Shot_Data_Dictionary.csv "
            "against the live file and update REQUIRED_COLUMNS / RAW_SHOTS_SCHEMA."
        )
    for col, dtype in _NUMERIC_DTYPES.items():
        df[col] = df[col].astype(dtype)
    return df


# The NHL physically allows at most 6 skaters (excluding the goalie) on one
# team's bench at once: 5 skaters, plus a 6th during a delayed penalty when
# the non-offending team pulls its goalie for an extra attacker. Any row
# claiming more is a MoneyPuck data-entry error, not a real game state.
# Confirmed present (at a rate of 1-3 rows per ~110,000, i.e. <0.003%) in
# every era sampled during Phase 1 (2007, 2013, 2025) -- see
# docs/decisions/0004-impossible-skater-counts.md.
MAX_PHYSICAL_SKATERS_ON_ICE = 6


def _drop_impossible_skater_count_rows(df: pd.DataFrame, season: int) -> pd.DataFrame:
    """Drop shot rows claiming more than 6 skaters on ice for either team,
    logging exactly which `shotID`s were dropped and why.
    """
    impossible = (df["homeSkatersOnIce"] > MAX_PHYSICAL_SKATERS_ON_ICE) | (
        df["awaySkatersOnIce"] > MAX_PHYSICAL_SKATERS_ON_ICE
    )
    n_dropped = int(impossible.sum())
    if n_dropped:
        logger.warning(
            "season %s: dropping %d/%d shot rows with a physically impossible "
            "skater count (>%d on one team) -- shotIDs %s. This is a known, "
            "persistent MoneyPuck data-entry glitch, not an ingest bug; see "
            "docs/decisions/0004-impossible-skater-counts.md.",
            season,
            n_dropped,
            len(df),
            MAX_PHYSICAL_SKATERS_ON_ICE,
            sorted(df.loc[impossible, "shotID"].tolist()),
        )
    return df.loc[~impossible].reset_index(drop=True)


# Columns compared to decide whether a game's shot sequence has been
# duplicated wholesale within the file (see
# docs/decisions/0005-duplicated-game-blocks.md). Deliberately excludes
# `shotID` itself (which differs between the original and duplicate block by
# construction) and player/TOI diagnostic columns this project doesn't
# depend on; `homeTeamGoals`/`awayTeamGoals` are included because a coincidental
# match on event sequencing alone, without the running score also matching,
# would be too weak a signal to safely drop real data on.
_DUPLICATE_BLOCK_COMPARISON_COLUMNS = (
    "period",
    "time",
    "isHomeTeam",
    "event",
    "goal",
    "homeTeamGoals",
    "awayTeamGoals",
)


def _drop_duplicated_game_blocks(df: pd.DataFrame, season: int) -> pd.DataFrame:
    """Detect and drop games whose entire shot sequence is repeated twice
    within the file under the same `game_id` (with a disjoint `shotID`
    range for the repeat) -- a real, confirmed MoneyPuck ETL artifact, not a
    hypothetical. Found in the 2007 season file: its first 16 games
    (game_id 20001-20016) each have every shot row appearing twice.

    A game is flagged only if its row count is even and splitting it in
    half (in `shotID` order) produces two element-wise identical halves on
    `_DUPLICATE_BLOCK_COMPARISON_COLUMNS`. This deliberately will not flag
    genuinely long games (e.g. multi-overtime playoff games), which have no
    reason to split into two identical halves.
    """
    kept_frames = []
    n_games_deduplicated = 0
    for game_id, game in df.groupby("game_id", sort=False):
        n = len(game)
        if n < 2 or n % 2 != 0:
            kept_frames.append(game)
            continue
        game_sorted = game.sort_values("shotID")
        half = n // 2
        first_half = game_sorted.iloc[:half]
        second_half = game_sorted.iloc[half:]
        is_duplicated = (
            first_half[list(_DUPLICATE_BLOCK_COMPARISON_COLUMNS)]
            .reset_index(drop=True)
            .equals(second_half[list(_DUPLICATE_BLOCK_COMPARISON_COLUMNS)].reset_index(drop=True))
        )
        if is_duplicated:
            n_games_deduplicated += 1
            logger.warning(
                "season %s: game %s has its entire %d-shot sequence duplicated "
                "within the file (shotIDs %s and %s) -- dropping the second copy. "
                "See docs/decisions/0005-duplicated-game-blocks.md.",
                season,
                game_id,
                half,
                sorted(first_half["shotID"].tolist()),
                sorted(second_half["shotID"].tolist()),
            )
            kept_frames.append(first_half)
        else:
            kept_frames.append(game)

    if n_games_deduplicated == 0:
        return df
    return pd.concat(kept_frames, ignore_index=True)


def ingest_season(
    season: int, raw_dir: Path, interim_dir: Path, *, force: bool = False
) -> pd.DataFrame:
    """Download, extract, load, and schema-validate one season end to end,
    updating the drift-detection manifest as a side effect.

    Returns:
        The validated shot-level DataFrame for `season`.
    """
    zip_path = download_season(season, raw_dir, force=force)
    csv_path = extract_season(season, raw_dir, interim_dir)
    df = load_raw_shots(csv_path)
    df = _drop_impossible_skater_count_rows(df, season)
    df = _drop_duplicated_game_blocks(df, season)
    validated = RAW_SHOTS_SCHEMA.validate(df, lazy=True)

    manifest = _load_manifest(raw_dir)
    key = str(season)
    new_hash = _sha256(zip_path)
    if key in manifest and manifest[key]["sha256"] != new_hash:
        logger.warning(
            "season %s zip content changed since last ingest (sha256 %s -> %s); "
            "MoneyPuck may have corrected historical data -- re-run downstream "
            "stages for this season.",
            season,
            manifest[key]["sha256"],
            new_hash,
        )
    manifest[key] = {
        "season": season,
        "url": SHOTS_URL_TEMPLATE.format(season=season),
        "sha256": new_hash,
        "row_count": len(validated),
        "n_columns": int(validated.shape[1]),
        "downloaded_at": pd.Timestamp.now(tz="UTC").isoformat(),
    }
    _write_manifest(raw_dir, manifest)

    logger.info(
        "ingested season %s: %d rows, %d columns", season, len(validated), validated.shape[1]
    )
    return validated


def download_data_dictionary(dest: Path) -> None:
    """Fetch MoneyPuck's published data dictionary and save it verbatim."""
    logger.info("refreshing MoneyPuck data dictionary at %s", dest)
    _download(DATA_DICTIONARY_URL, dest)


def main() -> None:
    from loserpoint.utils.config import load_config
    from loserpoint.validate.checks import reconcile_season, write_validation_report

    config = load_config()
    raw_dir = Path("data/raw/moneypuck")
    interim_dir = Path("data/interim/moneypuck")
    download_data_dictionary(Path("docs/data_dictionaries/MoneyPuck_Shot_Data_Dictionary.csv"))

    reconciliations = []
    for season in range(config.seasons.modern_start, config.seasons.modern_end + 1):
        df = ingest_season(season, raw_dir, interim_dir)
        reconciliations.append(
            reconcile_season(
                df, season, sample_games=config.validation.reconciliation_sample_games_per_season
            )
        )

    write_validation_report(
        reconciliations,
        Path("data/processed/validation_report.md"),
        hard_failure_mismatch_threshold=config.validation.hard_failure_mismatch_threshold,
    )


if __name__ == "__main__":
    main()
