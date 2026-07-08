# 0003 — MoneyPuck shot data: verified quirks and schema stability

**Status:** Confirmed during Phase 1 by downloading and inspecting the 2007,
2013, and 2025 season files directly (oldest, middle, and newest available
seasons), not just reading the published dictionary.

## Schema is stable across the full 2007-2025 range

2007 and 2013 have byte-identical column sets (124 columns, same names, same
order). Row counts for both match MoneyPuck's own published totals in the
data dictionary's notes section exactly (106,243 for 2007; 110,682 for
2013). No nulls in any of the ~20 columns this project depends on. This means
a single pandera schema can validate the whole modern era without
per-era branching.

## Shootout-deciding goals are NOT shot events

The shot table only records shots taken during regulation and overtime play;
a shootout is not "shots" in the hockey sense (attempts against a lone
goalie in a skills contest) and MoneyPuck does not log them here at all.
Confirmed example: 2013 game 20009 — the last recorded row has
`period == 4`, `homeTeamGoals == 4`, `awayTeamGoals == 4`, `goal == 0`, yet
`homeTeamWon == 1`. The recorded goal tally is tied; the decision came from a
shootout that left no trace in this table.

**Consequence for `panel/score_state.py` and the "reached overtime" /
"decided by shootout" outcome variables (Phase 2-3):** these must be derived
from `homeTeamWon` plus the last row's recorded score and `period`, never
inferred from goal parity in the shot rows alone. A game where the last
recorded score is tied and `period == 4` (regular season) is a shootout game;
the winner is given by `homeTeamWon`, not by any goal event in this table.

## Period numbering differs between regular season and playoffs

Regular-season games never exceed `period == 4` (a single 5-minute, 3-on-3
overtime; ties beyond that go to a shootout with no shot rows, per above).
Playoff games can reach `period >= 5` because playoff overtimes are full
20-minute 5-on-5 periods repeated until a goal — confirmed on 2013 game
30132 (playoff, `game_id` starting with 3 per the NHL's own ID convention),
which has real shot rows at `period == 5` with `time` past 4800 seconds.
`period <= 3` is regulation in both cases; the panel is regulation-only, so
this only affects the "reached OT" / "OT length" outcome variables, not the
panel construction itself.

## Blocked shots are excluded by design

`event` takes exactly three values across every season checked: `SHOT`
(shot on goal), `MISS` (shot that missed the net), `GOAL`. Blocked shots are
not tracked in this table (MoneyPuck tracks them in a separate table, not
downloaded here since shot attempts — Corsi — for this project's purposes
are on-net attempts + misses + goals, consistent with how the descriptive
and model specs in `docs/methodology.md` define "shot attempts").

## Known incomplete games (MoneyPuck's own disclosure)

Per the data dictionary's own notes, these games have missing/incomplete
shot data and are excluded from reconciliation sampling (not from the
analysis panel — that decision is deferred to `build_panel.py`, which will
need its own policy for whether to drop them):

| Season | Game ID |
|---|---|
| 2008 | 259 |
| 2008 | 409 |
| 2008 | 1077 |
| 2009 | 81 |

## Published row-count totals only cover 2007-2018

MoneyPuck's dictionary notes list exact published shot totals through 2018
only; there is no independent published total to reconcile against for 2019
onward. `validate/checks.py` treats seasons without a published total as
"no reference available" (an `INFO`-severity, non-blocking note in the
reconciliation report), not a silent pass or a failure.

## `shotID` is not season-wide unique -- it resets every game

The upstream dictionary describes `shotID` as "a unique id for each shot,"
which reads as a season-wide primary key. It is not: confirmed on the 2025
season file, `shotID` is a per-game sequential counter starting at 0/1 for
every `game_id` (game 20001's first shot has `shotID == 0`; game 20066's
first shot also has `shotID == 0`). 244 duplicate `shotID` values were found
across the 119,271-row 2025 file purely from this per-game restart, not from
any actual data corruption. The real primary key for a shot row is the pair
`(game_id, shotID)`. `RAW_SHOTS_SCHEMA` enforces uniqueness on that pair
(`unique=["game_id", "shotID"]`), not on `shotID` alone.

## Some goals increment the running score with no corresponding shot row

Confirmed on 2013 game 20451: `awayTeamGoals` jumps from 2 to 3 on a row
that is itself a plain `SHOT` for the *home* team, with no `GOAL`-tagged row
anywhere near it in either team's log. The running score column is correct
(it agrees with the game's actual final score), but the goal that caused
the increment has no shot-event row of its own -- a genuine, if rare, gap in
MoneyPuck's shot-event logging, not an ingest bug.

**Consequence:** `validate/checks.py::check_game_goal_counts` only enforces
that the running score is monotonic non-decreasing; it deliberately does
not check that the final tally equals the count of `GOAL`-tagged rows,
since that equality does not always hold in real data. This is also why
`panel/score_state.py` (Phase 2) must read the running
`homeTeamGoals`/`awayTeamGoals` columns directly as the score-state ground
truth, and must never reconstruct score by counting `GOAL` rows.

## `modern_end` in `config.yaml` needed a bump

The config inherited from Phase 0 scaffolding had `modern_end: 2024`. Direct
verification (`shots_2025.zip` downloads a complete 1,312-regular-season-game
year; `shots_2026.zip` 404s) confirmed 2025 is the actual latest completed
season as of 2026-07-07. Updated in this phase.
