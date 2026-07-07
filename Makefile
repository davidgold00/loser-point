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

data:
	$(UV) run python -m loserpoint.ingest.moneypuck
	$(UV) run python -m loserpoint.ingest.nhl_api
	$(UV) run python -m loserpoint.ingest.hockey_reference

panel:
	$(UV) run python -m loserpoint.panel.build_panel

analysis:
	$(UV) run python -m loserpoint.analysis.event_study
	$(UV) run python -m loserpoint.analysis.models
	$(UV) run python -m loserpoint.analysis.regime_did
	$(UV) run python -m loserpoint.analysis.heterogeneity
	$(UV) run python -m loserpoint.analysis.counterfactual
	$(UV) run python -m loserpoint.analysis.robustness

app:
	$(UV) run streamlit run app/streamlit_app.py

all: setup data panel analysis test

clean:
	rm -rf data/interim/* data/processed/* .cache
