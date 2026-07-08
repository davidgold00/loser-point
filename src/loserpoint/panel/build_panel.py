"""Builds the game x team x minute panel from cleaned shot data.

Consumes the validated output of `ingest.moneypuck.ingest_season` (never
the raw CSVs directly -- ingest's cleaning steps are part of the contract)
and produces two tables:

- `game_minutes`: one row per game x team x regulation minute (always
  exactly 120 rows per game), carrying the score state *entering* the
  minute and shot-attempt/xG counts under the four filter combinations of
  decision 0006 rule 6.
- `games`: one row per game with outcome variables (reached OT, shootout,
  regulation and final scores).

`check_panel_invariants` runs inside the build (and again as pytest
integration tests): a panel that violates any structural invariant is a
bug, and the build refuses to write it.

Column definitions are documented in
docs/data_dictionaries/panel_tables.md, kept next to the schemas in
validate/schemas.py.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from loserpoint.panel.score_state import (
    MIRROR_STATE,
    REGULATION_MAX_PERIOD,
    REGULATION_MINUTES,
    REGULATION_SECONDS,
    STATE_BINS,
    InconsistentGameError,
    extract_goal_events,
    game_outcomes,
    minute_of_time,
    minute_states,
)
from loserpoint.utils.logging import get_logger

logger = get_logger(__name__)


class PanelInvariantError(AssertionError):
    """A structural invariant of the panel is violated -- always a bug in
    panel construction (or a corrupted input), never a data quirk to
    tolerate."""


def _build_game_rows(game: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    """Build one game's 120 panel rows and its games-table row."""
    outcomes = game_outcomes(game)
    goals = extract_goal_events(game)
    states = minute_states(goals)
    first = game.iloc[0]
    home_code, away_code = first["homeTeamCode"], first["awayTeamCode"]

    reg = game[
        (game["period"] <= REGULATION_MAX_PERIOD) & (game["time"] <= REGULATION_SECONDS)
    ].copy()
    reg["minute"] = reg["time"].map(minute_of_time)
    reg["is_5v5"] = (reg["homeSkatersOnIce"] == 5) & (reg["awaySkatersOnIce"] == 5)
    # Empty-net policy (a): drop shots on an empty net, and shots by a team
    # whose own goalie is pulled (their net is the empty one).
    shooter_net_empty = ((reg["isHomeTeam"] == 1) & (reg["homeEmptyNet"] == 1)) | (
        (reg["isHomeTeam"] == 0) & (reg["awayEmptyNet"] == 1)
    )
    reg["en_keep"] = ~((reg["shotOnEmptyNet"] == 1) | shooter_net_empty)

    non_5v5_minutes = set(reg.loc[~reg["is_5v5"], "minute"])

    def aggregate(mask: pd.Series, prefix: str) -> pd.DataFrame:
        subset = reg[mask]
        agg = (
            subset.groupby(["isHomeTeam", "minute"])
            .agg(attempts=("event", "size"), xg=("xGoal", "sum"))
            .rename(columns={"attempts": f"attempts_{prefix}", "xg": f"xg_{prefix}"})
        )
        return agg

    aggregates = pd.concat(
        [
            aggregate(reg["is_5v5"] & reg["en_keep"], "main"),
            aggregate(reg["is_5v5"], "5v5_incl_en"),
            aggregate(reg["en_keep"], "all_ex_en"),
            aggregate(pd.Series(True, index=reg.index), "naive"),
        ],
        axis=1,
    )

    reg_goal_counts: dict[tuple[bool, int], int] = {}
    for g in goals:
        if g.is_regulation:
            key = (g.is_home_team, minute_of_time(g.time))
            reg_goal_counts[key] = reg_goal_counts.get(key, 0) + 1

    frames = []
    for is_home in (True, False):
        side = pd.DataFrame({"minute": range(1, REGULATION_MINUTES + 1)})
        diff = states["home_score"] - states["away_score"]
        side["score_diff"] = (diff if is_home else -diff).astype(int)
        side["score_state"] = states["home_state" if is_home else "away_state"]
        side["is_home"] = is_home
        side["team_code"] = home_code if is_home else away_code
        side["opp_code"] = away_code if is_home else home_code
        side["goals_for"] = [
            reg_goal_counts.get((is_home, minute), 0) for minute in range(1, REGULATION_MINUTES + 1)
        ]
        team_agg = (
            aggregates.loc[int(is_home)]
            if int(is_home) in aggregates.index.get_level_values(0)
            else pd.DataFrame(columns=aggregates.columns)
        )
        side = side.merge(team_agg, how="left", left_on="minute", right_index=True)
        frames.append(side)

    minutes = pd.concat(frames, ignore_index=True)
    count_cols = [c for c in minutes.columns if c.startswith(("attempts_", "xg_"))]
    minutes[count_cols] = minutes[count_cols].fillna(0)
    for col in count_cols:
        if col.startswith("attempts_"):
            minutes[col] = minutes[col].astype(int)
    minutes["non_5v5_flag"] = minutes["minute"].isin(non_5v5_minutes)
    minutes["game_id"] = outcomes.game_id
    minutes["season"] = outcomes.season
    minutes["is_playoff"] = outcomes.is_playoff

    game_row = {
        "game_id": outcomes.game_id,
        "season": outcomes.season,
        "is_playoff": outcomes.is_playoff,
        "home_team": home_code,
        "away_team": away_code,
        "reg_home_goals": outcomes.reg_home_goals,
        "reg_away_goals": outcomes.reg_away_goals,
        "final_home_goals": outcomes.final_home_goals,
        "final_away_goals": outcomes.final_away_goals,
        "reached_ot": outcomes.reached_ot,
        "decided_by_shootout": outcomes.decided_by_shootout,
        "home_won": outcomes.home_won,
        "n_phantom_goals": outcomes.n_phantom_goals,
    }
    return minutes, game_row


def build_panel(shots: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Build the full panel from (possibly multi-game) cleaned shot data.

    Interpretation: `game_minutes` is the estimation dataset -- each row
    answers "how hard did this team play during this minute, given the
    score state it entered the minute with?" `games` holds the outcomes
    (reached OT / shootout) those behaviors produce.

    Returns:
        (game_minutes, games) -- see module docstring.
    """
    minute_frames = []
    game_rows = []
    dropped: list[int] = []
    for (_, game_id), game in shots.groupby(["season", "game_id"], sort=True):
        try:
            minutes, game_row = _build_game_rows(game)
        except InconsistentGameError as exc:
            # A game whose recorded running score is internally inconsistent
            # even after ingest cleaning is provably corrupt, and we have no
            # ground truth to repair it against until the NHL API client
            # exists (Phase 3). Dropping it loudly beats inventing a fix.
            # Confirmed real example: 2007 game 20274 (T.B vs WSH), which
            # has a duplicated GOAL row AND a homeTeamWon flag contradicting
            # its own recorded final score. See decision 0007.
            logger.warning("dropping corrupt game %s from panel: %s", game_id, exc)
            dropped.append(int(game_id))
            continue
        minute_frames.append(minutes)
        game_rows.append(game_row)
    game_minutes = pd.concat(minute_frames, ignore_index=True)
    games = pd.DataFrame(game_rows)
    logger.info(
        "built panel: %d game-minute rows from %d games (%d corrupt game(s) dropped: %s)",
        len(game_minutes),
        len(games),
        len(dropped),
        dropped or "none",
    )
    return game_minutes, games


def check_panel_invariants(game_minutes: pd.DataFrame, games: pd.DataFrame) -> None:
    """Verify every structural invariant of the panel; raise on the first
    violated one with enough detail to debug it.

    Invariants (also mirrored as integration tests):
      1. every game has exactly 120 rows: 60 minutes x 2 teams, no dupes;
      2. per game and team, goals_for sums to the games-table regulation
         score;
      3. mirror consistency: the two team rows of a game-minute have
         opposite score_diff and mirrored score_state;
      4. minute 1 is always entered tied;
      5. attempt and xG columns are non-negative; states are valid labels.

    Raises:
        PanelInvariantError: on any violation.
    """
    row_counts = game_minutes.groupby(["season", "game_id"]).size()
    bad = row_counts[row_counts != 2 * REGULATION_MINUTES]
    if len(bad):
        raise PanelInvariantError(f"games without exactly 120 panel rows: {dict(bad.head(5))}")
    dupes = game_minutes.duplicated(subset=["season", "game_id", "is_home", "minute"])
    if dupes.any():
        raise PanelInvariantError(
            f"duplicate (game, team, minute) rows: "
            f"{game_minutes.loc[dupes, ['game_id', 'is_home', 'minute']].head(5).to_dict('records')}"
        )

    goal_sums = (
        game_minutes.groupby(["season", "game_id", "is_home"])["goals_for"].sum().unstack("is_home")
    )
    merged = goal_sums.join(
        games.set_index(["season", "game_id"])[["reg_home_goals", "reg_away_goals"]]
    )
    home_bad = merged[merged[True] != merged["reg_home_goals"]]
    away_bad = merged[merged[False] != merged["reg_away_goals"]]
    if len(home_bad) or len(away_bad):
        raise PanelInvariantError(
            "panel goals_for sums disagree with games-table regulation scores; "
            f"first offenders: {list(home_bad.index[:3]) + list(away_bad.index[:3])}"
        )

    # Label validity runs before the mirror check: an invalid label would
    # otherwise always surface as a confusing "mirror violation" instead of
    # naming the actual problem.
    invalid_states = set(game_minutes["score_state"]) - set(STATE_BINS)
    if invalid_states:
        raise PanelInvariantError(f"invalid score_state labels: {invalid_states}")

    wide = game_minutes.pivot_table(
        index=["season", "game_id", "minute"],
        columns="is_home",
        values="score_diff",
        aggfunc="first",
    )
    asymmetric = wide[wide[True] != -wide[False]]
    if len(asymmetric):
        raise PanelInvariantError(
            f"mirror violation -- score_diff does not negate between team rows at: "
            f"{list(asymmetric.index[:5])}"
        )
    states_wide = game_minutes.pivot_table(
        index=["season", "game_id", "minute"],
        columns="is_home",
        values="score_state",
        aggfunc="first",
    )
    state_mismatch = states_wide[states_wide[True].map(MIRROR_STATE) != states_wide[False]]
    if len(state_mismatch):
        raise PanelInvariantError(
            f"mirror violation -- score_state does not mirror at: {list(state_mismatch.index[:5])}"
        )

    minute_one = game_minutes[game_minutes["minute"] == 1]
    if (minute_one["score_state"] != "tied").any() or (minute_one["score_diff"] != 0).any():
        raise PanelInvariantError("some games are not entered tied at minute 1")

    count_cols = [c for c in game_minutes.columns if c.startswith(("attempts_", "xg_"))]
    if (game_minutes[count_cols] < 0).any().any():
        raise PanelInvariantError("negative attempt/xG values in panel")

    logger.info("panel invariants verified: %d games, %d rows", len(games), len(game_minutes))


def main() -> None:
    from loserpoint.ingest.moneypuck import ingest_season
    from loserpoint.utils.config import load_config
    from loserpoint.utils.io import write_parquet
    from loserpoint.validate.schemas import PANEL_GAMES_SCHEMA, PANEL_MINUTES_SCHEMA

    config = load_config()
    raw_dir = Path("data/raw/moneypuck")
    interim_dir = Path("data/interim/moneypuck")

    minute_frames, game_frames = [], []
    for season in range(config.seasons.modern_start, config.seasons.modern_end + 1):
        shots = ingest_season(season, raw_dir, interim_dir)
        game_minutes, games = build_panel(shots)
        check_panel_invariants(game_minutes, games)
        minute_frames.append(game_minutes)
        game_frames.append(games)

    all_minutes = pd.concat(minute_frames, ignore_index=True)
    all_games = pd.concat(game_frames, ignore_index=True)
    PANEL_MINUTES_SCHEMA.validate(all_minutes, lazy=True)
    PANEL_GAMES_SCHEMA.validate(all_games, lazy=True)
    write_parquet(all_minutes, Path("data/processed/game_minutes.parquet"))
    write_parquet(all_games, Path("data/processed/games.parquet"))


if __name__ == "__main__":
    main()
