"""Hand-verified expectations for the golden games.

Every expectation below was derived BY HAND from the raw goal timelines
(printed from the raw season files during Phase 2 and reproduced in the
comments), applying the two conventions of decision 0006 manually:

    minute(t) = max(1, ceil(t/60));  a goal in minute M changes the state
    entering minute M+1 onward.

If a refactor of score_state.py or build_panel.py changes any of these,
the refactor is wrong, not the fixture. `home_states` lists
(first_minute, last_minute, state) ranges covering minutes 1-60 exactly.

The pre-2005 "historical tie" golden game cannot come from MoneyPuck
(shot data starts 2007-08); it is added in Phase 4 alongside the
Hockey-Reference scraper, in HISTORICAL_GOLDEN_GAMES below, and tested
against `ingest.hockey_reference` directly (not the MoneyPuck ingest
pipeline) in tests/golden/test_golden_historical.py.
"""

# ------------------------------------------------------------------
# Historical (Hockey-Reference) golden game: real pre-shootout tie.
# NYR @ EDM, October 1, 1999. Goals: EDM (home) @ t=1317 (minute 22),
# NYR (away) @ t=1601 (minute 27). Final 1-1; OT was played (5 min,
# 4-on-4 sudden death under the rules in effect that season) but nobody
# scored, so the game ended in a real tie -- exactly the outcome the
# 1999 loser point was introduced to soften (each team banks 1 point).
#   EDM@1317 min 22 -> up_1 entering 23     NYR@1601 min 27 -> tied entering 28
HISTORICAL_GOLDEN_GAMES = {
    ("1999", "199910010EDM"): {
        "home_team": "EDM",
        "home_states": [
            (1, 22, "tied"),
            (23, 27, "up_1"),
            (28, 60, "tied"),
        ],
        "final_score": (1, 1),  # (home, away)
        "is_tie": True,
    },
}

GOLDEN_GAMES = {
    # ------------------------------------------------------------------
    # Edge case: WHOLESALE DUPLICATED BLOCK (decision 0005). The committed
    # CSV holds the raw, pre-dedup rows: every event appears twice. The
    # golden test runs ingest cleaning first; expectations describe the
    # deduplicated game. Goals (post-dedup): H@586, A@2072, A@2358, H@2644.
    # Reg 2-2, OT scoreless -> shootout, home (DET) won.
    #   H@586  min 10 -> up_1 entering 11      A@2072 min 35 -> tied entering 36
    #   A@2358 min 40 -> down_1 entering 41    H@2644 min 45 -> tied entering 46
    (2007, 20004): {
        "home_states": [
            (1, 10, "tied"),
            (11, 35, "up_1"),
            (36, 40, "tied"),
            (41, 45, "down_1"),
            (46, 60, "tied"),
        ],
        "reg_score": (2, 2),
        "final_score": (2, 2),
        "reached_ot": True,
        "decided_by_shootout": True,
        "home_won": True,
        "is_playoff": False,
        "n_phantom_goals": 0,
    },
    # ------------------------------------------------------------------
    # Edge case: SHOOTOUT (decision 0003's original example). WSH vs CGY.
    # Goals: A@318, A@613, A@982, H@1650, A@1745, H@1884, H@2125, H@3250.
    # Reg 4-4, OT scoreless, homeTeamWon=1 with tied recorded score.
    #   A@318  min 6  -> down_1 entering 7     A@613  min 11 -> down_2+ entering 12
    #   A@982  min 17 (0-3, label unchanged)   H@1650 min 28 (1-3, unchanged)
    #   A@1745 min 30 (1-4, unchanged)         H@1884 min 32 (2-4, unchanged)
    #   H@2125 min 36 -> down_1 entering 37    H@3250 min 55 -> tied entering 56
    (2013, 20009): {
        "home_states": [
            (1, 6, "tied"),
            (7, 11, "down_1"),
            (12, 36, "down_2_plus"),
            (37, 55, "down_1"),
            (56, 60, "tied"),
        ],
        "reg_score": (4, 4),
        "final_score": (4, 4),
        "reached_ot": True,
        "decided_by_shootout": True,
        "home_won": True,
        "is_playoff": False,
        "n_phantom_goals": 0,
    },
    # ------------------------------------------------------------------
    # Edge case: GOAL IN THE FINAL 10 SECONDS (t=3599, minute 60 -- must
    # change nothing, as it would affect only nonexistent minute 61).
    # ARI vs DET. Goals: A@287, A@482, H@2340, H@2707, H@2828, H@3194,
    # H@3599. H@2340 is also an exact boundary: 2340 = 39:00 -> minute 39.
    #   A@287  min 5  -> down_1 entering 6     A@482  min 9  -> down_2+ entering 10
    #   H@2340 min 39 -> down_1 entering 40    H@2707 min 46 -> tied entering 47
    #   H@2828 min 48 -> up_1 entering 49      H@3194 min 54 -> up_2+ entering 55
    #   H@3599 min 60 -> no effect
    (2013, 20120): {
        "home_states": [
            (1, 5, "tied"),
            (6, 9, "down_1"),
            (10, 39, "down_2_plus"),
            (40, 46, "down_1"),
            (47, 48, "tied"),
            (49, 54, "up_1"),
            (55, 60, "up_2_plus"),
        ],
        "reg_score": (5, 2),
        "final_score": (5, 2),
        "reached_ot": False,
        "decided_by_shootout": False,
        "home_won": True,
        "is_playoff": False,
        "n_phantom_goals": 0,
    },
    # ------------------------------------------------------------------
    # Edge case: THREE GOALS IN ONE MINUTE (A@1383, H@1402, H@1431 -- all
    # minute 24; net effect 0-1 -> 2-2, so entering minute 25 is tied).
    # WPG vs CHI. Other goals: A@1046, A@1863, H@2010, A@2591, A@2722,
    # A@3545 (minute 60, no effect).
    #   A@1046 min 18 -> down_1 entering 19    [triple in min 24] -> tied entering 25
    #   A@1863 min 32 -> down_1 entering 33    H@2010 min 34 -> tied entering 35
    #   A@2591 min 44 -> down_1 entering 45    A@2722 min 46 -> down_2+ entering 47
    (2013, 20330): {
        "home_states": [
            (1, 18, "tied"),
            (19, 24, "down_1"),
            (25, 32, "tied"),
            (33, 34, "down_1"),
            (35, 44, "tied"),
            (45, 46, "down_1"),
            (47, 60, "down_2_plus"),
        ],
        "reg_score": (3, 6),
        "final_score": (3, 6),
        "reached_ot": False,
        "decided_by_shootout": False,
        "home_won": False,
        "is_playoff": False,
        "n_phantom_goals": 0,
    },
    # ------------------------------------------------------------------
    # Edge case: PHANTOM GOAL (decision 0003's original example). NYR vs
    # WSH. Away's 3rd goal has no GOAL row; first observed by the running
    # score at t=2329 (minute 39) -> counted entering minute 40 onward.
    # Goals: A@1348, A@1373 (both minute 23), PHANTOM-A observed @2329,
    # A@3423 (min 58), H@3487 (min 59) -- the last three never change the
    # label, which is down_2_plus from minute 24 on.
    (2013, 20451): {
        "home_states": [
            (1, 23, "tied"),
            (24, 60, "down_2_plus"),
        ],
        "reg_score": (1, 4),
        "final_score": (1, 4),
        "reached_ot": False,
        "decided_by_shootout": False,
        "home_won": False,
        "is_playoff": False,
        "n_phantom_goals": 1,
    },
    # ------------------------------------------------------------------
    # Edge case: GOAL AT EXACTLY 54:00.0 (t=3240) -- the spec's canonical
    # boundary case: minute 54, so tied entering 55, PLUS a shootout.
    # VGK vs LAK. Goals: A@281, A@717, H@1330, A@2021, H@2252, H@2354,
    # H@2706, H@2923, A@3099, A@3240. Reg 5-5, OT scoreless, away won SO.
    #   A@281  min 5  -> down_1 entering 6     A@717  min 12 -> down_2+ entering 13
    #   H@1330 min 23 -> down_1 entering 24    A@2021 min 34 -> down_2+ entering 35
    #   H@2252 min 38 -> down_1 entering 39    H@2354 min 40 -> tied entering 41
    #   H@2706 min 46 -> up_1 entering 47      H@2923 min 49 -> up_2+ entering 50
    #   A@3099 min 52 -> up_1 entering 53      A@3240 min 54 -> tied entering 55
    (2025, 20007): {
        "home_states": [
            (1, 5, "tied"),
            (6, 12, "down_1"),
            (13, 23, "down_2_plus"),
            (24, 34, "down_1"),
            (35, 38, "down_2_plus"),
            (39, 40, "down_1"),
            (41, 46, "tied"),
            (47, 49, "up_1"),
            (50, 52, "up_2_plus"),
            (53, 54, "up_1"),
            (55, 60, "tied"),
        ],
        "reg_score": (5, 5),
        "final_score": (5, 5),
        "reached_ot": True,
        "decided_by_shootout": True,
        "home_won": False,
        "is_playoff": False,
        "n_phantom_goals": 0,
    },
    # ------------------------------------------------------------------
    # Edge case: COMEBACK (home down 0-2, wins 6-3 in regulation) with a
    # heavy empty-net finish (H@3492, H@3595 with TOR's net empty).
    # DET vs TOR. Goals: A@147, A@749, H@1736, H@2095, H@2290, A@2558,
    # H@2805, H@3492, H@3595 (minute 60, no effect).
    #   A@147  min 3  -> down_1 entering 4     A@749  min 13 -> down_2+ entering 14
    #   H@1736 min 29 -> down_1 entering 30    H@2095 min 35 -> tied entering 36
    #   H@2290 min 39 -> up_1 entering 40      A@2558 min 43 -> tied entering 44
    #   H@2805 min 47 -> up_1 entering 48      H@3492 min 59 -> up_2+ entering 60
    (2025, 20025): {
        "home_states": [
            (1, 3, "tied"),
            (4, 13, "down_1"),
            (14, 29, "down_2_plus"),
            (30, 35, "down_1"),
            (36, 39, "tied"),
            (40, 43, "up_1"),
            (44, 47, "tied"),
            (48, 59, "up_1"),
            (60, 60, "up_2_plus"),
        ],
        "reg_score": (6, 3),
        "final_score": (6, 3),
        "reached_ot": False,
        "decided_by_shootout": False,
        "home_won": True,
        "is_playoff": False,
        "n_phantom_goals": 0,
    },
    # ------------------------------------------------------------------
    # Edge case: DECIDED BY AN OT GOAL (reached OT but NOT a shootout),
    # with a second exact-boundary goal late: A@3360 = 56:00 -> minute 56,
    # so tied entering 57. CAR vs PHI. Goals: A@1178, H@1426, A@1578,
    # H@1747, H@2310, A@3360, H@3883 (OT, excluded from panel states).
    #   A@1178 min 20 -> down_1 entering 21    H@1426 min 24 -> tied entering 25
    #   A@1578 min 27 -> down_1 entering 28    H@1747 min 30 -> tied entering 31
    #   H@2310 min 39 -> up_1 entering 40      A@3360 min 56 -> tied entering 57
    (2025, 20030): {
        "home_states": [
            (1, 20, "tied"),
            (21, 24, "down_1"),
            (25, 27, "tied"),
            (28, 30, "down_1"),
            (31, 39, "tied"),
            (40, 56, "up_1"),
            (57, 60, "tied"),
        ],
        "reg_score": (3, 3),
        "final_score": (4, 3),
        "reached_ot": True,
        "decided_by_shootout": False,
        "home_won": True,
        "is_playoff": False,
        "n_phantom_goals": 0,
    },
    # ------------------------------------------------------------------
    # Edge case: PLAYOFF MULTI-OVERTIME (period 5 goal at t=5633 -- must
    # be excluded from panel states; playoff games can never be shootouts).
    # CAR vs OTT. Goals: H@391, H@1670, A@1847, A@2200, H@5633 (2OT).
    #   H@391  min 7  -> up_1 entering 8       H@1670 min 28 -> up_2+ entering 29
    #   A@1847 min 31 -> up_1 entering 32      A@2200 min 37 -> tied entering 38
    (2025, 30132): {
        "home_states": [
            (1, 7, "tied"),
            (8, 28, "up_1"),
            (29, 31, "up_2_plus"),
            (32, 37, "up_1"),
            (38, 60, "tied"),
        ],
        "reg_score": (2, 2),
        "final_score": (3, 2),
        "reached_ot": True,
        "decided_by_shootout": False,
        "home_won": True,
        "is_playoff": True,
        "n_phantom_goals": 0,
    },
}
