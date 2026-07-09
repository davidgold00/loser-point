"""NHL API client: schedules, game results, and standings.

A thin, polite layer over the community `nhl-api-py` package (imported as
`nhlpy` -- see decision 0002): every response is cached to disk as JSON so
no endpoint is ever hit twice, real requests are rate-limited (default one
per second) and retried with exponential backoff.

Game results are fetched by iterating `weekly_schedule` across each season
(the API's `nextStartDate` chains the weeks), NOT per team: MoneyPuck team
codes ("T.B", "L.A") don't match NHL abbreviations ("TBL", "LAK"), while
NHL game ids join to MoneyPuck arithmetically -- the API id 2013020022 is
season 2013 + game type 02 + game 0022, i.e. MoneyPuck game_id
2013020022 % 1_000_000 == 20022.

The `last_period_type` field (REG/OT/SO) is the external ground truth for
the panel's reached-OT and shootout outcome variables, and the API's final
scores are the cross-source reconciliation target promised in Phase 1.
Note the score convention difference: for shootout games the API credits
the winner with one extra goal (the SO decider), while MoneyPuck's shot
data leaves the score tied (decision 0003).
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from pathlib import Path

import pandas as pd

from loserpoint.utils.logging import get_logger

logger = get_logger(__name__)

REGULAR_SEASON = 2
PLAYOFFS = 3
# A season (October through the June playoffs) spans ~38 weeks; 60 is a
# runaway-loop guard, not a schedule fact.
MAX_WEEKS_PER_SEASON = 60


class NHLApiError(RuntimeError):
    """The NHL API could not be reached after retries, or returned a shape
    this client does not understand."""


class NHLApiClient:
    """Caching, rate-limited, retrying wrapper around nhlpy.

    Args:
        cache_dir: directory for the JSON response cache.
        min_request_interval_seconds: minimum spacing between real HTTP
            requests (cached reads are free).
        max_retries: attempts per request before giving up.
        backoff_base_seconds: sleep is backoff_base ** attempt.
        client: an nhlpy NHLClient; injectable for tests. Constructed
            lazily so unit tests never need nhlpy importable/network-ready.
    """

    def __init__(
        self,
        cache_dir: Path | str,
        *,
        min_request_interval_seconds: float = 1.0,
        max_retries: int = 5,
        backoff_base_seconds: float = 2.0,
        client: object | None = None,
    ) -> None:
        self.cache_dir = Path(cache_dir)
        self.min_interval = min_request_interval_seconds
        self.max_retries = max_retries
        self.backoff_base = backoff_base_seconds
        self._client = client
        self._last_request_at = 0.0

    @property
    def client(self) -> object:
        if self._client is None:
            from nhlpy import NHLClient

            self._client = NHLClient()
        return self._client

    def _fetch_cached(self, key: str, fetch: Callable[[], dict | list]) -> dict | list:
        """Return the cached response for `key`, fetching (politely) once."""
        path = self.cache_dir / f"{key}.json"
        if path.exists():
            return json.loads(path.read_text())

        wait = self.min_interval - (time.monotonic() - self._last_request_at)
        if wait > 0:
            time.sleep(wait)

        last_error: Exception | None = None
        for attempt in range(self.max_retries):
            try:
                self._last_request_at = time.monotonic()
                response = fetch()
                break
            except Exception as exc:  # nhlpy surfaces raw httpx/JSON errors
                last_error = exc
                sleep_s = self.backoff_base**attempt
                logger.warning(
                    "NHL API request %s failed (attempt %d/%d): %s -- retrying in %.0fs",
                    key,
                    attempt + 1,
                    self.max_retries,
                    exc,
                    sleep_s,
                )
                time.sleep(sleep_s)
        else:
            raise NHLApiError(
                f"NHL API request {key!r} failed after {self.max_retries} attempts "
                f"(last error: {last_error}). Check your connection and whether "
                "https://api-web.nhle.com is reachable; the nhl-api-py package may "
                "also need updating if the NHL changed their API."
            ) from last_error

        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(response))
        return response

    def weekly_schedule(self, date: str) -> dict:
        """The league-wide schedule for the week starting at `date`
        (YYYY-MM-DD), with final scores and gameOutcome for played games."""
        return self._fetch_cached(
            f"weekly_schedule_{date}", lambda: self.client.schedule.weekly_schedule(date)
        )

    def season_manifest(self) -> list[dict]:
        """Per-season metadata (standingsStart/standingsEnd) for every NHL
        season -- used to know where each season's week iteration begins."""
        return self._fetch_cached(
            "season_standing_manifest",
            lambda: self.client.standings.season_standing_manifest(),
        )

    def league_standings(self, date: str) -> dict:
        """League standings as of `date` (YYYY-MM-DD) -- the input for
        playoff-race context (consumed in Phase 5)."""
        return self._fetch_cached(
            f"league_standings_{date}", lambda: self.client.standings.league_standings(date=date)
        )


def _season_start_date(client: NHLApiClient, season: int) -> str:
    season_id = season * 10000 + season + 1  # 2013 -> 20132014
    for entry in client.season_manifest():
        if entry.get("id") == season_id:
            return entry["standingsStart"]
    raise NHLApiError(
        f"season {season} (id {season_id}) not found in the NHL season manifest -- "
        "check that the season label is a real NHL season."
    )


def fetch_season_game_results(client: NHLApiClient, season: int) -> pd.DataFrame:
    """All regular-season and playoff game results for one season.

    Iterates weekly_schedule from the season's standings start, following
    the API's own nextStartDate chain until past the playoff end date.

    Returns:
        One row per game: season, game_id (MoneyPuck-compatible), date,
        home_team, away_team, home_score, away_score, last_period_type
        (REG/OT/SO), game_type (2=regular season, 3=playoffs).
    """
    rows: list[dict] = []
    seen: set[int] = set()
    date = _season_start_date(client, season)
    season_id = season * 10000 + season + 1
    # Captured from the FIRST week's response only. Later responses roll
    # into the next season and report *that* season's playoffEndDate, so
    # re-reading it every week makes the stop condition recede forever
    # (bugs_found.md #9).
    playoff_end: str | None = None

    for _ in range(MAX_WEEKS_PER_SEASON):
        week = client.weekly_schedule(date)
        if playoff_end is None:
            playoff_end = week.get("playoffEndDate")
        for day in week.get("gameWeek", []):
            for game in day.get("games", []):
                if game.get("season") != season_id:
                    continue
                if game.get("gameType") not in (REGULAR_SEASON, PLAYOFFS):
                    continue  # preseason / all-star
                full_id = game["id"]
                if full_id in seen:
                    continue  # week windows can overlap at the seams
                seen.add(full_id)
                outcome = game.get("gameOutcome") or {}
                rows.append(
                    {
                        "season": season,
                        "game_id": full_id % 1_000_000,
                        "date": day["date"],
                        "home_team": game["homeTeam"]["abbrev"],
                        "away_team": game["awayTeam"]["abbrev"],
                        "home_score": game["homeTeam"].get("score"),
                        "away_score": game["awayTeam"].get("score"),
                        "last_period_type": outcome.get("lastPeriodType"),
                        "game_type": game["gameType"],
                    }
                )
        next_date = week.get("nextStartDate")
        if not next_date or (playoff_end and date > playoff_end):
            break
        date = next_date
    else:
        raise NHLApiError(
            f"season {season}: week iteration exceeded {MAX_WEEKS_PER_SEASON} weeks "
            "without reaching the playoff end date -- the API's nextStartDate "
            "chain may have changed shape."
        )

    df = pd.DataFrame(rows)
    logger.info(
        "NHL API: season %s -> %d games (%d regular season, %d playoffs)",
        season,
        len(df),
        int((df["game_type"] == REGULAR_SEASON).sum()) if len(df) else 0,
        int((df["game_type"] == PLAYOFFS).sum()) if len(df) else 0,
    )
    return df


def main() -> None:
    from loserpoint.utils.config import load_config
    from loserpoint.utils.io import write_parquet

    config = load_config()
    api_cfg = config.scraping["nhl_api"]
    client = NHLApiClient(
        Path("data/raw/nhl_api"),
        min_request_interval_seconds=api_cfg["min_request_interval_seconds"],
        max_retries=api_cfg["max_retries"],
        backoff_base_seconds=api_cfg["backoff_base_seconds"],
    )
    frames = [
        fetch_season_game_results(client, season)
        for season in range(config.seasons.modern_start, config.seasons.modern_end + 1)
    ]
    results = pd.concat(frames, ignore_index=True)
    write_parquet(results, Path("data/interim/nhl_api/game_results.parquet"))


if __name__ == "__main__":
    main()
