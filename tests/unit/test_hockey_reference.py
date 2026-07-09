"""Unit tests for ingest/hockey_reference.py.

Fixtures are trimmed real HTML fetched from hockey-reference.com during
Phase 4 development (see docs/decisions/0011-hockey-reference-scraper.md
for the verified page structures) -- parsing logic is tested against real
markup, not synthetic guesses. All network access is mocked.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import requests
from loserpoint.ingest.hockey_reference import (
    HockeyReferenceClient,
    HockeyReferenceError,
    build_game_minutes,
    parse_boxscore_goals,
    parse_schedule,
)

FIXTURES = Path(__file__).parent.parent / "fixtures" / "hockey_reference"


def _read(name: str) -> str:
    return (FIXTURES / name).read_text()


def test_parse_schedule_extracts_known_games() -> None:
    schedule = parse_schedule(_read("schedule_2000_snippet.html"), season=1999)
    assert len(schedule) == 10
    by_key = schedule.set_index("game_key")

    dal_game = by_key.loc["199910010DAL"]
    assert dal_game["home_team"] == "DAL"
    assert dal_game["away_team"] == "PIT"
    assert dal_game["home_goals"] == 6
    assert dal_game["away_goals"] == 4
    assert not dal_game["reached_ot"]
    assert not dal_game["decided_by_shootout"]

    edm_game = by_key.loc["199910010EDM"]
    assert edm_game["home_team"] == "EDM"
    assert edm_game["home_goals"] == 1
    assert edm_game["away_goals"] == 1
    assert edm_game["reached_ot"]
    assert not edm_game["decided_by_shootout"]  # no SO in 1999-2000


def test_parse_schedule_raises_on_missing_table() -> None:
    with pytest.raises(HockeyReferenceError, match="no table id='games'"):
        parse_schedule("<html><body>nothing here</body></html>", season=1999)


def test_parse_schedule_raises_on_empty_table() -> None:
    html = '<html><table id="games"><tbody></tbody></table></html>'
    with pytest.raises(HockeyReferenceError, match="no game rows"):
        parse_schedule(html, season=1999)


def test_parse_schedule_handles_cancelled_lockout_season(caplog) -> None:
    # Real text verified on Hockey-Reference's NHL_2005_games.html page --
    # the entire 2004-05 season was cancelled by the NHL lockout, so there
    # is no games table at all. This must return an empty (correctly
    # shaped) DataFrame, not raise. See decision 0012.
    html = (
        "<html><body><p><strong>Note</strong>: This season was cancelled "
        "due to NHL lockout.</p></body></html>"
    )
    with caplog.at_level("WARNING"):
        schedule = parse_schedule(html, season=2004)
    assert len(schedule) == 0
    assert list(schedule.columns) == [
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
    assert any("cancelled" in r.message for r in caplog.records)


def test_parse_schedule_raises_on_missing_table_without_lockout_notice() -> None:
    # A missing table WITHOUT the lockout explanation is a real bug signal
    # (changed page layout, error page, etc.) and must still raise.
    with pytest.raises(HockeyReferenceError, match="no lockout notice"):
        parse_schedule("<html><body>some unrelated page</body></html>", season=1999)


def test_parse_schedule_skips_mid_table_header_repeat_rows() -> None:
    # Sports-Reference sites repeat the header row periodically down long
    # tables for readability; those <tr>s have no csk slug and must be
    # skipped, not mistaken for a game.
    html = """
    <table id="games"><tbody>
    <tr><th data-stat="date_game">Date</th><th data-stat="visitor_team_name">Visitor</th></tr>
    <tr>
        <th data-stat="date_game" csk="199910010DAL"><a>1999-10-01</a></th>
        <td data-stat="visitor_team_name" csk="PIT.199910010DAL">Pittsburgh</td>
        <td data-stat="visitor_goals">4</td>
        <td data-stat="home_team_name" csk="DAL.199910010DAL">Dallas</td>
        <td data-stat="home_goals">6</td>
        <td data-stat="overtimes"></td>
    </tr>
    </tbody></table>
    """
    schedule = parse_schedule(html, season=1999)
    assert len(schedule) == 1
    assert schedule.iloc[0]["game_key"] == "199910010DAL"


def test_parse_boxscore_goals_skips_ot_rows_and_caption_rows() -> None:
    # An "Overtime" period header (unmapped in PERIOD_LABELS -> period=None)
    # followed by a goal row must be skipped entirely; a stray row with
    # fewer than 5 cells (e.g. a caption) must also be skipped.
    html = """
    <table id="scoring">
    <caption>Scoring Summary Table</caption>
    <tr class="thead onecell"><th colspan="5">1st Period</th></tr>
    <tr>
        <td>03:10</td><td><a>DAL</a></td><td></td><td>Scorer</td><td>Assist</td>
    </tr>
    <tr class="thead onecell"><th colspan="5">Overtime</th></tr>
    <tr>
        <td>02:00</td><td><a>DAL</a></td><td></td><td>OT Scorer</td><td></td>
    </tr>
    </table>
    """
    goals = parse_boxscore_goals(html, home_team="DAL")
    assert len(goals) == 1
    assert goals[0].time == 190
    assert goals[0].period == 1


def test_parse_boxscore_goals_skips_rows_with_no_team_link() -> None:
    # A 5-cell row whose team cell has no <a> (e.g. a malformed or
    # non-goal informational row) must be skipped, not crash.
    html = """
    <table id="scoring">
    <tr class="thead onecell"><th colspan="5">1st Period</th></tr>
    <tr>
        <td>05:00</td><td>no link here</td><td></td><td>x</td><td>y</td>
    </tr>
    <tr>
        <td>07:21</td><td><a>DAL</a></td><td></td><td>Scorer</td><td></td>
    </tr>
    </table>
    """
    goals = parse_boxscore_goals(html, home_team="DAL")
    assert len(goals) == 1
    assert goals[0].time == 441


def test_parse_boxscore_goals_no_ot_game() -> None:
    # DAL is home; real scoring from 199910010DAL.html: PIT@0:03:10 (1st),
    # DAL@0:07:21 (1st, PP), DAL@0:18:29 (1st, PP), plus more later periods.
    goals = parse_boxscore_goals(_read("box_no_ot.html"), home_team="DAL")
    assert len(goals) > 0
    assert all(not g.is_phantom for g in goals)
    first_three = goals[:3]
    assert [(g.time, g.is_home_team, g.period) for g in first_three] == [
        (190, False, 1),  # PIT @ 3:10 -- away team (PIT != DAL)
        (441, True, 1),  # DAL @ 7:21
        (1109, True, 1),  # DAL @ 18:29
    ]
    # No goal should ever land in period 4+ (this game had no OT).
    assert all(g.period <= 3 for g in goals)


def test_parse_boxscore_goals_scoreless_ot_produces_no_ot_goals() -> None:
    # NYR @ EDM ended 1-1; OT was played but scoreless, so the scoring
    # table has no "Overtime" section at all -- confirms real ties existed
    # pre-shootout (the mechanism the loser point was introduced to soften).
    goals = parse_boxscore_goals(_read("box_tie_ot.html"), home_team="EDM")
    assert len(goals) == 2
    assert sum(1 for g in goals if g.is_home_team) == 1
    assert sum(1 for g in goals if not g.is_home_team) == 1
    assert all(g.period <= 3 for g in goals)


def test_parse_boxscore_goals_raises_on_missing_table() -> None:
    with pytest.raises(HockeyReferenceError, match="no table id='scoring'"):
        parse_boxscore_goals("<html><body>nothing</body></html>", home_team="DAL")


def test_build_game_minutes_reuses_score_state_and_sums_goals() -> None:
    goals = parse_boxscore_goals(_read("box_tie_ot.html"), home_team="EDM")
    game = {
        "season": 1999,
        "game_key": "199910010EDM",
        "home_team": "EDM",
        "away_team": "NYR",
    }
    panel = build_game_minutes(game, goals)

    assert len(panel) == 120
    assert panel["goals_for"].sum() == 2  # one goal each team, both regulation
    home = panel[panel["is_home"]].set_index("minute")
    away = panel[~panel["is_home"]].set_index("minute")
    assert home.loc[1, "score_state"] == "tied"
    assert (home["score_diff"] == -away["score_diff"]).all()
    assert (home["team_code"] == "EDM").all()
    assert (home["opp_code"] == "NYR").all()
    assert (away["team_code"] == "NYR").all()


# ---------------------------------------------------------------------------
# HockeyReferenceClient: caching, rate limiting, error handling
# ---------------------------------------------------------------------------


class _FakeResponse:
    def __init__(self, status_code: int, text: str = "") -> None:
        self.status_code = status_code
        self.text = text


class _FakeSession:
    def __init__(self, responses: dict[str, _FakeResponse]) -> None:
        self.responses = responses
        self.calls: list[str] = []

    def get(self, url, headers=None, timeout=None):
        self.calls.append(url)
        return self.responses[url]


def test_client_caches_to_disk_and_does_not_refetch(tmp_path) -> None:
    session = _FakeSession(
        {"https://www.hockey-reference.com/boxscores/x.html": _FakeResponse(200, "<html>ok</html>")}
    )
    client = HockeyReferenceClient(
        tmp_path, user_agent="test-agent", min_request_interval_seconds=0, session=session
    )
    first = client.get("/boxscores/x.html")
    second = client.get("/boxscores/x.html")
    assert first == second == "<html>ok</html>"
    assert len(session.calls) == 1
    assert (tmp_path / "boxscores" / "x.html").exists()


def test_client_sends_configured_user_agent(tmp_path) -> None:
    captured = {}

    class _CapturingSession:
        def get(self, url, headers=None, timeout=None):
            captured["headers"] = headers
            return _FakeResponse(200, "<html></html>")

    client = HockeyReferenceClient(
        tmp_path,
        user_agent="loser-point-research/0.1 (test)",
        min_request_interval_seconds=0,
        session=_CapturingSession(),
    )
    client.get("/boxscores/y.html")
    assert captured["headers"]["User-Agent"] == "loser-point-research/0.1 (test)"


def test_client_raises_with_guidance_on_non_200(tmp_path) -> None:
    session = _FakeSession(
        {"https://www.hockey-reference.com/boxscores/missing.html": _FakeResponse(404)}
    )
    client = HockeyReferenceClient(
        tmp_path, user_agent="test-agent", min_request_interval_seconds=0, session=session
    )
    with pytest.raises(HockeyReferenceError, match="HTTP 404"):
        client.get("/boxscores/missing.html")


def test_client_raises_with_guidance_on_connection_error(tmp_path) -> None:
    class _RaisingSession:
        def get(self, url, headers=None, timeout=None):
            raise requests.ConnectionError("no route to host")

    client = HockeyReferenceClient(
        tmp_path,
        user_agent="test-agent",
        min_request_interval_seconds=0,
        max_retries=2,
        retry_backoff_seconds=0,
        session=_RaisingSession(),
    )
    with pytest.raises(HockeyReferenceError, match="could not reach"):
        client.get("/boxscores/z.html")


def test_client_retries_transient_network_error_then_succeeds(tmp_path, caplog) -> None:
    # Regression test for bugs_found.md #10: a single read-timeout used to
    # kill the entire multi-hour scrape. A transient failure must now be
    # retried, not raised immediately.
    class _FlakyThenOkSession:
        def __init__(self) -> None:
            self.calls = 0

        def get(self, url, headers=None, timeout=None):
            self.calls += 1
            if self.calls < 3:
                raise requests.ConnectionError("read timed out")
            return _FakeResponse(200, "<html>recovered</html>")

    session = _FlakyThenOkSession()
    client = HockeyReferenceClient(
        tmp_path,
        user_agent="test-agent",
        min_request_interval_seconds=0,
        max_retries=5,
        retry_backoff_seconds=0,
        session=session,
    )
    with caplog.at_level("WARNING"):
        result = client.get("/boxscores/flaky.html")
    assert result == "<html>recovered</html>"
    assert session.calls == 3
    assert sum("failed (attempt" in r.message for r in caplog.records) == 2
