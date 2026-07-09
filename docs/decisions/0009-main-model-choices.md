# 0009 — Main model specification choices (Phase 3)

**Status:** Decided before estimation; sign predictions recorded in
docs/methodology.md pre-registration style.

## Reference state: down-1, not "one-goal games"

Following decision 0008, the estimand is the tied state's *differential*
late-game change versus the down-1 state:

```
attempts ~ i(score_state, late, ref='down_1') + score_state + late
           + is_home + rest_diff + elo_diff_100 | team + opp + season
```

estimated by Poisson QMLE (pyfixest.fepois), SEs clustered by game. With
down-1 as the reference, the coefficient `score_state::tied:late` is
directly the difference-in-differences — (tied late vs tied mid) minus
(down-1 late vs down-1 mid) — no post-hoc contrast arithmetic. Down-1 is
the right benchmark because a down-1 team has nothing banked (status quo
= 0 points), making it the closest observable stand-in for "play when only
winning matters." The up-1 interaction is reported alongside as the
lead-protection yardstick that would exist under any point system.

## Sample window: minutes 41-58

The third period exactly (minute 40 belongs to the second period), ending
at 58 because goalie pulls destroy the one-goal states' 5v5 sample in
minutes 59-60 (decision 0008 artifact 1). Late window default = 56-58;
sensitivity at 55/56/57 in the robustness battery.

## xG outcome uses the same Poisson QMLE

Poisson pseudo-maximum-likelihood is consistent for any non-negative
outcome with a correctly specified conditional mean (Gourieroux, Monfort
& Trognon 1984; Santos Silva & Tenreyro 2006) — no separate gamma/quasi
machinery, same code path, same interpretation of exponentiated
coefficients.

## Elo constants

Fixed K=8, home ice +50 Elo, season carryover regresses one third to
1505, expansion teams (VGK, SEA) debut at 1380. Elo is a *control*, not an
estimate of interest; the simplest defensible variant beats a tunable one
(interview rule: every number explainable in one sentence).

## Games the sources disagree on are kept, and counted

Cross-source reconciliation (validate/checks.py) found 41 of 22,834
regular-season games (0.18%) where the MoneyPuck-reconstructed final
score disagrees with the NHL API — overwhelmingly the decision-0006 blind
spot (a goal after the game's final shot row leaves no trace in shot
data). At 0.18% with no plausible correlation to the tied-late estimand,
dropping them would be cosmetic; they are retained and disclosed in
docs/methodology.md's limitations.

## Playoff-probability Monte Carlo: deferred to Phase 5

The playoff-race simulation needs per-season division/conference
alignments and tiebreaker rules (realignment in 2013, Vegas 2017, Seattle
2021, the 2020 COVID play-in) — a data-engineering task with no consumer
until the Phase 5 heterogeneity analysis. Building it now would be
speculative plumbing; it is deferred to Phase 5 where its requirements are
concrete. The standings-on-date API endpoint it needs is already
implemented and cached (`NHLApiClient.league_standings`).
