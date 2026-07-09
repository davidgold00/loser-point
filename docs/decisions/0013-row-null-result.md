# 0013 — The ROW-tiebreaker natural experiment is a clean, informative null

**Status:** Result from the real 19-season modern panel (2007-08 through
2025-26), documented before writing the methodology results section.

## The result

`state x late x post_row` triple interaction, 394,918 team-minutes,
split at the 2010-11 season (when regulation+OT wins became the first
standings tiebreaker):

| interaction | estimate | 95% CI | p | MDE |
|---|---|---|---|---|
| tied x late x post-ROW | +0.7% | [-6.5, +8.3] | 0.86 | ~11% |
| up-1 x late x post-ROW | -2.4% | [-11.2, +7.2] | 0.61 | ~15% |

Both are tightly centered on zero, and the minimum detectable effect
(~11% for tied) is informative, not just "underpowered": the design could
have detected a change of that size or larger and did not find one. This
is a real null, not an inconclusive one.

## Why a null here is coherent, not a problem for the thesis

ROW changes a **standings tiebreaker** -- it only matters if two teams
finish the season level on points, and even then only decides playoff
seeding between them. It does not change the point payoff of the
individual game being played: reaching overtime still banks exactly 1
point (plus a coin-flip for a 2nd) for both teams in that game, regardless
of ROW. A team turtling to overtime tonight gets the same 1 guaranteed
point whether ROW exists or not; ROW only affects how that game's result
compares to other teams' at the very end of the season.

A rational-actor account of turtling therefore predicts exactly this
null: ROW is a real repair of the *standings-fairness* problem the
original prompt's counterargument raises (a shootout win looking equal to
a regulation win) but it is not a repair of the *in-game incentive* that
causes the late-game behavioral distortion in the first place. The two
problems are related but distinct, and this experiment cleanly separates
them.

## What this means for the memo

The counterfactual/policy section should present ROW's effect honestly:
it improved standings integrity (a regulation win now counts for more in
the tiebreaker), but it did not, and mechanically could not, have been
expected to reduce the turtling behavior itself. Any policy fix aimed at
the in-game distortion needs to change the *game's own* point payoff (e.g.
3-2-1-0), not a season-end tiebreaker -- exactly the counterfactual this
project already builds in Phase 5.
