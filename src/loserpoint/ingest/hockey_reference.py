"""Hockey-Reference scraper: pre-shot-tracking goal timestamps (1999-2006).

Powers the regime difference-in-differences (pre-2005 loser-point-only era
vs. post-2005 shootout era): MoneyPuck shot data starts in 2007-08, so the
only way to measure late-game behavior before the shootout is goals, not
shot attempts, scraped from Hockey-Reference boxscores. See
docs/decisions/0011-hockey-reference-scraper.md for the verified page
structures and the robots.txt paths this scraper does and does not touch.

Politeness is structural, not a suggestion: every raw HTML response is
cached to disk keyed by URL, so a killed run resumes for free without
re-fetching anything; real requests are spaced by
`min_request_interval_seconds` (config default 4.0s, above the site's own
`Crawl-delay: 3`); and the User-Agent identifies this project and its
purpose.
"""

from __future__ import annotations

import time
from pathlib import Path

import pandas as pd
import requests
from bs4 import BeautifulSoup

from loserpoint.panel.score_state import GoalEvent, minute_states
from loserpoint.utils.logging import get_logger

logger = get_logger(__name__)

BASE_URL = "https://www.hockey-reference.com"
PERIOD_SECONDS = 1200  # 20 minutes; only periods 1-3 are kept (OT dropped)
PERIOD_LABELS = {"1st Period": 1, "2nd Period": 2, "3rd Period": 3}


class HockeyReferenceError(RuntimeError):
    """The site could not be reached, or returned a page shape this
    scraper does not understand."""


class HockeyReferenceClient:
    """Caching, rate-limited HTTP client for Hockey-Reference pages.

    Args:
        cache_dir: directory for raw HTML, one file per URL path.
        user_agent: sent on every real request (config-driven; identifies
            this project, per Hockey-Reference's own request to do so).
        min_request_interval_seconds: minimum spacing between real
            requests; cached reads never sleep.
        session: injectable `requests.Session`-like object for tests.
    """

    def __init__(
        self,
        cache_dir: Path | str,
        *,
        user_agent: str,
        min_request_interval_seconds: float = 4.0,
        max_retries: int = 4,
        retry_backoff_seconds: float = 5.0,
        session: object | None = None,
    ) -> None:
        self.cache_dir = Path(cache_dir)
        self.user_agent = user_agent
        self.min_interval = min_request_interval_seconds
        self.max_retries = max_retries
        self.retry_backoff_seconds = retry_backoff_seconds
        self._session = session
        self._last_request_at = 0.0

    @property
    def session(self):
        if self._session is None:
            self._session = requests.Session()
        return self._session

    def get(self, path: str) -> str:
        """Fetch `path` (e.g. "/boxscores/199910010DAL.html"), serving from
        the on-disk cache when present.

        A multi-hour polite scrape WILL hit transient network errors
        (a single read timeout killed the first real run of this scraper
        -- see bugs_found.md #10); those are retried with backoff. A
        non-200 response is not retried -- it means the URL itself is
        wrong or blocked, which a retry cannot fix.

        Raises:
            HockeyReferenceError: on a non-200 response, or a network
                error that persists through all retries.
        """
        cache_path = self.cache_dir / path.lstrip("/")
        if cache_path.exists():
            return cache_path.read_text()

        url = BASE_URL + path
        last_error: requests.RequestException | None = None
        for attempt in range(self.max_retries):
            wait = self.min_interval - (time.monotonic() - self._last_request_at)
            if wait > 0:
                time.sleep(wait)
            try:
                self._last_request_at = time.monotonic()
                response = self.session.get(
                    url, headers={"User-Agent": self.user_agent}, timeout=30
                )
                break
            except requests.RequestException as exc:
                last_error = exc
                sleep_s = self.retry_backoff_seconds * (attempt + 1)
                logger.warning(
                    "GET %s failed (attempt %d/%d): %s -- retrying in %.0fs",
                    url,
                    attempt + 1,
                    self.max_retries,
                    exc,
                    sleep_s,
                )
                time.sleep(sleep_s)
        else:
            raise HockeyReferenceError(
                f"could not reach {url} after {self.max_retries} attempts "
                f"(last error: {last_error}). Check your network connection "
                "and whether hockey-reference.com is up."
            )

        if response.status_code != 200:
            raise HockeyReferenceError(
                f"GET {url} returned HTTP {response.status_code}. Hockey-Reference "
                "may have changed its URL structure or is rate-limiting this "
                "User-Agent -- check https://www.hockey-reference.com/robots.txt."
            )

        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(response.text)
        return response.text


def _is_cancelled_season(soup: BeautifulSoup) -> bool:
    """True if the page carries Hockey-Reference's own cancellation notice
    (verified verbatim text on the 2004-05 lockout season's schedule page:
    "This season was cancelled due to NHL lockout.").
    """
    return "cancelled due to nhl lockout" in soup.get_text().lower()


def _schedule_url(season: int) -> str:
    """Hockey-Reference's URL year is the season's second calendar year
    (season=1999, i.e. 1999-2000, -> NHL_2000_games.html)."""
    return f"/leagues/NHL_{season + 1}_games.html"


def parse_schedule(html: str, season: int) -> pd.DataFrame:
    """Parse a season schedule page into one row per regular-season game.

    Team abbreviations are read from each cell's `csk` attribute (e.g.
    `csk="DAL.199910010DAL"` -> "DAL"), not the visible full team name,
    since the boxscore's scoring table identifies scoring teams by
    abbreviation only.

    Returns:
        DataFrame: season, game_key (the boxscore URL stem, e.g.
        "199910010DAL"), date, home_team, away_team (abbreviations),
        home_goals, away_goals, reached_ot (True for "OT" or "SO" --
        "SO" cannot occur before the 2005-06 season), decided_by_shootout.
    """
    soup = BeautifulSoup(html, "html.parser")
    table = soup.find("table", id="games")
    if table is None:
        if _is_cancelled_season(soup):
            logger.warning(
                "season %s: Hockey-Reference confirms this season was cancelled "
                "(the 2004-05 NHL lockout) -- returning zero games, not an error. "
                "See docs/decisions/0012-lockout-season-gap.md.",
                season,
            )
            return pd.DataFrame(
                columns=[
                    "season",
                    "game_key",
                    "date",
                    "away_team",
                    "away_goals",
                    "home_team",
                    "home_goals",
                    "reached_ot",
                    "decided_by_shootout",
                ]
            )
        raise HockeyReferenceError(
            f"season {season}: no table id='games' found on the schedule page, and "
            "no lockout notice was found either -- Hockey-Reference may have changed "
            "their schedule page layout."
        )
    rows = []
    for tr in table.find("tbody").find_all("tr"):
        date_cell = tr.find(attrs={"data-stat": "date_game"})
        game_key = date_cell.get("csk")
        if not game_key:
            continue  # header/spacer rows have no csk slug
        away_cell = tr.find(attrs={"data-stat": "visitor_team_name"})
        home_cell = tr.find(attrs={"data-stat": "home_team_name"})
        overtimes = tr.find(attrs={"data-stat": "overtimes"}).get_text(strip=True)
        rows.append(
            {
                "season": season,
                "game_key": game_key,
                "date": date_cell.get_text(strip=True),
                "away_team": away_cell["csk"].split(".")[0],
                "away_goals": int(
                    tr.find(attrs={"data-stat": "visitor_goals"}).get_text(strip=True)
                ),
                "home_team": home_cell["csk"].split(".")[0],
                "home_goals": int(tr.find(attrs={"data-stat": "home_goals"}).get_text(strip=True)),
                "reached_ot": overtimes in ("OT", "SO"),
                "decided_by_shootout": overtimes == "SO",
            }
        )
    if not rows:
        raise HockeyReferenceError(
            f"season {season}: schedule table had no game rows -- check "
            f"{BASE_URL}{_schedule_url(season)} manually."
        )
    return pd.DataFrame(rows)


def parse_boxscore_goals(html: str, *, home_team: str) -> list[GoalEvent]:
    """Parse a boxscore's scoring summary table into regulation goal events.

    Overtime and shootout rows are dropped entirely: shootout goals do not
    change Hockey-Reference's own recorded score, and this project's panel
    is regulation-only regardless of era.

    Args:
        html: the boxscore page HTML.
        home_team: the home team's abbreviation for this game, from the
            matching schedule row (a boxscore page alone labels goals only
            by the scoring team's own abbreviation, not home/away).

    Returns:
        GoalEvent list (is_phantom always False; Hockey-Reference has no
        analog of MoneyPuck's phantom-goal gap).
    """
    soup = BeautifulSoup(html, "html.parser")
    table = soup.find("table", id="scoring")
    if table is None:
        raise HockeyReferenceError(
            "no table id='scoring' found on the boxscore page -- Hockey-Reference "
            "may have changed their boxscore layout, or this game had no scoring "
            "(0-0 final, vanishingly rare but possible)."
        )

    goals = []
    period = None
    for tr in table.find_all("tr"):
        header = tr.find("th", colspan="5")
        if header is not None:
            period = PERIOD_LABELS.get(header.get_text(strip=True))
            continue
        cells = tr.find_all("td")
        if len(cells) != 5 or period is None:
            continue  # stray/caption rows, or an OT/SO row (period is None)
        team_link = cells[1].find("a")
        if team_link is None:
            continue
        minutes, seconds = (int(x) for x in cells[0].get_text(strip=True).split(":"))
        absolute_time = (period - 1) * PERIOD_SECONDS + minutes * 60 + seconds
        goals.append(
            GoalEvent(
                time=absolute_time,
                is_home_team=team_link.get_text(strip=True) == home_team,
                is_phantom=False,
                period=period,
            )
        )
    return goals


def build_game_minutes(game: dict, goals: list[GoalEvent]) -> pd.DataFrame:
    """Build one historical game's 120 panel rows from its parsed goals.

    Reuses `panel.score_state.minute_states` unchanged: the minute-boundary
    convention (decision 0006) is source-agnostic -- only the outcome
    (goals, not shot attempts) differs for this pre-tracking era.
    """
    states = minute_states(goals)
    diff = states["home_score"] - states["away_score"]

    def goals_in_minute(is_home: bool) -> list[int]:
        from loserpoint.panel.score_state import minute_of_time

        counts = [0] * 60
        for g in goals:
            if g.is_home_team == is_home:
                counts[minute_of_time(g.time) - 1] += 1
        return counts

    frames = []
    for is_home in (True, False):
        frames.append(
            pd.DataFrame(
                {
                    "season": game["season"],
                    "game_key": game["game_key"],
                    "is_home": is_home,
                    "team_code": game["home_team"] if is_home else game["away_team"],
                    "opp_code": game["away_team"] if is_home else game["home_team"],
                    "minute": states["minute"],
                    "score_state": states["home_state" if is_home else "away_state"],
                    "score_diff": diff if is_home else -diff,
                    "goals_for": goals_in_minute(is_home),
                }
            )
        )
    return pd.concat(frames, ignore_index=True)


def build_historical_panel(schedule: pd.DataFrame, client: HockeyReferenceClient) -> pd.DataFrame:
    """Fetch every scheduled game's boxscore and build the full historical
    game x team x minute panel."""
    frames = []
    for game in schedule.itertuples(index=False):
        html = client.get(f"/boxscores/{game.game_key}.html")
        goals = parse_boxscore_goals(html, home_team=game.home_team)
        frames.append(build_game_minutes(game._asdict(), goals))
    panel = pd.concat(frames, ignore_index=True)
    logger.info(
        "historical panel: %d rows from %d games", len(panel), schedule["game_key"].nunique()
    )
    return panel


def main() -> None:
    from loserpoint.utils.config import load_config
    from loserpoint.utils.io import write_parquet

    config = load_config()
    hr_cfg = config.scraping["hockey_reference"]
    client = HockeyReferenceClient(
        Path("data/raw/hockey_reference"),
        user_agent=hr_cfg["user_agent"],
        min_request_interval_seconds=hr_cfg["min_request_interval_seconds"],
    )
    sample_cap = hr_cfg.get("sample_games_per_season")

    schedules = []
    for season in range(config.seasons.historical_start, config.seasons.historical_end + 1):
        html = client.get(_schedule_url(season))
        season_schedule = parse_schedule(html, season)
        if sample_cap is not None and len(season_schedule) > sample_cap:
            season_schedule = season_schedule.sample(n=sample_cap, random_state=season).sort_values(
                "date"
            )
        schedules.append(season_schedule)
        logger.info(
            "season %s: %d games scheduled for boxscore fetch", season, len(season_schedule)
        )

    schedule = pd.concat(schedules, ignore_index=True)
    write_parquet(schedule, Path("data/interim/hockey_reference/schedule.parquet"))

    panel = build_historical_panel(schedule, client)
    write_parquet(panel, Path("data/interim/hockey_reference/game_minutes.parquet"))


if __name__ == "__main__":
    main()
