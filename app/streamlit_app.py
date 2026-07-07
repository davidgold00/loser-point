"""The public-facing Streamlit app — scrollytelling narrative over the
project's pre-aggregated `data/processed/app/` parquet artifacts.

Not yet implemented: this is a Phase 0 placeholder. The real app (hero
figure, Turtle Index leaderboard, natural-experiment before/afters,
3-2-1-0 what-if, methods drawer) is built in Phase 6 once the analysis
artifacts it reads exist.
"""

import streamlit as st

st.set_page_config(page_title="The Loser Point", page_icon="🏒")
st.title("The Loser Point")
st.info(
    "This app is not yet built — the analysis pipeline (Phases 1-5) has not "
    "run yet, so there are no results to display. See the repo README for "
    "project status."
)
