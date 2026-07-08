# `moneypuck_shots_raw` — one row per shot attempt (raw ingest stage)

Source: MoneyPuck.com, `shots_<season>.zip` per season 2007-2025, downloaded
by `src/loserpoint/ingest/moneypuck.py`. Full 124-column upstream dictionary
is committed at `docs/data_dictionaries/MoneyPuck_Shot_Data_Dictionary.csv`.
This file documents only the ~20 columns this project depends on and is
kept next to `validate/schemas.py::RAW_SHOTS_SCHEMA`, which enforces it.

| Column | Type | Definition | Notes |
|---|---|---|---|
| `shotID` | int | Sequential id *within a game* (resets to 0 for every `game_id`) | **Not** season-wide unique despite the upstream dictionary's wording -- the real primary key is `(game_id, shotID)`, enforced as such in `RAW_SHOTS_SCHEMA`. See [decision 0003](../decisions/0003-moneypuck-data-quirks.md) |
| `game_id` | int | NHL game id | First digit `2` = regular season, `3` = playoffs (NHL convention) |
| `season` | int | Season the shot took place in, e.g. `2013` = 2013-14 | |
| `isPlayoffGame` | int {0,1} | 1 if playoff game | Playoff games are excluded from the main panel (no loser point applies in playoffs — see `docs/methodology.md`) |
| `homeTeamCode` / `awayTeamCode` | str | 3-4 letter team code | |
| `homeTeamWon` | int {0,1} | 1 if home team won the game | **Only reliable source of the shootout winner** — see [decision 0003](../decisions/0003-moneypuck-data-quirks.md) |
| `period` | int | Period of the shot | 1-3 = regulation; 4 = OT (3v3/5min in regular season, 5v5/20min in playoffs); >=5 only in playoff multi-OT games |
| `time` | int | Seconds into the game | Not seconds into the period — see boundary convention in [decision 0001](../decisions/0001-minute-boundary-convention.md) |
| `team` / `isHomeTeam` | str {HOME,AWAY} / int {0,1} | Shooting team, two encodings of the same fact | |
| `event` | str | `SHOT`, `MISS`, or `GOAL` | Blocked shots are not in this table — see decision 0003 |
| `goal` | int {0,1} | 1 if this row is a goal | |
| `homeTeamGoals` / `awayTeamGoals` | int | Score **entering** this shot (before it resolves) | Add `goal` for the score after this shot |
| `xGoal` | float [0,1] | Expected-goals value of the shot | MoneyPuck's model output |
| `homeSkatersOnIce` / `awaySkatersOnIce` | int | Skaters on ice (excludes goalie) | Used for the 5v5 situation filter |
| `homeEmptyNet` / `awayEmptyNet` | int {0,1} | 1 if that team's net is empty | Used by the empty-net policy in `config.yaml` |
| `shotOnEmptyNet` | int {0,1} | 1 if this specific shot was on an empty net | |
| `teamCode` | str | Team code of the shooting team | Redundant with `team`/`isHomeTeam` + `homeTeamCode`/`awayTeamCode`; kept because MoneyPuck ships it and it's a useful join key |

## What is deliberately *not* validated here

MoneyPuck ships ~100 additional columns (player-level time-on-ice detail,
rebound/rush/rest-differential diagnostics, arena-adjusted coordinates).
`RAW_SHOTS_SCHEMA` is non-strict — these pass through unvalidated because
this project's analysis never depends on their correctness. If a future
robustness cut needs one of them, add it to both this table and the schema
together so they can't drift apart.
