# 0014 — Pre-registered heterogeneity predictions (Phase 5)

**Status:** Written and committed BEFORE any heterogeneity model was
estimated, per docs/methodology.md item 6. The predictions below are
falsifiable and will be reported as-is regardless of which way the
estimates come out (the same discipline that produced decisions 0010 and
0013).

## Design common to all three hypotheses

Each hypothesis is one triple-interaction FE-Poisson model on the modern
5v5 shot-attempt panel — the main Phase 3 specification
(`attempts_main`, minutes 41-58, late = 56-58, down-1 reference,
`is_home + rest_diff + elo_diff_100` controls, team/opponent/season fixed
effects, SEs clustered by game) with one extra binary dimension `D` and
its full set of interaction dummies, built as explicit products exactly
like `analysis/row_experiment.py`:

```
attempts ~ state + late + D + state x late + state x D + late x D
           + state x late x D + controls | team + opp + season
```

The coefficient of interest is `tied x late x D` — how much *more* (or
less) tied teams cut late-game offense when `D = 1`. Three hypotheses
means three models; all three are reported with no selective emphasis,
and each is reported with its MDE so a null is distinguishable from an
uninformative estimate.

## H1 — Playoff-race proximity (primary hypothesis)

**D = 1 ("race game")** when BOTH teams are within 6 points of their
playoff cutline in the pre-game standings, among games in the second half
of each season's schedule (game date >= that season's median
regular-season game date — schedule-based, so the 2012-13 lockout and
COVID seasons split correctly).

*Cutline definition (approximation, fixed in advance):* the 8th-highest
point total in the team's conference on that date; for 2020-21 (no
conferences) the 4th-highest in the team's division. This approximates
the wildcard-era qualification rule (top 3 per division + 2 wildcards)
by conference rank; the difference is rare and unrelated to the estimand.
Pre-game standings = league standings as of the day before the game.

**Prediction: `tied x late x race` < 0** (suppression is *stronger* in
race games). The marginal standings value of a banked point is highest
for bubble teams; teams far out of the race (or comfortably in) gain
little from a guaranteed loser point.

## H2 — Intra-division games

**D = 1** when both teams belong to the same division in that season's
real alignment (taken from the NHL API standings, not hardcoded — the
2013 realignment, Vegas/Seattle expansion, and the 2020-21 temporary
divisions are all reflected automatically).

**Prediction: `tied x late x intra_division` > 0** (suppression is
*weaker* intra-division). Reaching overtime hands the opponent a
guaranteed point; against a same-division rival that point damages your
own seeding race directly, so the tacit point-splitting bargain is less
attractive. Registered honestly: the opposing mechanism (both bubble
teams still prefer 1 point to a coin-flip on 0) predicts no difference
or the opposite sign, and the older literature on post-1999 tie rates
suggests rivalry games went to overtime *more*, not less. If the
estimate comes out negative, that is evidence the direct-rival
externality does not discipline the behavior — worth reporting, not
hiding.

## H3 — Evenly matched games

**D = 1** when the game's pre-game Elo gap `|elo_diff_100|` is at or
below the estimation sample's median gap.

**Prediction: `tied x late x even` < 0** (suppression is *stronger* in
even games). Turtling to overtime is tacit cooperation; it is most
attractive when pressing buys the least win probability — an even game.
A heavy favorite tied late still expects to win in regulation by
playing, so it should keep playing.

## What is NOT registered

No subgroup fishing beyond these three models; no post-hoc threshold
tuning (the 6-point bubble and the median Elo split are fixed here,
before estimation). If a threshold turns out to produce a degenerate
sample (e.g. almost no race games), the fix is documented in a follow-up
decision, not silently swapped.
