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

# Targets list every pipeline module in dependency order, so `make all`
# works end to end from a clean checkout (network fetches are cached).
data:
	$(UV) run python -m loserpoint.ingest.moneypuck
	$(UV) run python -m loserpoint.ingest.nhl_api
	$(UV) run python -m loserpoint.ingest.hockey_reference

panel:
	$(UV) run python -m loserpoint.panel.build_panel
	$(UV) run python -m loserpoint.panel.context

analysis:
	$(UV) run python -m loserpoint.analysis.models
	$(UV) run python -m loserpoint.analysis.robustness
	$(UV) run python -m loserpoint.analysis.regime_did
	$(UV) run python -m loserpoint.analysis.row_experiment
	$(UV) run python -m loserpoint.analysis.counterfactual
	$(UV) run python -m loserpoint.analysis.heterogeneity

app:
	$(UV) run streamlit run app/streamlit_app.py

all: setup data panel analysis test

clean:
	rm -rf data/interim/* data/processed/* .cache
