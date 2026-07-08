# Bugs found during the build

One entry per bug encountered and fixed, in the order discovered. Each entry
states the cause, the fix, and where the regression test lives.

## 1. Stale interpreter path in `.venv` (Phase 0)

**Cause:** the virtualenv was originally created while the repo lived at
`/Users/davidgold/loser-point`; after the repo moved to
`/Users/davidgold/Documents/loser-point`, every shebang line in `.venv/bin/*`
(including `pytest`) still pointed at the old, now-nonexistent path. Running
`uv run pytest` did not error outright — it silently fell back to the
system/Anaconda Python on `PATH`, which lacked `pytest-cov`, producing a
confusing `unrecognized arguments: --cov=...` error that looked like a
missing dependency rather than a broken venv.

**Fix:** `rm -rf .venv && uv sync --extra dev` to rebuild the venv at the
correct path. No code change; not unit-testable, but documented here so a
future "coverage flag not recognized" error is diagnosed in seconds instead
of chased as a dependency problem.

## 2. Coverage gate failing on Phase 0 scaffold

**Cause:** `pyproject.toml` enforces `fail_under = 90` globally, but
`utils/io.py` and `utils/logging.py` had no tests yet, so total coverage sat
at 66%. `make test` — the Phase 0 exit criterion — did not pass.

**Fix:** added `tests/unit/test_io.py` (parquet round-trip, missing-file
error, schema-violation rejection) and `tests/unit/test_logging.py`
(logger identity, idempotent root-handler configuration), bringing coverage
to 96.67%.

## 3. Real MoneyPuck data has physically impossible skater counts (Phase 1)

**Cause:** `RAW_SHOTS_SCHEMA` bounded `homeSkatersOnIce`/`awaySkatersOnIce`
to [0, 6] (the true physical maximum). The very first real end-to-end run
against live MoneyPuck data (seasons 2007, 2013, 2025) failed validation:
a handful of rows record 7-8 skaters for one team. Checked across all three
eras -- persistent at a rate of 1-3 rows per ~110,000 (<0.003%) in every one,
so a genuine (if tiny) upstream data-entry glitch, not a fluke or a bug in
this project's range assumption.

**Fix:** added `_drop_impossible_skater_count_rows()` in
`ingest/moneypuck.py`, called before schema validation, which drops the
offending rows and logs a `WARNING` naming the exact `shotID`s dropped.
Chosen over loosening the schema bound (would mean accepting rows proven
physically impossible) or failing the whole season (disproportionate over
1-3 rows out of 110,000). See
`docs/decisions/0004-impossible-skater-counts.md` for the full option
analysis. Regression test:
`test_moneypuck_ingest.py::test_drops_impossible_skater_count_rows_with_warning`.

## 4. `shotID` is not season-wide unique (Phase 1)

**Cause:** `RAW_SHOTS_SCHEMA` originally enforced `Column(int, unique=True)`
on `shotID`, following the upstream dictionary's description of it as "a
unique id for each shot." Continuing the same real end-to-end run (after
fixing bug #3), the 2025 season failed validation with 244 duplicate
`shotID` values. Inspection showed `shotID` is actually a per-game
sequential counter that restarts at 0 for every `game_id` -- not a
season-wide id at all.

**Fix:** changed the schema's uniqueness constraint from the single column
`shotID` to the composite pair `unique=["game_id", "shotID"]`, which is the
table's true primary key. Updated `docs/data_dictionaries/moneypuck_shots_raw.md`
and `docs/decisions/0003-moneypuck-data-quirks.md` to describe this
correctly. Regression tests:
`test_schemas.py::test_duplicate_game_id_shot_id_pair_fails` and
`test_schemas.py::test_shot_id_repeating_across_different_games_is_valid`.

## 5. `hard_failure_fraction` denominator counted issues, not games sampled (Phase 1)

**Cause:** after fixing bugs #3 and #4, the first clean end-to-end run
against real 2007/2013/2025 data reported implausible 66-86% "internal
consistency failure rates" -- clearly a bug, not real data quality (a
widely-used public dataset would not be 85% internally inconsistent).
`check_game_goal_counts` appended one `WARNING` issue per failing game, plus
a single trailing `INFO` summary issue for the whole season. `hard_failure_fraction`
computed `bad / len(game_level_issues)`, but `len(game_level_issues)` was
`(number of warnings) + 1` (the summary line) -- not the actual sample size
of 200 games. So a season with 6 real warnings out of 200 games sampled
computed `6 / 7 = 85.7%` instead of the correct `6 / 200 = 3%`.

**Fix:** `check_game_goal_counts` now returns `(issues, n_sampled, n_failed)`
explicitly instead of encoding the sample size inside a message string that
had to be inferred later. `reconcile_season` returns a new `SeasonReconciliation`
dataclass carrying `n_games_sampled` / `n_games_failed` directly, and
`failure_fraction` is a property on that dataclass -- there is no longer any
code path that has to reconstruct a sample size from a list of issues.
Regression tests: `test_checks.py::test_season_reconciliation_failure_fraction`
and `test_checks.py::test_reconcile_season_combines_both_checks_and_tracks_counts`.

## 6. Two more real data quirks found after fixing bug #5 (Phase 1)

**Cause:** with the fraction bug fixed, the real 2007/2013/2025 run still
showed a ~3% (2007) and ~2.5% (2013) failure rate -- still implausibly high
for a claimed "internal consistency" check. Inspecting individual failing
games found two distinct, real causes:

1. **Wholesale duplicated game blocks.** `game_id` 20004 (2007) has 158 shot
   rows for what should be a ~79-play game; the first and second halves
   (split by `shotID`) are element-wise identical. Scanning found 16 such
   games, all contiguous at the very start of the 2007 file (`game_id`
   20001-20016) -- a one-time backfill artifact in MoneyPuck's oldest
   season. Not present in 2013 or 2025.
2. **"Phantom" goals.** 2013 game 20451's `awayTeamGoals` jumps from 2 to 3
   on a row that is itself a plain `SHOT`, with no `GOAL` row anywhere
   nearby causing it. The running score is correct; the goal simply has no
   shot-event row of its own in MoneyPuck's data.

**Fix:** added `_drop_duplicated_game_blocks()` to `ingest/moneypuck.py`
(runs on every season, not just 2007, so it self-corrects if the same
artifact exists in an undownloaded season), and removed the "final tally
must equal counted GOAL rows" branch of `check_game_goal_counts` entirely --
monotonicity of the running score is the only invariant `score_state.py`
actually needs, and it's the only one real data reliably satisfies. Full
analysis in `docs/decisions/0005-duplicated-game-blocks.md` and the
"phantom goals" section of `docs/decisions/0003-moneypuck-data-quirks.md`.
Regression tests: `test_moneypuck_ingest.py::test_drops_duplicated_game_block_with_warning`,
`test_moneypuck_ingest.py::test_even_row_count_game_with_distinct_halves_is_not_flagged`,
`test_checks.py::test_check_game_goal_counts_does_not_flag_phantom_goals`.

## 7. NHL game_ids restart every season -- the panel key is (season, game_id) (Phase 2)

**Cause:** `PANEL_MINUTES_SCHEMA` enforced uniqueness on
`(game_id, is_home, minute)`, and `check_panel_invariants` grouped by
`game_id` alone. Both worked when building one season at a time, but the
first multi-season concatenation (2007 + 2013 + 2025) failed schema
validation: NHL game_id 20001 exists in *every* season -- game ids restart
each year. Had the schema not caught it, any multi-season groupby keyed on
`game_id` alone would have silently merged rows from different seasons'
games (and the invariant checker itself had the same latent bug: it would
have counted 360 rows for "game 20001" and raised a misleading error).

**Fix:** every game-level key in the panel layer is now
`(season, game_id)`: the schema uniqueness constraints on both panel
tables, the build loop's groupby, and all five groupby/pivot operations in
`check_panel_invariants`. Documented in the panel data dictionary so
Phase 3's joins (standings, Elo) key correctly from the start. Regression
test: `test_build_panel.py::test_same_game_id_in_different_seasons_stays_separate`.

## 8. Headline gap had the wrong sign — the 5v5 control group collapses at minutes 59-60 (Phase 2)

**Cause:** the first draft of `analysis/descriptive.py::headline_gap`
averaged the one-goal comparison series over minutes 56-60. But under the
primary 5v5 filter, one-goal minutes 59-60 are 50%/18% covered (goalie
pulls make them 6v5), and the surviving cells are mostly zero-shot minutes
(mean 0.11 attempts vs 0.55 at minute 58). The "control" collapsed toward
zero and the computed gap came out **+27.7%** — tied teams appearing to
shoot *more* — a pure selection artifact with the wrong sign. Caught by
inspecting per-minute n's and coverage before publishing the figure.

**Fix:** all descriptive windows involving a one-goal state end at minute
58; the figure truncates the one-goal series there with a footnote; the
headline contrasts are now the within-tied late drop (clean through minute
60) and the tied vs down-1 / up-1 ordering over minutes 56-58. Full
analysis in `docs/decisions/0008-late-window-control-selection.md`.
Regression test:
`test_descriptive.py::test_headline_windows_exclude_contaminated_minutes`.
