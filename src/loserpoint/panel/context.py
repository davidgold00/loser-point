"""Game-level context: Elo ratings and rest days.

Consumes the NHL API game-results table (ingest/nhl_api.py) -- which has
the dates and final scores the MoneyPuck shot data lacks -- and produces
one row per game with each side's pre-game Elo and days of rest. These are
*controls* in the main models (they absorb "evenly matched teams are more
likely to be tied late"), not headline estimates, so the Elo here is the
simplest defensible variant: fixed K, fixed home-ice bonus, no
margin-of-victory multiplier. Constants follow common NHL Elo practice
(FiveThirtyEight's NHL model uses the same season-carryover and expansion
conventions); swapping variants is a robustness exercise, not a design
decision this project's results hinge on.
"""

from __future__ import annotations

import pandas as pd

from loserpoint.utils.logging import get_logger

logger = get_logger(__name__)

INITIAL_ELO = 1500.0
EXPANSION_ELO = 1380.0  # new franchises (VGK 2017, SEA 2021) start below par
MEAN_ELO = 1505.0
SEASON_CARRYOVER = 2 / 3  # regress one third of the way to the mean each summer
K_FACTOR = 8.0
HOME_ICE_ELO = 50.0
MAX_REST_DAYS = 7  # beyond a week, more rest is not more of anything


def expected_home_win_prob(home_elo: float, away_elo: float) -> float:
    """Standard Elo logistic expectation with the home-ice bonus applied.

    Interpretation: the probability the home team wins the game (in any
    fashion -- regulation, OT, or shootout; Elo here does not distinguish).
    """
    return 1.0 / (1.0 + 10.0 ** (-(home_elo + HOME_ICE_ELO - away_elo) / 400.0))


def _rest_days(last_played: dict[str, pd.Timestamp], team: str, date: pd.Timestamp) -> int:
    if team not in last_played:
        return MAX_REST_DAYS
    return int(min((date - last_played[team]).days, MAX_REST_DAYS))


def compute_game_context(results: pd.DataFrame) -> pd.DataFrame:
    """Walk all games chronologically, computing pre-game Elo and rest days.

    Args:
        results: the NHL API game-results table (one row per game with
            season, game_id, date, home_team, away_team, home_score,
            away_score). Regular-season AND playoff games both update Elo;
            a game with missing scores (never played / not yet played) is
            skipped with a warning.

    Returns:
        One row per game: season, game_id, home_elo_pre, away_elo_pre,
        elo_diff_home (home minus away, before the home-ice bonus),
        home_rest_days, away_rest_days (capped at MAX_REST_DAYS; a team's
        first game of a season gets the cap -- everyone is fully rested on
        opening night).
    """
    results = results.sort_values(["date", "game_id"]).reset_index(drop=True)
    results["date"] = pd.to_datetime(results["date"])

    elo: dict[str, float] = {}
    last_played: dict[str, pd.Timestamp] = {}
    current_season: int | None = None
    first_season = int(results["season"].min())
    rows: list[dict] = []

    for game in results.itertuples(index=False):
        if game.season != current_season:
            # Off-season: regress every team toward the league mean; wipe
            # rest-day history (opening night = fully rested).
            elo = {
                team: MEAN_ELO + SEASON_CARRYOVER * (rating - MEAN_ELO)
                for team, rating in elo.items()
            }
            last_played = {}
            current_season = game.season

        if pd.isna(game.home_score) or pd.isna(game.away_score):
            logger.warning(
                "season %s game %s has no final score in the NHL API data -- "
                "skipping for Elo/rest purposes.",
                game.season,
                game.game_id,
            )
            continue

        # Teams first seen in the first processed season start at par (we
        # simply don't know their history); teams first seen in a LATER
        # season are true expansion franchises (VGK 2017, SEA 2021) and
        # start below par.
        debut_elo = INITIAL_ELO if game.season == first_season else EXPANSION_ELO
        home, away = game.home_team, game.away_team
        home_elo = elo.setdefault(home, debut_elo)
        away_elo = elo.setdefault(away, debut_elo)

        rows.append(
            {
                "season": game.season,
                "game_id": game.game_id,
                "home_elo_pre": home_elo,
                "away_elo_pre": away_elo,
                "elo_diff_home": home_elo - away_elo,
                "home_rest_days": _rest_days(last_played, home, game.date),
                "away_rest_days": _rest_days(last_played, away, game.date),
            }
        )

        home_won = game.home_score > game.away_score
        expected = expected_home_win_prob(home_elo, away_elo)
        delta = K_FACTOR * ((1.0 if home_won else 0.0) - expected)
        elo[home] = home_elo + delta
        elo[away] = away_elo - delta
        last_played[home] = game.date
        last_played[away] = game.date

    context = pd.DataFrame(rows)
    logger.info("game context: Elo + rest computed for %d games", len(context))
    return context


def main() -> None:
    from pathlib import Path

    from loserpoint.utils.io import write_parquet

    results = pd.read_parquet("data/interim/nhl_api/game_results.parquet")
    context = compute_game_context(results)
    write_parquet(context, Path("data/processed/game_context.parquet"))


if __name__ == "__main__":
    main()
