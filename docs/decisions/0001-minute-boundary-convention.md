# ADR 0001: Minute-boundary convention for the score-state panel

**Status:** decided (Phase 0)

## Decision

A game-minute `N` (1-60) covers game-clock seconds `(60*(N-1), 60*N]` —
i.e. half-open on the left, closed on the right. A goal scored at exactly
54:00.0 belongs to minute 54, not 55; a goal at 54:00.1 belongs to minute 55.

Configured as `panel.minute_boundary_convention: half_open_right` in
`config/config.yaml`.

## Why

Off-by-one errors at minute boundaries are the single biggest correctness
risk in this project (see the project brief). Picking one explicit,
documented, tested convention — rather than leaving it implicit in code —
means any future refactor that changes this behavior will fail the golden
game tests and the boundary-goal fixture in `tests/fixtures/`.

## Consequences

- `score_state.py` must implement this exact rule and its docstring must
  restate it.
- `tests/fixtures/` includes a dedicated "goal at exact minute boundary"
  fixture asserting the goal lands in the pre-boundary minute.
- The data dictionary entry for the panel's `minute` column must restate
  this convention so a future reader of the parquet file alone (without
  the code) still interprets it correctly.
