"""Simulate-and-recover: the estimation pipeline must recover a KNOWN
injected turtling effect from synthetic data, and must NOT find one when
none is injected.

This is the strongest correctness evidence in the repo: it exercises the
exact production formula, reference coding, clustering, and IRR extraction
(fit_main_model + extract_estimates) against data whose true parameters we
chose ourselves.

The simulated world mirrors the real panel's structure: each game is
either a tied game (both teams tied) or a one-goal game (one team up_1,
the mirror team down_1); team/opponent/season effects, home ice, and an
Elo gradient all shift the Poisson rate, so recovery fails if the fixed
effects or controls are wired wrong -- not just if the interaction term is.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
from loserpoint.analysis.models import extract_estimates, fit_main_model

N_GAMES = 4000
N_TEAMS = 12
MINUTES = range(41, 59)
LATE_START = 56

# True data-generating parameters (log scale).
BASE_RATE = np.log(0.6)
LATE_EFFECT = -0.05  # everyone slows a little late
TIED_LEVEL = -0.08
UP1_LEVEL = -0.15
HOME_EFFECT = 0.04
ELO_EFFECT = 0.10  # per 100 Elo points of edge
TRUE_UP1_LATE = -0.12  # lead protection differential (always present)


def simulate_panel(delta_tied_late: float, seed: int = 42) -> pd.DataFrame:
    """Build a model-ready sample with a known tied x late effect."""
    rng = np.random.default_rng(seed)
    team_quality = rng.normal(0, 0.08, N_TEAMS)  # log-rate offense
    team_defense = rng.normal(0, 0.08, N_TEAMS)  # log-rate allowed
    elo = 1500 + 400 * team_quality  # Elo consistent with quality

    rows = []
    for g in range(N_GAMES):
        home, away = rng.choice(N_TEAMS, size=2, replace=False)
        season = 2013 + g % 3
        tied_game = rng.random() < 0.5
        for is_home, team, opp in ((1, home, away), (0, away, home)):
            if tied_game:
                state = "tied"
            else:
                # the home team leads in half the one-goal games
                leader_is_home = g % 2 == 0
                state = "up_1" if (is_home == int(leader_is_home)) else "down_1"
            elo_diff_100 = (elo[team] - elo[opp]) / 100
            for minute in MINUTES:
                late = int(minute >= LATE_START)
                log_rate = (
                    BASE_RATE
                    + team_quality[team]
                    + team_defense[opp]
                    + 0.03 * (season - 2013)
                    + HOME_EFFECT * is_home
                    + ELO_EFFECT * elo_diff_100
                    + LATE_EFFECT * late
                    + {"tied": TIED_LEVEL, "up_1": UP1_LEVEL, "down_1": 0.0}[state]
                    + (delta_tied_late if (state == "tied" and late) else 0.0)
                    + (TRUE_UP1_LATE if (state == "up_1" and late) else 0.0)
                )
                rows.append(
                    {
                        "attempts_main": rng.poisson(np.exp(log_rate)),
                        "score_state": state,
                        "late": late,
                        "is_home": is_home,
                        "rest_diff": 0,
                        "elo_diff_100": elo_diff_100,
                        "team_code": f"T{team}",
                        "opp_code": f"T{opp}",
                        "season": season,
                        "game_key": g,
                    }
                )
    return pd.DataFrame(rows)


@pytest.mark.slow
def test_pipeline_recovers_injected_turtling_effect() -> None:
    # Tolerances are SE-scaled, not flat: a single finite simulation of
    # this size has an interaction SE of ~0.023, so demanding (say) 0.01
    # absolute accuracy would fail on pure sampling noise. Unbiasedness
    # beyond this was verified during the build by averaging 8 seeds
    # (mean recovered -0.091 for truth -0.10, i.e. within 2 mean-SEs) and
    # by a placebo with all late effects zeroed (clean).
    delta = -0.10  # tied teams cut ~9.5% more than down-1 teams late
    sample = simulate_panel(delta_tied_late=delta, seed=1)
    model = fit_main_model(sample, outcome="attempts_main")
    estimates = {e.state: e for e in extract_estimates(model, outcome="attempts_main")}

    tied = estimates["tied"]
    assert tied.coef == pytest.approx(delta, abs=3 * tied.se)
    assert tied.ci_low_pct < 100 * (np.exp(delta) - 1) < tied.ci_high_pct
    # The always-present lead-protection differential is recovered too.
    up1 = estimates["up_1"]
    assert up1.coef == pytest.approx(TRUE_UP1_LATE, abs=3 * up1.se)
    # IRR/pct arithmetic is consistent with the raw coefficient.
    assert tied.irr == pytest.approx(np.exp(tied.coef))
    assert tied.pct == pytest.approx(100 * (np.exp(tied.coef) - 1))
    # And the effect is actually detected, not just bracketed: the CI
    # excludes zero by a wide margin.
    assert tied.ci_high_pct < -1.0


@pytest.mark.slow
def test_pipeline_finds_no_effect_when_none_injected() -> None:
    sample = simulate_panel(delta_tied_late=0.0, seed=7)
    model = fit_main_model(sample, outcome="attempts_main")
    tied = {e.state: e for e in extract_estimates(model, outcome="attempts_main")}["tied"]
    # No false positive: the zero must sit comfortably inside the CI.
    assert abs(tied.coef / tied.se) < 3.0
    assert tied.ci_low_pct < 0.0 < tied.ci_high_pct
