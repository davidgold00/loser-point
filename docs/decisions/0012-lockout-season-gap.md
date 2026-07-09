# 0012 — The 2004-05 season is a real, expected gap (NHL lockout)

**Status:** Found by the scraper's own error handling on the very first
real multi-season run — it correctly refused to silently proceed on an
unexplained empty page, which is exactly what surfaced this.

## What happened

`season=2004` in this project's labeling (the season starting in 2004)
maps to `NHL_2005_games.html`. That page has no `<table id="games">` at
all. Direct inspection found Hockey-Reference's own explanation on the
page:

> **Note**: This season was cancelled due to NHL lockout.

The entire 2004-05 NHL season was cancelled by the league's labor
dispute -- zero games were played. This is real hockey history, not a
scraping bug, and the schedule page correctly reflects that by omitting
the games table entirely rather than showing an empty one.

## Why this matters for the regime split

The pre-regime bucket (`historical_start=1999` through
`historical_post_start_season - 1 = 2004`) therefore contributes real
games from only 5 seasons (1999-2003), not 6 -- season 2004 exists in the
loop range but yields zero rows. This is harmless for the DiD (Poisson
estimation handles an unbalanced panel fine), but it's disclosed in
`docs/methodology.md`'s sample description so the season count isn't
silently overstated.

## The fix

`parse_schedule` checks for Hockey-Reference's own cancellation text
before deciding whether a missing games table is expected or a real bug:
if present, it logs a `WARNING` and returns an empty (correctly-shaped)
DataFrame; if absent, it still raises `HockeyReferenceError` loudly, since
an unexplained missing table on any other season *is* a bug (a changed
page layout, a fetch that returned an error page, etc.) and must not be
swallowed. `ingest/hockey_reference.py::main` iterates all configured
seasons regardless, so 2004 simply contributes nothing without halting
the scrape of the surrounding seasons.

Regression test:
`tests/unit/test_hockey_reference.py::test_parse_schedule_handles_cancelled_lockout_season`.
