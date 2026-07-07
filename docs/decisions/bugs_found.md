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
