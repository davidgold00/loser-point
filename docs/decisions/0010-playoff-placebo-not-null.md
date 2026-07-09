# 0010 — The playoff "placebo" is not null, and what that honestly means

**Status:** Empirical surprise from the Phase 3 robustness battery,
documented before writing the methodology results section.

## The pre-registered prediction, and what came back

The original design treated playoff games as a placebo: no loser point in
the playoffs, so the tied-late differential "should NOT appear." The
battery result:

| sample | tied x late vs down-1 | 95% CI | p |
|---|---|---|---|
| regular season (main) | -5.6% | [-8.1, -3.0] | <0.001 |
| playoffs ("placebo") | **-13.2%** | [-21.2, -4.3] | <0.001 |
| second period (placebo) | +1.5% | [-1.1, +4.2] | 0.27 |

The second-period placebo -- where nothing can be banked from any state --
is a clean null, exactly as predicted. The playoff sample is not: tied
playoff teams pull back *more* than in the regular season.

## Why this is coherent, not a refutation of turtling

The prediction was written for the pooled tied-vs-one-goal design. Under
the three-state design the relevant question is what a tied team's
*reaching overtime* is worth relative to conceding in regulation:

- Regular season: reaching OT banks 1 point plus roughly a coin-flip for
  a second -- worth ~1.5 points against 0 for a regulation concession.
- Playoffs: reaching OT preserves ~50% of the win in a sudden-death
  continuation -- against 0% after a regulation concession, in a game
  that may end a season.

The playoff OT option is *more* valuable, not less, and playoff down-1
teams late (often facing elimination) are maximally desperate -- widening
the differential from both sides. Tied-late conservatism scaling WITH the
value of reaching overtime is exactly what an incentive story predicts.

## What it changes about identification

It removes one arrow from the quiver honestly: the playoff comparison
cannot isolate the *loser point* specifically -- it shows tied-late
conservatism tracks the generic option value of reaching OT, of which the
loser point is one instance. The decisive test for the loser point itself
is therefore the regime evidence:

1. the pre/post-2005 difference-in-differences (Phase 4), where the same
   regular-season tied state changes value across rule regimes, and
2. the 2010-11 ROW-tiebreaker natural experiment.

The methodology and README must present the playoff row as a *mechanism
consistency check* (conservatism scales with OT option value), not as the
falsification test originally envisioned. Pretending otherwise would be
exactly the kind of overclaiming this project exists to avoid.
