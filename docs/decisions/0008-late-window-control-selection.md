# 0008 — The 5v5 control group collapses in minutes 59-60, and the pooled "one-goal" group hides the real contrast

**Status:** Found while producing the Phase 2 go/no-go descriptive figure,
by inspecting the numbers before publishing them.

## Artifact 1: goalie pulls destroy the one-goal 5v5 sample late

Under the primary 5v5 specification (decision 0006 rule 5), a game-minute
is excluded when any shot in it was taken at non-5v5 strength. In one-goal
games, the trailing team pulls its goalie in the final ~90 seconds, making
those minutes 6v5. Measured 5v5 coverage of one-goal game-minutes:

| minute | 56 | 57 | 58 | 59 | 60 |
|---|---|---|---|---|---|
| one-goal coverage | 87% | 87% | 81% | **50%** | **18%** |
| tied coverage | 88% | 88% | 89% | 89% | 86% |

The 18% of one-goal minute-60 cells that survive are mostly zero-shot
minutes (mean attempts 0.11 vs 0.55 at minute 58) — pure selection, not
behavior. **Consequence:** the one-goal comparison series is only valid
through minute 58; the figure truncates it there and says so. The tied
series is clean through minute 60 (nobody pulls a goalie in a tied game).

This artifact produced a wrong-signed headline number in the first draft
of `headline_gap` (logged as bugs_found.md #8): averaging one-goal means
over minutes 56-60 dragged the control down to 0.4-ish, making tied teams
look 28% *more* active. All headline windows now end at minute 58 when a
one-goal state is involved.

## Artifact 2: "one-goal games" pools two opposite behaviors

The pooled one-goal group averages two states with opposing late-game
incentives, and they nearly cancel (attempts, minutes 41-55 vs 56-58,
three-season sample; the window starts at 41 because minute 40 is the
last minute of the *second* period and minute 41 carries a period-opening
dip -- the plotted window is exactly the third period):

| state entering the minute | mid third | late | change |
|---|---|---|---|
| down 1 (nothing banked, EV of status quo = 0 pts) | 0.663 | 0.654 | **-1.4%** |
| tied (OT point floor within reach) | 0.597 | 0.556 | **-6.8%** |
| up 1 (protecting 2 points) | 0.537 | 0.440 | **-18.0%** |

The xG versions show the same ordering (roughly -1% / -7% / -15%).

**The descriptive story is the ordering itself.** A tied team's marginal
value of the next goal is as high as a down-1 team's — under a
win-is-everything system they should behave alike. Instead tied teams sit
much closer to lead-protectors. The natural reading: they *are* protecting
something — the guaranteed point that reaching overtime banks for both
teams. (The regime DiD in Phase 4 is what tests this causally against the
pre-2005 world; the descriptive figure only needs to display the pattern
honestly.)

**Consequence for the figure:** the headline chart shows three lines
(tied in the accent hue; down-1 and up-1 as gray context), not the pooled
two-line version, with one-goal lines ending at minute 58 per artifact 1.

## Supporting descriptive facts (3-season sample, re-estimated on all
seasons in Phase 3)

- Tied-game total scoring drops 10.8% in the final five minutes vs the
  mid-third-period tied rate.
- 73.9% of games tied entering minute 56 reach overtime (801 such games);
  holding the mid-game tied scoring rate, ~67% would.
