# 0007 — Dropping internally inconsistent games at panel build time

**Status:** Found by `score_state.extract_goal_events`'s own defensive
check, on the first full-season panel build against real 2007 data.

## The problem

2007 regular-season game 20274 (T.B vs WSH) fails goal-timeline
reconstruction: shotIDs 22867 and 22868 are *the same goal recorded twice*
(identical time 3576, period 3, home team, and — the giveaway — identical
score-before of 4-2, which is impossible for two real consecutive goals by
the same team). The walk sees the first GOAL row, advances the tally to
5-2, then meets the second row still claiming 4-2 — a decrease, which
raises `InconsistentGameError`.

Worse, the game's `homeTeamWon` flag is 0 while its own recorded final
score is a home win (5-2, or 4-2 if the duplicate is discounted) — the
game's data contradicts itself twice over, so there is no self-consistent
repair available from this file alone.

Scanning all three ingested seasons for recorded-score decreases (after
ingest cleaning): 2007 has exactly this one game; 2013 and 2025 have zero.

## Why the sampled reconciliation missed it

`validate/checks.py` checks score monotonicity on a random sample of 200
games per season (~15% of a season); game 20274 wasn't drawn. The panel
builder walks *every* game by construction, so it is the natural enforcing
layer; the ingest check remains a cheap early-warning.

## Options considered

1. **Repair by dropping the duplicated GOAL row.** Rejected: the
   contradictory `homeTeamWon` flag means the corruption isn't limited to
   one duplicated row; any repair would be a guess without external ground
   truth. (Phase 3's NHL API client will have the true final score — the
   game can be revisited then if one game in ~1,300 ever matters.)
2. **Fail the whole season's build.** Rejected: disproportionate for one
   provably corrupt game, and the project already has the drop-loudly
   pattern (decisions 0004, 0005) for exactly this situation.
3. **Drop the game from the panel, loudly.** Chosen. `build_panel` catches
   `InconsistentGameError`, logs a WARNING naming the game and reason, and
   reports the drop count in its completion log line.

Regression test:
`tests/unit/test_build_panel.py::test_corrupt_game_is_dropped_with_warning`.

## Postscript (Phase 3 backfill)

The full 19-season backfill surfaced two more games with the same
duplicated-goal-row signature, both dropped by the same code path with
the same logged warning: 2012 game 20288 and 2018 game 20670. Three
corrupt games in 24,536 (~0.01%) — the drop-loudly policy generalized
correctly beyond the game it was written for.
