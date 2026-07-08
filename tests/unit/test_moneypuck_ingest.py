"""Unit tests for ingest.moneypuck. Network access is always mocked --
these tests must pass with no internet connection.
"""

from __future__ import annotations

import zipfile

import pandas as pd
import pytest
import requests
from loserpoint.ingest import moneypuck

from tests.fixtures.moneypuck.builders import games_to_frame, make_clean_game


def _write_season_zip(raw_dir, season: int, df: pd.DataFrame) -> None:
    raw_dir.mkdir(parents=True, exist_ok=True)
    csv_bytes = df.to_csv(index=False).encode()
    zip_path = raw_dir / f"shots_{season}.zip"
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.writestr(f"shots_{season}.csv", csv_bytes)


def test_download_season_skips_if_already_cached(tmp_path, monkeypatch) -> None:
    raw_dir = tmp_path / "raw"
    raw_dir.mkdir()
    (raw_dir / "shots_2013.zip").write_bytes(b"fake cached zip")

    def _boom(*args, **kwargs):
        raise AssertionError("should not attempt a network call when cached")

    monkeypatch.setattr(requests, "get", _boom)
    result = moneypuck.download_season(2013, raw_dir)
    assert result == raw_dir / "shots_2013.zip"
    assert result.read_bytes() == b"fake cached zip"


def test_download_season_writes_streamed_content_on_success(tmp_path, monkeypatch) -> None:
    class _FakeResponse:
        status_code = 200

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def iter_content(self, chunk_size):
            yield b"fake zip bytes part 1 "
            yield b"fake zip bytes part 2"

    monkeypatch.setattr(requests, "get", lambda *a, **k: _FakeResponse())
    raw_dir = tmp_path / "raw"
    result = moneypuck.download_season(2013, raw_dir)
    assert result == raw_dir / "shots_2013.zip"
    assert result.read_bytes() == b"fake zip bytes part 1 fake zip bytes part 2"
    assert not (raw_dir / "shots_2013.zip.part").exists()


def test_download_raises_with_guidance_on_non_200(tmp_path, monkeypatch) -> None:
    class _FakeResponse:
        status_code = 404

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    monkeypatch.setattr(requests, "get", lambda *a, **k: _FakeResponse())
    with pytest.raises(RuntimeError, match="HTTP 404"):
        moneypuck.download_season(2099, tmp_path / "raw", force=True)


def test_download_raises_with_guidance_on_connection_error(tmp_path, monkeypatch) -> None:
    def _raise(*args, **kwargs):
        raise requests.ConnectionError("no route to host")

    monkeypatch.setattr(requests, "get", _raise)
    with pytest.raises(RuntimeError, match="could not reach"):
        moneypuck.download_season(2099, tmp_path / "raw", force=True)


def test_extract_season_raises_if_not_downloaded(tmp_path) -> None:
    with pytest.raises(FileNotFoundError, match="No downloaded zip"):
        moneypuck.extract_season(2013, tmp_path / "raw", tmp_path / "interim")


def test_extract_season_raises_on_unexpected_internal_filename(tmp_path) -> None:
    raw_dir = tmp_path / "raw"
    raw_dir.mkdir()
    with zipfile.ZipFile(raw_dir / "shots_2013.zip", "w") as zf:
        zf.writestr("wrong_name.csv", b"a,b\n1,2\n")
    with pytest.raises(RuntimeError, match="MoneyPuck may have changed their zip"):
        moneypuck.extract_season(2013, raw_dir, tmp_path / "interim")


def test_extract_then_load_round_trips_a_clean_game(tmp_path) -> None:
    raw_dir, interim_dir = tmp_path / "raw", tmp_path / "interim"
    df = games_to_frame(make_clean_game(game_id=20001, season=2013))
    _write_season_zip(raw_dir, 2013, df)

    csv_path = moneypuck.extract_season(2013, raw_dir, interim_dir)
    loaded = moneypuck.load_raw_shots(csv_path)

    assert len(loaded) == len(df)
    assert loaded["xGoal"].dtype == "float64"
    assert loaded["game_id"].dtype == "int64"


def test_load_raw_shots_raises_on_missing_required_column(tmp_path) -> None:
    df = games_to_frame(make_clean_game(game_id=20001, season=2013)).drop(columns=["xGoal"])
    csv_path = tmp_path / "shots_2013.csv"
    df.to_csv(csv_path, index=False)
    with pytest.raises(RuntimeError, match="missing columns this project depends on"):
        moneypuck.load_raw_shots(csv_path)


def test_load_raw_shots_raises_if_file_missing(tmp_path) -> None:
    with pytest.raises(FileNotFoundError, match="Expected extracted CSV not found"):
        moneypuck.load_raw_shots(tmp_path / "does_not_exist.csv")


def test_ingest_season_validates_and_writes_manifest(tmp_path) -> None:
    raw_dir, interim_dir = tmp_path / "raw", tmp_path / "interim"
    df = games_to_frame(make_clean_game(game_id=20001, season=2013))
    _write_season_zip(raw_dir, 2013, df)

    validated = moneypuck.ingest_season(2013, raw_dir, interim_dir)
    assert len(validated) == len(df)

    manifest = moneypuck._load_manifest(raw_dir)
    assert manifest["2013"]["row_count"] == len(df)
    assert "sha256" in manifest["2013"]


def test_drops_impossible_skater_count_rows_with_warning(tmp_path, caplog) -> None:
    # See docs/decisions/0004-impossible-skater-counts.md: MoneyPuck's real
    # data occasionally (rarely) claims 7-8 skaters on ice for one team,
    # which is not a physically possible NHL game state.
    raw_dir, interim_dir = tmp_path / "raw", tmp_path / "interim"
    df = games_to_frame(make_clean_game(game_id=20001, season=2013))
    df.loc[0, "homeSkatersOnIce"] = 8
    _write_season_zip(raw_dir, 2013, df)

    with caplog.at_level("WARNING"):
        validated = moneypuck.ingest_season(2013, raw_dir, interim_dir)

    assert len(validated) == len(df) - 1
    assert 8 not in validated["homeSkatersOnIce"].tolist()
    assert any("physically impossible skater count" in r.message for r in caplog.records)


def test_drops_duplicated_game_block_with_warning(tmp_path, caplog) -> None:
    # See docs/decisions/0005-duplicated-game-blocks.md: MoneyPuck's 2007
    # file has 16 games whose entire shot sequence is duplicated wholesale
    # under the same game_id with a different shotID range for the copy.
    raw_dir, interim_dir = tmp_path / "raw", tmp_path / "interim"
    duplicated_game = make_clean_game(game_id=20004, season=2007)
    duplicated_game_repeat = make_clean_game(game_id=20004, season=2007)
    normal_game = make_clean_game(game_id=20005, season=2007)
    df = games_to_frame(duplicated_game, duplicated_game_repeat, normal_game)
    _write_season_zip(raw_dir, 2007, df)

    with caplog.at_level("WARNING"):
        validated = moneypuck.ingest_season(2007, raw_dir, interim_dir)

    assert len(validated[validated["game_id"] == 20004]) == len(duplicated_game)
    assert len(validated[validated["game_id"] == 20005]) == len(normal_game)
    assert any(
        "has its entire" in r.message and "shot sequence duplicated" in r.message
        for r in caplog.records
    )


def test_even_row_count_game_with_distinct_halves_is_not_flagged(tmp_path) -> None:
    # An even shot count alone must not trigger deduplication -- only two
    # element-wise identical halves should. A normal 4-row game (distinct
    # content in each half) must survive intact, so a genuinely long
    # multi-overtime playoff game (also even-length by chance) isn't
    # mistaken for a duplicated block.
    raw_dir, interim_dir = tmp_path / "raw", tmp_path / "interim"
    game = make_clean_game(game_id=30001, season=2013)
    df = games_to_frame(game)
    _write_season_zip(raw_dir, 2013, df)

    validated = moneypuck.ingest_season(2013, raw_dir, interim_dir)
    assert len(validated) == len(game)


def test_ingest_season_warns_on_content_drift(tmp_path, caplog) -> None:
    raw_dir, interim_dir = tmp_path / "raw", tmp_path / "interim"
    df = games_to_frame(make_clean_game(game_id=20001, season=2013))
    _write_season_zip(raw_dir, 2013, df)
    moneypuck.ingest_season(2013, raw_dir, interim_dir)

    # Simulate MoneyPuck silently revising the season's data. The zip already
    # exists on disk with new content, so re-ingesting (without force=True,
    # i.e. no network call) must still pick up the drift via the sha256
    # comparison against the manifest written by the first ingest.
    df2 = games_to_frame(make_clean_game(game_id=20002, season=2013))
    _write_season_zip(raw_dir, 2013, df2)
    with caplog.at_level("WARNING"):
        moneypuck.ingest_season(2013, raw_dir, interim_dir)
    assert any("content changed since last ingest" in r.message for r in caplog.records)
