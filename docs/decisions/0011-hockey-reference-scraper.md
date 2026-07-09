# 0011 — Hockey-Reference scraper: verified structure and scope

**Status:** Verified against the live site before writing any scraper
code (per project policy: never guess URLs).

## robots.txt (fetched 2026-07-09)

```
User-agent: *
Disallow: /hockey/
Disallow: /play-index/*cgi
Disallow: */scoring/
Disallow: */gamelog/
Disallow: */splits/
Disallow: /player_search.cgi
Disallow: /boxscores/index*
...
Crawl-delay: 3
```

Two paths this project needs are both **allowed**:
- `/leagues/NHL_{year}_games.html` (season schedule) — not `/boxscores/index*`
  (that disallow is the boxscore date-picker index, a different page).
- `/boxscores/{slug}.html` (individual boxscore) — the disallowed
  `*/scoring/` pattern is Hockey-Reference's separate *team season scoring
  leaders* page (e.g. `/teams/TOR/2013_scoring.html`), not the scoring
  summary table embedded on the boxscore page itself.

`Crawl-delay: 3`; `config.yaml`'s `min_request_interval_seconds: 4.0`
already exceeds it, so no change was needed.

## Confirmed page structures

**Schedule page** (`NHL_{year}_games.html`, one request per season): a
single table with one row per regular-season game, `data-stat` attributes
`date_game`, `visitor_team_name`, `visitor_goals`, `home_team_name`,
`home_goals`, `overtimes` (blank / `OT` / `SO`), and a `csk` slug on the
date cell (e.g. `199910010DAL`) that is exactly the boxscore URL stem.
This one page gives the full game list, final scores, and the reached-OT
flag for an entire season in a single fetch — no need to touch the
disallowed boxscore index.

**Boxscore page** (`/boxscores/{slug}.html`, one request per game): the
scoring summary lives in `<table id="scoring">`, with period-header rows
(`<tr class="thead onecell"><th colspan="5">1st Period</th></tr>`)
followed by goal rows: `<td>` elapsed time in the period (MM:SS), scoring
team abbreviation, situation (PP/SH/EN/blank), scorer, assists. Verified
against 199910010DAL.html (no OT) and 199910010EDM.html (reached OT,
scoreless, ended 1-1 -- confirming real ties still occur in this era,
exactly the pre-shootout mechanism the loser point was introduced to
soften).

## Season label convention

Hockey-Reference's URL year is the season's *second* calendar year
(`NHL_2000_games.html` = the 1999-2000 season). This project labels
seasons by the *first* year everywhere else (matching MoneyPuck's
`season=2013` for 2013-14), so `season_schedule(season)` fetches
`NHL_{season + 1}_games.html` and stores `season=1999` for that page's
games — the mapping lives in one place (`_schedule_url`) so it can't drift.

## Goal-event reuse

Boxscore goal rows convert directly into `panel.score_state.GoalEvent`
objects (period, absolute game-seconds via the same 20-minute-period
offsets as the modern data, `is_phantom=False` always -- Hockey-Reference
has no analog of MoneyPuck's phantom-goal gap). This means
`minute_states()` and the entire minute-boundary convention (decision
0006) apply unchanged to historical data; only the *outcome* differs
(goals, not shot attempts), because Hockey-Reference has no shot-location
data for this era.

## Scope: bounded sample per season, not full population

A full population fetch is ~1,230 games/season x 8 seasons x 4s/request
= approximately 11 hours -- outside what's practical for one working
session, and the regime DiD is powered by goal *counts*, not shot
attempts, so its minimum detectable effect is naturally coarser regardless
of sample size within reason. `config.yaml`'s
`historical_sample_games_per_season` bounds the scrape (deterministic
random sample, fixed seed, spread evenly across the season by sampling
without replacement from the full schedule) rather than fetching every
game. `make data` with this cap unset (null) runs the full population;
the bounded run here is what's actually executed and is disclosed as a
sample-size limitation in `docs/methodology.md`.
