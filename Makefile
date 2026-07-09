.PHONY: setup data panel analysis test app all lint clean

UV := uv

setup:
	$(UV) sync --extra dev
	$(UV) run pre-commit install

lint:
	$(UV) run ruff format --check src tests
	$(UV) run ruff check src tests

test:
	$(UV) run pytest

# Phase 4 adds loserpoint.ingest.hockey_reference here; Phase 5 adds the
# regime/heterogeneity/counterfactual analysis modules. Targets list only
# modules that exist, so `make all` always works end to end.
data:
	$(UV) run python -m loserpoint.ingest.moneypuck
	$(UV) run python -m loserpoint.ingest.nhl_api

panel:
	$(UV) run python -m loserpoint.panel.build_panel
	$(UV) run python -m loserpoint.panel.context

analysis:
	$(UV) run python -m loserpoint.analysis.models
	$(UV) run python -m loserpoint.analysis.robustness

app:
	$(UV) run streamlit run app/streamlit_app.py

all: setup data panel analysis test

clean:
	rm -rf data/interim/* data/processed/* .cache
