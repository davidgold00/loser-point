# 0005 — Dropping wholesale duplicated game blocks

**Status:** Found via the reconciliation report itself, on the same
end-to-end run as decision 0004, after fixing the impossible-skater-count
rows. The corrected reconciliation still showed an implausible ~3% failure
rate for `game_goal_counts` on the 2007 season.

## The problem

Inspecting one failing game (`game_id` 20004, 2007 season) directly: it has
158 shot rows, but the game only has 79 distinct plays. The first 79 rows
(shotID 227-305) and the last 79 rows (shotID 1518-1596) are element-wise
identical on period, time, team, event, and running score -- the entire
game's shot sequence is duplicated wholesale within the file, under the
same `game_id`, with a disjoint `shotID` range for the second copy.

Scanning the full 2007 file for this exact pattern (split each game's rows
in half by `shotID` order; check if the two halves are identical) found 16
affected games, all contiguous at the very start of the season:
`game_id` 20001 through 20016. No such pattern was found scanning the 2013
or 2025 files under the same method -- this appears to be a one-time
artifact from how MoneyPuck originally backfilled their oldest season, not
an ongoing issue.

## Why this matters

Left uncorrected, every shot-attempt count, xG sum, and goal count for
these 16 games would be exactly doubled in any analysis that doesn't
explicitly deduplicate -- a silent 2x inflation that would not be obvious
from aggregate season totals (16 games out of ~1,230 is a small enough
share that season-level sums would look only slightly off, not obviously
broken).

## The fix

`_drop_duplicated_game_blocks()` in `ingest/moneypuck.py` runs on every
ingested season (not just 2007): for each `game_id` with an even row count,
it splits the rows in half by `shotID` order and compares the two halves on
`period`, `time`, `isHomeTeam`, `event`, `goal`, `homeTeamGoals`, and
`awayTeamGoals`. If they're identical, the second half is dropped and a
`WARNING` names the exact game and shotID ranges involved. Genuinely long
games (e.g. multi-overtime playoff games, which can have 150+ rows) are not
falsely flagged, because there's no reason their first and second halves by
row-order would be identical -- confirmed by running the same detector
against 2013 game 30415 and 2025 game 30132 (both legitimately long
multi-OT playoff games), neither of which triggered a false positive.

This check runs unconditionally on every season, not just 2007, so if this
same artifact exists in an as-yet-undownloaded season (2008-2012, the rest
of MoneyPuck's earliest backfilled seasons, are plausible candidates), it
will be caught and corrected automatically rather than requiring a
season-specific patch.

Regression test: `test_moneypuck_ingest.py::test_drops_duplicated_game_block`.
