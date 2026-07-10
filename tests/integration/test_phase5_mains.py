"""End-to-end tests for the Phase 5 CLI entry points.

Both mains read parquet inputs relative to the working directory and read
the NHL season manifest through the caching client, so a tmp cwd with
synthetic parquets and a pre-seeded manifest cache exercises the full
production code path with zero network access.
"""

from __future__ import annotations

import json

import loserpoint.analysis.counterfactual as counterfactual
import loserpoint.analysis.heterogeneity as heterogeneity
import numpy as np
import pandas as pd
import pytest

SEASON = 2014
TEAMS = [f"T{i}" for i in range(8)]


def _seed_manifest(root) -> None:
    cache = root / "data" / "raw" / "nhl_api"
    cache.mkdir(parents=True)
    manifest = [
        {
            "id": SEASON * 10000 + SEASON + 1,
            "standingsStart": "2014-10-01",
            "standingsEnd": "2015-04-11",
            "wildcardInUse": True,
            "conferencesInUse": True,
            "divisionsInUse": True,
        }
    ]
    (cache / "season_standing_manifest.json").write_text(json.dumps(manifest))


def _game_results(n_games: int, rng) -> pd.DataFrame:
    rows = []
    for g in range(n_games):
        date = f"2014-11-{(g % 28) + 1:02d}" if g < n_games // 2 else f"2015-03-{(g % 28) + 1:02d}"
        home, away = TEAMS[g % 8], TEAMS[(g + 1) % 8]
        home_score, away_score = (3, 2) if rng.random() < 0.5 else (2, 3)
        rows.append(
            {
                "season": SEASON,
                "game_id": g,
                "date": date,
                "home_team": home,
                "away_team": away,
                "home_score": home_score,
                "away_score": away_score,
                "last_period_type": ("REG", "OT", "SO")[int(rng.integers(0, 3))],
                "game_type": 2,
            }
        )
    return pd.DataFrame(rows)


def _alignment_columns(frame: pd.DataFrame) -> pd.DataFrame:
    div = {t: ("Atlantic" if int(t[1]) < 4 else "Metropolitan") for t in TEAMS}
    frame["conference"] = "East"
    frame["division"] = frame["team"].map(div)
    return frame


@pytest.mark.slow
def test_counterfactual_main_end_to_end(tmp_path, monkeypatch) -> None:
    rng = np.random.default_rng(11)
    _seed_manifest(tmp_path)
    (tmp_path / "data" / "interim" / "nhl_api").mkdir(parents=True)
    (tmp_path / "data" / "processed").mkdir(parents=True)

    games = _game_results(160, rng)
    games.to_parquet(tmp_path / "data/interim/nhl_api/game_results.parquet")
    # Official standings that match by construction: computed from the same
    # games with the actual system (the validation gate must pass).
    official = counterfactual.compute_standings(games, counterfactual.POINT_SYSTEMS[0])
    official = _alignment_columns(official.drop(columns=["system"]))
    official.to_parquet(tmp_path / "data/interim/nhl_api/season_end_standings.parquet")

    monkeypatch.chdir(tmp_path)
    counterfactual.main()

    standings = pd.read_parquet(tmp_path / "data/processed/counterfactual_standings.parquet")
    summary = pd.read_parquet(tmp_path / "data/processed/counterfactual_summary.parquet")
    assert set(standings["system"]) == {"actual", "three_two_one", "no_loser_point"}
    assert set(summary["system"]) == {"three_two_one", "no_loser_point"}
    assert (summary["mean_abs_points_delta"] > 0).all()


@pytest.mark.slow
def test_counterfactual_main_aborts_on_official_mismatch(tmp_path, monkeypatch) -> None:
    rng = np.random.default_rng(12)
    _seed_manifest(tmp_path)
    (tmp_path / "data" / "interim" / "nhl_api").mkdir(parents=True)
    (tmp_path / "data" / "processed").mkdir(parents=True)

    games = _game_results(40, rng)
    games.to_parquet(tmp_path / "data/interim/nhl_api/game_results.parquet")
    official = counterfactual.compute_standings(games, counterfactual.POINT_SYSTEMS[0])
    official = _alignment_columns(official.drop(columns=["system"]))
    official.loc[0, "points"] += 1  # corrupt one official figure
    official.to_parquet(tmp_path / "data/interim/nhl_api/season_end_standings.parquet")

    monkeypatch.chdir(tmp_path)
    with pytest.raises(RuntimeError, match="disagree with the official"):
        counterfactual.main()


@pytest.mark.slow
def test_heterogeneity_main_end_to_end(tmp_path, monkeypatch) -> None:
    rng = np.random.default_rng(13)
    _seed_manifest(tmp_path)
    (tmp_path / "data" / "interim" / "nhl_api").mkdir(parents=True)
    (tmp_path / "data" / "processed").mkdir(parents=True)

    n_games = 160
    games = _game_results(n_games, rng)
    games.to_parquet(tmp_path / "data/interim/nhl_api/game_results.parquet")

    official = counterfactual.compute_standings(games, counterfactual.POINT_SYSTEMS[0])
    official = _alignment_columns(official.drop(columns=["system"]))
    official.to_parquet(tmp_path / "data/interim/nhl_api/season_end_standings.parquet")

    panel_rows, context_rows = [], []
    for g in range(n_games):
        home, away = TEAMS[g % 8], TEAMS[(g + 1) % 8]
        state = ("tied", "down_1", "up_1")[int(rng.integers(0, 3))]
        context_rows.append(
            {
                "season": SEASON,
                "game_id": g,
                "home_elo_pre": 1500 + rng.normal(0, 30),
                "away_elo_pre": 1500 + rng.normal(0, 30),
                "elo_diff_home": 0.0,
                "home_rest_days": int(rng.integers(1, 4)),
                "away_rest_days": int(rng.integers(1, 4)),
            }
        )
        for is_home in (True, False):
            for minute in range(41, 59):
                panel_rows.append(
                    {
                        "season": SEASON,
                        "game_id": g,
                        "is_home": is_home,
                        "is_playoff": False,
                        "non_5v5_flag": False,
                        "minute": minute,
                        "score_state": state,
                        "attempts_main": int(rng.poisson(0.5)),
                        "team_code": home if is_home else away,
                        "opp_code": away if is_home else home,
                    }
                )
    pd.DataFrame(panel_rows).to_parquet(tmp_path / "data/processed/game_minutes.parquet")
    pd.DataFrame(context_rows).to_parquet(tmp_path / "data/processed/game_context.parquet")

    # Pre-game standings snapshots: every team hovers near the cutline on
    # some dates so both race values occur.
    second_half_dates = sorted(
        (pd.to_datetime(games.loc[games["date"] >= "2015-01-01", "date"]) - pd.Timedelta(days=1))
        .dt.strftime("%Y-%m-%d")
        .unique()
    )
    snapshot_rows = []
    for d_i, date in enumerate(second_half_dates):
        for t_i, team in enumerate(TEAMS):
            snapshot_rows.append(
                {
                    "date": date,
                    "season": SEASON,
                    "team": team,
                    "conference": "East",
                    "division": "Atlantic" if t_i < 4 else "Metropolitan",
                    "points": 50 + ((t_i + d_i) % 4) * 5,
                }
            )
    pd.DataFrame(snapshot_rows).to_parquet(
        tmp_path / "data/interim/nhl_api/standings_by_date.parquet"
    )

    monkeypatch.chdir(tmp_path)
    heterogeneity.main()

    table = pd.read_parquet(tmp_path / "data/processed/heterogeneity.parquet")
    assert set(table["hypothesis"]) == {"race", "intra_division", "even"}
    assert len(table) == 6
    assert np.isfinite(table[["coef", "se", "pct", "mde_pct"]]).all().all()
