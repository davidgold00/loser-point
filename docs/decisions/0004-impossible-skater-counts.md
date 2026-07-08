# 0004 — Dropping physically impossible skater-count rows

**Status:** Found by the schema validator itself, on the first real
end-to-end ingest run against live MoneyPuck data (2007, 2013, 2025 seasons).

## The problem

`RAW_SHOTS_SCHEMA` bounds `homeSkatersOnIce`/`awaySkatersOnIce` to [0, 6] --
6 is the true physical maximum (5 skaters, plus a 6th during a delayed
penalty when the non-offending team pulls its goalie for an extra attacker).
Running the real ingest pipeline against live data immediately failed
validation:

```
Column 'homeSkatersOnIce' failed element-wise validator: in_range(0, 6)
Column 'awaySkatersOnIce' failed element-wise validator: in_range(0, 6)
```

Direct inspection found the cause: a handful of shot rows record 7 or 8
skaters for one team, which is not a possible NHL game state. Checked across
three eras to see whether this was a one-off:

| Season | Bad rows | Total rows | Rate |
|---|---|---|---|
| 2007 | 3 | 106,243 | 0.0028% |
| 2013 | 1 | 110,682 | 0.0009% |
| 2025 | 1 | 119,271 | 0.0008% |

Persistent, tiny, and present in every era sampled -- a genuine (if minor)
MoneyPuck data-entry glitch, not a fluke in one file or a bug in this
project's range assumption.

## Options considered

1. **Loosen the schema bound to admit 7-8.** Rejected -- it would mean
   accepting rows the schema itself proves are physically impossible,
   defeating the point of validating this column at all.
2. **Let the whole season fail hard.** Rejected -- a season is ~110,000
   rows; halting an entire season's ingest over 1-3 corrupted rows is a
   disproportionate failure mode, and this project's own philosophy is to
   fail loudly on real problems, not to be fragile over noise.
3. **Drop just the offending rows, loudly.** Chosen. `ingest_season` now
   calls `_drop_impossible_skater_count_rows()` before schema validation,
   which logs a `WARNING` naming the exact `shotID`s dropped and why, then
   proceeds with the rest of the season intact.

## Consequence

At <0.003% of any season's shots, this has no realistic effect on any of
the project's descriptive or model results. It is logged, not silent: every
pipeline run's log (and by extension anyone re-running `make data`) will
see exactly which rows were dropped and can go verify them against
MoneyPuck's own data if they want a second opinion.

Regression test: `tests/unit/test_moneypuck_ingest.py::test_drops_impossible_skater_count_rows_with_warning`.
