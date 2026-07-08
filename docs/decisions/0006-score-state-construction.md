# 0006 — Score-state panel construction: the load-bearing conventions

**Status:** Decided before implementation (Phase 2), test-first. Every rule
here has a corresponding unit test in `tests/unit/test_score_state.py`; the
minute-boundary rules are additionally locked by hand-verified real games in
`tests/golden/`.

## 1. Minute boundary convention (restates and extends decision 0001)

Minute `N` covers game seconds `(60*(N-1), 60*N]` — half-open on the left,
closed on the right. A goal at exactly 54:00.0 (3240s) belongs to minute 54,
not 55. Implementation: `minute = ceil(time / 60)`.

**The t=0 special case:** real MoneyPuck data contains shots at `time == 0`
(the opening second). `ceil(0/60) = 0`, which is not a valid minute, so
`minute_of_time` clamps to 1: `minute = max(1, ceil(time / 60))`. Minute 1
is therefore effectively `[0, 60]` — closed on both ends — while every other
minute is `(60*(N-1), 60*N]`. This is the only asymmetry, it is tested, and
it can never affect the analysis (no score-state question hinges on second
zero).

**Regulation cutoff:** a row is regulation iff `period <= 3` and
`time <= 3600`. Both conditions are required: `time <= 3600` alone would
misclassify a hypothetical period-4 row stamped exactly 3600 (the OT start
boundary), and `period <= 3` alone would admit corrupted rows with
`period <= 3` but `time > 3600` (none observed; the panel schema also bounds
this).

## 2. Score state *entering* a minute

The state entering minute `N` is computed from all goals with
`time <= 60*(N-1)`. Consistency check with rule 1: a goal at exactly 3240s
(minute 54) is counted in the state entering minute 55 — the goal happened
*in* minute 54, so minute 54's own entering state does not include it, and
minute 55's does. A goal at 54:31 (3271s, minute 55) changes the state
entering minute 56 onward.

States, from the shooting team's perspective, binned exactly as in
`config.yaml`: `down_2_plus` (diff <= -2), `down_1`, `tied`, `up_1`,
`up_2_plus` (diff >= +2). Every game's minute 1 is entered `tied` by
construction.

## 3. Goal timeline reconstruction: running score is ground truth

Per decision 0003, MoneyPuck's running score columns
(`homeTeamGoals`/`awayTeamGoals` = score *before* each shot) are the ground
truth, and a small number of real goals ("phantom goals") increment the
running score without any `GOAL`-tagged row of their own. The goal timeline
for a game is therefore reconstructed as:

1. Sort the game's rows by `shotID` (chronological within a game).
2. Walk the rows maintaining a running tally. A `GOAL` row adds a goal at
   exactly its `time`.
3. If a row's recorded score-before exceeds the tally, the difference is
   emitted as phantom goal(s) **timestamped at that row's `time`**.
4. If a row's recorded score-before is ever *below* the tally, the game's
   data is internally inconsistent and the game is rejected (this cannot
   happen for games that passed ingest reconciliation, but the module
   defends itself anyway rather than trusting its caller).

**Why phantom goals get the observing row's timestamp:** the true goal time
is only known to lie in the interval between the previous row and the
observing row (the score "before" the observing shot already includes it).
Using the observing row's time is the latest possible moment, so the error
is bounded by the gap between consecutive shots (typically well under a
minute) and applies only to phantom goals, which are rare (order of a few
per season). The alternative — the interval midpoint — pretends to
precision the data doesn't have; a deterministic, documented upper bound is
easier to defend and to test.

**Known blind spot:** a phantom goal occurring *after* a game's final shot
row can never be observed in shot data at all. Its effect on the panel would
be a missing late state transition in that one game. Phase 3's cross-source
reconciliation (reconstructed final scores vs. the NHL API schedule) will
quantify exactly how many games are affected; expected to be a handful
across 19 seasons.

## 4. Outcome definitions (game level, not panel rows)

- **Reached overtime:** regulation-end score is tied (computed from the
  reconstructed goal timeline at `time <= 3600`, periods 1-3). This is
  definitionally exact — a game reaches OT iff regulation ends tied.
- **Decided by shootout:** regular-season game whose *entire recorded goal
  timeline* (including OT) ends tied, yet `homeTeamWon` names a winner. Per
  decision 0003, shootout goals leave no shot rows, so this is the only
  reliable detection. Playoff games can never be shootout games.
- **Playoff games** are built into the panel and flagged (`is_playoff`),
  not dropped: the main analysis excludes them, but the no-loser-point
  placebo test in `robustness.py` needs them.

## 5. Situation (5v5) filtering: shots are filtered, minutes are flagged

Attempt/xG counts in the primary columns include only shots taken at 5v5
(`homeSkatersOnIce == 5 and awaySkatersOnIce == 5`). Additionally each
game-minute gets a `non_5v5_flag`: true if *any* shot by either team within
that minute was taken at non-5v5 strength. The primary analysis excludes
flagged minutes.

**Zero-shot minutes are always retained.** A minute with no shots has
unknown strength, and dropping it would be a catastrophic selection bias
for this specific project: the outcome of interest is *low* shot intensity,
so discarding shotless minutes would delete exactly the behavior being
measured. The cost is that a fully-penalized minute with zero shots ever
taken slips into the 5v5 panel as a zero — rare (power plays generate shots
at roughly double the 5v5 rate) and symmetric across tied/one-goal groups,
so it attenuates rather than manufactures the contrast. A penalty-clock
carry-forward refinement was considered and rejected: penalties can end
early on PP goals, making clock-based inference wrong in exactly the games
with the most late-game action, and the added complexity buys little given
zero-shot PP minutes are already rare.

## 6. Empty-net handling: computed as parallel columns, not rebuilds

The three config modes do not require three panel builds. The panel carries
four attempt/xG column pairs — {5v5, all-strength} x {EN-policy-a applied,
naive} — so every robustness cut is a column selection:

- Mode (a), the default: use the `_main` columns (5v5, EN-excluded). A shot
  is EN-excluded if it was taken **on** an empty net (`shotOnEmptyNet == 1`)
  or **by a team whose own goalie is pulled** (shooter's own net empty).
- Mode (b): same columns, additionally drop minutes 59-60 at analysis time
  (a row filter, not a panel property).
- Mode (c), naive: use the `_naive` columns.
