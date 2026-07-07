# 0002 — `nhl-api-py` package name vs. import name

**Status:** Noted during Phase 0 scaffold verification.

The PyPI distribution is `nhl-api-py` (installed via `pip install nhl-api-py` /
declared as `nhl-api-py>=1.2` in `pyproject.toml`), but the importable module
is `nhlpy`, not `nhl_api_py`. The currently resolved version is 3.3.0.

**Action for Phase 3:** `src/loserpoint/ingest/nhl_api.py` must `import nhlpy`
(e.g. `from nhlpy import NHLClient`), not `import nhl_api_py`. Verify the
client's actual method names against the installed 3.3.0 API at that time,
since the package is under active development and method signatures may have
moved since the `>=1.2` floor was set.
