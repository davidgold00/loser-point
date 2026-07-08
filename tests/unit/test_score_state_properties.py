"""Property-based tests for panel/score_state.py.

Hypothesis generates random goal sequences and checks the invariants that
must hold for *any* game, not just hand-picked examples: mirror consistency
between the two teams, path consistency (entering scores change by exactly
the goals scored in the intervening minute), monotonicity, and a full
round-trip through MoneyPuck-shaped shot rows (including phantom goals).
"""

from __future__ import annotations

from hypothesis import given
from hypothesis import strategies as st
from loserpoint.panel.score_state import (
    MIRROR_STATE,
    extract_goal_events,
    minute_of_time,
    minute_states,
)

from tests.fixtures.panel.builders import make_game_from_goals

# A regulation goal: any second of the game, either team.
goal_strategy = st.tuples(st.integers(min_value=0, max_value=3600), st.booleans())
goal_lists = st.lists(goal_strategy, max_size=15)


@given(goal_lists)
def test_minute_one_is_always_entered_tied(goals) -> None:
    states = minute_states(extract_goal_events(make_game_from_goals(goals)) if goals else [])
    assert states.iloc[0]["home_state"] == "tied"
    assert states.iloc[0]["away_state"] == "tied"


@given(goal_lists)
def test_mirror_consistency_for_any_goal_sequence(goals) -> None:
    events = extract_goal_events(make_game_from_goals(goals)) if goals else []
    states = minute_states(events)
    assert (states["away_state"] == states["home_state"].map(MIRROR_STATE)).all()


@given(goal_lists)
def test_entering_scores_are_non_decreasing(goals) -> None:
    events = extract_goal_events(make_game_from_goals(goals)) if goals else []
    states = minute_states(events)
    assert states["home_score"].is_monotonic_increasing
    assert states["away_score"].is_monotonic_increasing


@given(goal_lists)
def test_path_consistency_scores_change_by_goals_in_prior_minute(goals) -> None:
    # The score entering minute N+1 must exceed the score entering minute N
    # by exactly the number of goals scored during minute N -- computed here
    # independently from the raw goal list, not from minute_states itself.
    events = extract_goal_events(make_game_from_goals(goals)) if goals else []
    states = minute_states(events).set_index("minute")
    reg = [g for g in events if g.is_regulation]
    for minute in range(1, 60):
        home_goals_in_minute = sum(
            1 for g in reg if minute_of_time(g.time) == minute and g.is_home_team
        )
        away_goals_in_minute = sum(
            1 for g in reg if minute_of_time(g.time) == minute and not g.is_home_team
        )
        assert (
            states.loc[minute + 1, "home_score"] - states.loc[minute, "home_score"]
            == home_goals_in_minute
        )
        assert (
            states.loc[minute + 1, "away_score"] - states.loc[minute, "away_score"]
            == away_goals_in_minute
        )


@given(st.lists(goal_strategy, min_size=1, max_size=15))
def test_round_trip_through_shot_rows_recovers_every_goal(goals) -> None:
    game = make_game_from_goals(goals)
    events = extract_goal_events(game)
    assert sorted((g.time, g.is_home_team) for g in events) == sorted(
        (time, is_home) for time, is_home in goals
    )
    assert not any(g.is_phantom for g in events)


@given(
    st.lists(goal_strategy, min_size=1, max_size=10),
    st.data(),
)
def test_phantom_goals_are_recovered_with_correct_team_totals(goals, data) -> None:
    # Mark a random subset of goals as phantom and append a late observing
    # shot so every phantom is revealed by some later row's running score.
    phantom = data.draw(st.sets(st.integers(min_value=0, max_value=len(goals) - 1)))
    game = make_game_from_goals(goals, phantom=phantom, extra_shots=[(3600, True)])
    events = extract_goal_events(game)

    assert sum(1 for g in events if g.is_phantom) == len(phantom)
    assert sum(1 for g in events if g.is_home_team) == sum(1 for _, h in goals if h)
    assert sum(1 for g in events if not g.is_home_team) == sum(1 for _, h in goals if not h)
    # Phantom timestamps are upper bounds: never earlier than the true time.
    true_times = sorted(t for i, (t, _) in enumerate(goals) if i in phantom)
    phantom_times = sorted(g.time for g in events if g.is_phantom)
    assert all(obs >= true for obs, true in zip(phantom_times, true_times, strict=True))
