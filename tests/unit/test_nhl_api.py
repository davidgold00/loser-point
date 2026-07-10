"""Unit tests for ingest/nhl_api.py -- all network access is mocked."""

from __future__ import annotations

import json

import pytest
from loserpoint.ingest.nhl_api import (
    NHLApiClient,
    NHLApiError,
    fetch_season_game_results,
)


class FakeNhlpy:
    """Stands in for nhlpy.NHLClient with two seasons of canned weeks."""

    def __init__(self) -> None:
        self.calls: list[str] = []
        outer = self

        class _Schedule:
            def weekly_schedule(self, date):
                outer.calls.append(f"week:{date}")
                return outer.weeks[date]

        class _Standings:
            def season_standing_manifest(self):
                outer.calls.append("manifest")
                return [
                    {"id": 20132014, "standingsStart": "2013-10-01", "standingsEnd": "2014-04-13"}
                ]

            def league_standings(self, date=None, season=None):
                outer.calls.append(f"standings:{date}")
                return {"standings": []}

        self.schedule = _Schedule()
        self.standings = _Standings()
        self.weeks = {
            "2013-10-01": {
                "nextStartDate": "2013-10-08",
                "playoffEndDate": "2014-06-13",
                "gameWeek": [
                    {
                        "date": "2013-10-01",
                        "games": [
                            _game(2013020001, 20132014, 2, "TOR", "MTL", 4, 3, "OT"),
                            _game(2013010099, 20132014, 1, "TOR", "BUF", 2, 1, "REG"),  # preseason
                        ],
                    }
                ],
            },
            "2013-10-08": {
                "nextStartDate": None,
                "playoffEndDate": "2014-06-13",
                "gameWeek": [
                    {
                        "date": "2013-10-08",
                        "games": [
                            _game(2013020001, 20132014, 2, "TOR", "MTL", 4, 3, "OT"),  # dupe
                            _game(2013020002, 20132014, 2, "BOS", "TBL", 1, 2, "SO"),
                            _game(2013030001, 20132014, 3, "BOS", "MTL", 3, 0, "REG"),  # playoff
                            _game(
                                2012020099, 20122013, 2, "NYR", "NJD", 5, 1, "REG"
                            ),  # other season
                        ],
                    }
                ],
            },
        }


def _game(gid, season_id, game_type, home, away, hs, as_, lpt):
    return {
        "id": gid,
        "season": season_id,
        "gameType": game_type,
        "homeTeam": {"abbrev": home, "score": hs},
        "awayTeam": {"abbrev": away, "score": as_},
        "gameOutcome": {"lastPeriodType": lpt},
    }


def test_fetch_season_game_results_shapes_and_filters(tmp_path) -> None:
    client = NHLApiClient(tmp_path, client=FakeNhlpy(), min_request_interval_seconds=0)
    df = fetch_season_game_results(client, 2013)

    # Preseason, other-season, and duplicate games are all excluded.
    assert sorted(df["game_id"]) == [20001, 20002, 30001]
    row = df.set_index("game_id").loc[20002]
    assert row["home_team"] == "BOS"
    assert row["last_period_type"] == "SO"
    assert row["game_type"] == 2
    assert df.set_index("game_id").loc[30001, "game_type"] == 3
    assert df.set_index("game_id").loc[20001, "date"] == "2013-10-01"


def test_responses_are_cached_to_disk_and_not_refetched(tmp_path) -> None:
    fake = FakeNhlpy()
    client = NHLApiClient(tmp_path, client=fake, min_request_interval_seconds=0)
    fetch_season_game_results(client, 2013)
    n_calls_first = len(fake.calls)
    assert (tmp_path / "weekly_schedule_2013-10-01.json").exists()

    # Second run must be served entirely from cache.
    fetch_season_game_results(client, 2013)
    assert len(fake.calls) == n_calls_first


def test_unknown_season_raises_with_guidance(tmp_path) -> None:
    client = NHLApiClient(tmp_path, client=FakeNhlpy(), min_request_interval_seconds=0)
    with pytest.raises(NHLApiError, match="not found in the NHL season manifest"):
        fetch_season_game_results(client, 1997)


def test_retry_then_success(tmp_path) -> None:
    fake = FakeNhlpy()
    original = fake.schedule.weekly_schedule
    failures = {"count": 0}

    def flaky(date):
        if failures["count"] < 2:
            failures["count"] += 1
            raise ConnectionError("transient")
        return original(date)

    fake.schedule.weekly_schedule = flaky
    client = NHLApiClient(
        tmp_path, client=fake, min_request_interval_seconds=0, backoff_base_seconds=0
    )
    df = fetch_season_game_results(client, 2013)
    assert len(df) == 3


def test_exhausted_retries_raise_nhl_api_error(tmp_path) -> None:
    fake = FakeNhlpy()
    fake.schedule.weekly_schedule = lambda date: (_ for _ in ()).throw(ConnectionError("down"))
    client = NHLApiClient(
        tmp_path,
        client=fake,
        min_request_interval_seconds=0,
        max_retries=2,
        backoff_base_seconds=0,
    )
    with pytest.raises(NHLApiError, match="failed after 2 attempts"):
        fetch_season_game_results(client, 2013)


def test_week_iteration_stops_despite_receding_playoff_end_date(tmp_path) -> None:
    # Regression test for bugs_found.md #9: once the nextStartDate chain
    # rolls into the following season, responses report THAT season's
    # playoffEndDate, so a stop condition that re-reads it every week never
    # fires. The fetch must capture the first week's playoffEndDate and
    # stop once past it, not iterate to the runaway guard.
    fake = FakeNhlpy()
    # Rebuild the week chain: our season's playoffs end 2013-10-05; every
    # later week chains onward forever with a receding playoffEndDate.
    fake.weeks = {
        "2013-10-01": {
            "nextStartDate": "2013-10-08",
            "playoffEndDate": "2013-10-05",
            "gameWeek": [
                {
                    "date": "2013-10-01",
                    "games": [_game(2013020001, 20132014, 2, "TOR", "MTL", 4, 3, "REG")],
                }
            ],
        },
    }
    for i in range(8, 200, 7):  # an endless chain of next-season weeks
        day = f"2013-{10 + i // 31:02d}-{1 + i % 28:02d}"
        fake.weeks[f"2013-10-{i:02d}" if i < 31 else day] = {}
    # Simpler: make every unknown date return a generic next-season week.
    generic = {
        "nextStartDate": "2099-01-01",
        "playoffEndDate": "2099-06-01",  # always far in the future
        "gameWeek": [],
    }
    fake.weeks = {
        "2013-10-01": fake.weeks["2013-10-01"],
        "2013-10-08": dict(generic, nextStartDate="2013-10-15"),
        "2013-10-15": dict(generic, nextStartDate="2013-10-22"),
        "2013-10-22": dict(generic, nextStartDate="2013-10-29"),
    }
    client = NHLApiClient(tmp_path, client=fake, min_request_interval_seconds=0)
    df = fetch_season_game_results(client, 2013)
    assert sorted(df["game_id"]) == [20001]
    # It must have stopped at the first week past 2013-10-05, not chained on.
    week_calls = [c for c in fake.calls if c.startswith("week:")]
    assert week_calls == ["week:2013-10-01", "week:2013-10-08"]


def test_league_standings_cached(tmp_path) -> None:
    fake = FakeNhlpy()
    client = NHLApiClient(tmp_path, client=fake, min_request_interval_seconds=0)
    client.league_standings("2014-01-15")
    client.league_standings("2014-01-15")
    assert fake.calls.count("standings:2014-01-15") == 1
    cached = json.loads((tmp_path / "league_standings_2014-01-15.json").read_text())
    assert cached == {"standings": []}


def test_parse_standings_flattens_real_shape() -> None:
    from loserpoint.ingest.nhl_api import parse_standings

    response = {
        "standings": [
            {
                "seasonId": 20132014,
                "teamAbbrev": {"default": "BOS"},
                "conferenceName": "Eastern",
                "divisionName": "Atlantic",
                "gamesPlayed": 82,
                "points": 117,
                "wins": 54,
                "losses": 19,
                "otLosses": 9,
                "regulationPlusOtWins": 51,
                "goalDifferential": 84,
                "leagueSequence": 1,
                "conferenceSequence": 1,
                "divisionSequence": 1,
                "wildcardSequence": 0,
                "clinchIndicator": "p",
            },
            {
                # 2020-21 shape: no conference, sponsor-named division
                # (verified against the real API -- decision 0015).
                "seasonId": 20202021,
                "teamAbbrev": {"default": "COL"},
                "divisionName": "Honda West",
                "gamesPlayed": 56,
                "points": 82,
                "wins": 39,
                "losses": 13,
                "otLosses": 4,
                "regulationPlusOtWins": 39,
                "goalDifferential": 64,
            },
        ]
    }
    frame = parse_standings(response, date="2014-04-13")
    assert len(frame) == 2
    bos = frame.iloc[0]
    assert bos["season"] == 2013
    assert bos["team"] == "BOS"
    assert bos["conference"] == "Eastern"
    assert bos["points"] == 117
    assert bos["row_wins"] == 51
    import pandas as pd

    col = frame.iloc[1]
    assert col["season"] == 2020
    assert pd.isna(col["conference"])  # pandas coerces the missing key's None to NaN
    assert col["division"] == "Honda West"


def test_season_second_half_start_dates_uses_schedule_median() -> None:
    import pandas as pd
    from loserpoint.ingest.nhl_api import season_second_half_start_dates

    results = pd.DataFrame(
        {
            "season": [2012] * 4 + [2013] * 4,
            # Lockout-style late calendar for 2012; normal for 2013. A
            # playoff game (type 3) must not shift the median.
            "date": [
                "2013-01-19",
                "2013-02-01",
                "2013-03-01",
                "2013-06-01",
                "2013-10-01",
                "2013-11-01",
                "2014-01-01",
                "2014-06-01",
            ],
            "game_type": [2, 2, 2, 3, 2, 2, 2, 3],
        }
    )
    cutoffs = season_second_half_start_dates(results)
    assert cutoffs[2012] == pd.Timestamp("2013-02-01")
    assert cutoffs[2013] == pd.Timestamp("2013-11-01")


def test_pregame_standings_dates_second_half_minus_one_day() -> None:
    import pandas as pd
    from loserpoint.ingest.nhl_api import _pregame_standings_dates

    results = pd.DataFrame(
        {
            "season": [2013] * 3,
            "date": ["2013-10-01", "2014-01-15", "2014-01-15"],
            "game_type": [2, 2, 2],
        }
    )
    dates = _pregame_standings_dates(results)
    # Median date is 2014-01-15; only that (second-half) date survives,
    # shifted back one day and deduplicated.
    assert dates == ["2014-01-14"]


def test_fetch_standings_history_concatenates_dates(tmp_path) -> None:
    from loserpoint.ingest.nhl_api import fetch_standings_history

    fake = FakeNhlpy()
    fake.standings_payload = {
        "standings": [
            {
                "seasonId": 20132014,
                "teamAbbrev": {"default": "TOR"},
                "conferenceName": "Eastern",
                "divisionName": "Atlantic",
                "gamesPlayed": 41,
                "points": 50,
                "wins": 24,
                "losses": 15,
                "otLosses": 2,
                "regulationPlusOtWins": 20,
                "goalDifferential": 5,
            }
        ]
    }
    fake.standings.league_standings = lambda date=None, season=None: fake.standings_payload
    client = NHLApiClient(tmp_path, min_request_interval_seconds=0, client=fake)
    frame = fetch_standings_history(client, ["2014-01-14", "2014-01-15"])
    assert len(frame) == 2
    assert sorted(frame["date"]) == ["2014-01-14", "2014-01-15"]
    assert (frame["team"] == "TOR").all()
