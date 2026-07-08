"""Descriptive analysis: late-game intensity curves by score state.

Produces the project's headline empirical fact -- mean 5v5 unblocked shot
attempts (Fenwick) per team-minute over the third period, by the score
state each team *entered* the minute with -- plus game-level
cluster-bootstrap confidence intervals and the headline contrasts.

Two artifacts shape everything here (decision 0008): the one-goal states'
5v5 sample collapses at minutes 59-60 (goalie pulls), so any window
involving them ends at minute 58; and up-1 / down-1 must never be pooled,
because their opposing late-game incentives nearly cancel.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from loserpoint.utils.logging import get_logger

logger = get_logger(__name__)

# The three states of the headline figure. up_1 and down_1 are deliberately
# NOT pooled -- see decision 0008, artifact 2.
HEADLINE_STATES = ("tied", "down_1", "up_1")

# Minutes 59-60 are only usable for the tied state; one-goal states lose
# their 5v5 sample to goalie pulls (decision 0008, artifact 1).
ONE_GOAL_LAST_CLEAN_MINUTE = 58


def analysis_subset(game_minutes: pd.DataFrame) -> pd.DataFrame:
    """The primary descriptive sample: regular season, 5v5 minutes only
    (per the non_5v5 flag of decision 0006 rule 5).

    Interpretation: each remaining row is one team's even-strength offensive
    output in one regulation minute, with empty-net-context shots already
    excluded from `attempts_main` by the panel build (decision 0006 rule 6).
    """
    return game_minutes[~game_minutes["is_playoff"] & ~game_minutes["non_5v5_flag"]]


def intensity_curves(
    game_minutes: pd.DataFrame,
    *,
    outcome: str = "attempts_main",
    # Minute 41 is the first minute of the third period; minute 40 belongs
    # to the second. The window is exactly the third period.
    first_minute: int = 41,
    states: tuple[str, ...] = HEADLINE_STATES,
    n_boot: int = 500,
    seed: int = 0,
) -> pd.DataFrame:
    """Mean `outcome` per team-minute by minute and score state, with
    game-level cluster-bootstrap CIs.

    The bootstrap resamples *games* (not rows) with replacement, respecting
    that the two team-rows of a game-minute -- and all 60 minutes of a game
    -- are correlated. 95% intervals are the 2.5/97.5 percentiles across
    replicates.

    Interpretation: the loser-point signature is an ordering, not a single
    gap -- down-1 teams (nothing banked) should hold their intensity, up-1
    teams (protecting 2 points) should cut it hard, and tied teams should
    sit far closer to the protectors than to the pushers, because the OT
    point floor gives them something to protect too.

    Args:
        game_minutes: panel rows (pass through `analysis_subset` first).
        outcome: which panel count column to average.
        first_minute: left edge of the plotted window (through minute 60).
        states: score states to compute curves for.
        n_boot: bootstrap replicates.
        seed: RNG seed for reproducibility.

    Returns:
        DataFrame with columns minute, score_state, mean, lo, hi, n_obs.
        Curves for one-goal states stop at ONE_GOAL_LAST_CLEAN_MINUTE.
    """
    window = game_minutes[game_minutes["minute"] >= first_minute]
    frames = []
    rng = np.random.default_rng(seed)

    for state in states:
        last_minute = 60 if state == "tied" else ONE_GOAL_LAST_CLEAN_MINUTE
        rows = window[(window["score_state"] == state) & (window["minute"] <= last_minute)]
        point = rows.groupby("minute")[outcome].agg(["mean", "size"])

        # Cluster bootstrap: resample (season, game_id) pairs, then
        # recompute each minute's mean from the resampled games' rows.
        keys = rows[["season", "game_id"]].drop_duplicates()
        indexed = rows.set_index(["season", "game_id"])
        boot_means = np.full((n_boot, len(point)), np.nan)
        minutes_order = point.index.to_numpy()
        for b in range(n_boot):
            draw = keys.sample(frac=1.0, replace=True, random_state=rng.integers(2**32))
            resampled = indexed.loc[pd.MultiIndex.from_frame(draw)]
            means = resampled.groupby("minute")[outcome].mean()
            boot_means[b] = means.reindex(minutes_order).to_numpy()
        lo, hi = np.nanpercentile(boot_means, [2.5, 97.5], axis=0)

        frames.append(
            pd.DataFrame(
                {
                    "minute": minutes_order,
                    "score_state": state,
                    "mean": point["mean"].to_numpy(),
                    "lo": lo,
                    "hi": hi,
                    "n_obs": point["size"].to_numpy(),
                }
            )
        )
    curves = pd.concat(frames, ignore_index=True)
    logger.info(
        "intensity curves: %d cells from %d team-minute rows (%s)",
        len(curves),
        len(window),
        outcome,
    )
    return curves


def headline_contrasts(
    curves: pd.DataFrame, *, late_start: int = 56, mid_start: int = 41
) -> dict[str, float]:
    """The numbers the README leads with: each state's late-window drop
    relative to its own mid-third-period baseline.

    All windows involving one-goal states end at minute 58 (decision 0008
    artifact 1); the tied state's own drop is also reported over the same
    56-58 window so the three numbers are directly comparable.

    Interpretation: `tied_drop_pct` between `up1_drop_pct` (lead
    protection, exists under any point system) and `down1_drop_pct`
    (desperation floor) is the descriptive signature -- how much of a
    "lead" tied teams act like they are protecting.
    """
    result: dict[str, float] = {"late_start": late_start, "late_end": 58}
    for state, key in (("tied", "tied"), ("down_1", "down1"), ("up_1", "up1")):
        sub = curves[curves["score_state"] == state].set_index("minute")["mean"]
        mid = sub[(sub.index >= mid_start) & (sub.index < late_start)].mean()
        late = sub[(sub.index >= late_start) & (sub.index <= 58)].mean()
        result[f"{key}_drop_pct"] = 100 * (late / mid - 1)
    return result
