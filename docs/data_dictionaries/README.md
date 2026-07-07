# Data dictionaries

This directory holds two kinds of files:

1. **Upstream dictionaries**, committed verbatim: MoneyPuck's published shot
   data dictionary (added in Phase 1 when the ingest module is built against it).
2. **Our own dictionaries**, one per processed table produced by this
   pipeline (`game_minutes`, `standings_by_date`, `elo_ratings`, etc.), each
   listing column name, dtype, definition, and source. Written alongside the
   table-producing code so they never drift out of sync — see
   `src/loserpoint/panel/build_panel.py` once it exists.
