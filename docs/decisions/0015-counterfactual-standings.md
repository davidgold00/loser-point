# 0015 — Counterfactual standings design, and the Rule 84.2 forfeiture

**Status:** Decided during Phase 5; the validation result and the
Minnesota finding below are from the real 2007-2025 panel.

## What the counterfactual is (and is not)

`analysis/counterfactual.py` holds every real game outcome fixed and
re-scores the season under alternative point systems:

* `actual` — 2 any win / 1 OT-SO loss / 0 regulation loss
* `three_two_one` — 3 regulation win / 2 OT-SO win / 1 OT-SO loss / 0
* `no_loser_point` — 2 any win / 0 any loss

This is the *mechanical* half of the policy question only. The project's
own behavioral estimates say teams respond to the point schedule, so if
the schedule changed, outcomes would too (fewer games would reach
overtime in the first place). The mechanical deltas are therefore a
lower bound on disruption, reported with the Lucas-critique caveat
(docs/methodology.md item 10).

## Inputs: API game results and API alignment, not MoneyPuck

Outcomes come from `data/interim/nhl_api/game_results.parquet` — it
shares the standings' team-abbreviation space and is the cross-source
ground truth. Conference/division alignment comes from the real
season-end standings responses, so the 2013 realignment, Vegas/Seattle
expansion, Atlanta-to-Winnipeg, Arizona-to-Utah, and the 2020-21
temporary divisions are handled by data rather than hardcoded history.
Season formats come from the NHL season manifest's own flags
(`wildcardInUse`, `conferencesInUse`), verified era by era.

## The validation gate

Before any counterfactual number is produced, the module recomputes the
**actual** standings from per-game results and compares points, wins,
regulation+OT wins, goal differential, and games played against the
official API season-end standings for every team-season. The run aborts
on any mismatch. On the real panel this now passes exactly: **584 of 584
team-seasons reproduce the official standings on all five figures.**

## The gate caught a real one: NHL Rule 84.2

The first real run failed on exactly one figure out of ~2,900: 2023-24
Minnesota, computed 88 points vs official 87. Tracing MIN's ten OT/SO
losses through day-over-day official standings found the game:
**2024-03-30, VGK at MIN — Minnesota earned zero points for an overtime
loss.** The gamecenter record confirms Jonathan Marchessault's OT winner
was an empty-net goal with Minnesota's net vacant (situation code 1340):
Minnesota, in a playoff race where one point was nearly worthless,
pulled its goalie in 3-on-3 overtime for an extra attacker, lost, and
forfeited the loser point under NHL Rule 84.2.

This is kept as a documented outcome-level exception
(`OT_LOSER_POINT_FORFEITURES`), not a code path inferred from shot data
— the rule has bitten exactly once in 22,842 games. It is also a
finding in its own right: a team's revealed preference that the second
point can be worth gambling the guaranteed one, i.e. the loser-point
incentive surfacing as a standings anomaly.

## Tiebreak approximation

Counterfactual ranks use a fixed cascade: points, then regulation+OT
wins, then total wins, then goal differential, then team code. The NHL's
real cascades are era-specific and end in head-to-head records, which
cannot be recomputed sensibly under a different point system anyway.
The approximation only matters when two teams finish level on
counterfactual points at the cutline; berth-flip counts should be read
with that granularity in mind.

## 2019-20 is excluded from berth flips

The COVID-halted season ended with unequal games played and a 24-team
play-in seeded by points percentage — there is no 16-team cutline to
flip. Points deltas are still reported for it; `berth_flips` is NaN.

## Headline mechanical results (real panel, 18 evaluable seasons)

* `three_two_one`: 8 berth flips total (~0.4 per season); mean absolute
  points change ~31 (mostly inflation — every regulation win is worth
  one more point).
* `no_loser_point`: 15 berth flips total (~0.8 per season); mean
  absolute points change ~9.
* The full per-season table is `data/processed/counterfactual_summary.parquet`.
