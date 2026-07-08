"""Every README/memo figure as a pure function -> saved PNG + SVG.

Figures follow the project theme (viz/theme.py): the story series wears the
accent hue, comparison series wear de-emphasis grays, CI ribbons are a 10%
wash, text wears ink tokens (never series colors), and every figure carries
a source-and-n footer.
"""

from __future__ import annotations

from pathlib import Path

import matplotlib.pyplot as plt
import pandas as pd

from loserpoint.viz.theme import (
    ACCENT,
    FIGURES_DIR,
    INK_MUTED,
    INK_PRIMARY,
    INK_SECONDARY,
    RIBBON_ALPHA,
    apply_theme,
    save_figure,
)

# Emphasis form: tied is the story; the two one-goal states are context.
# down_1 gets the darker gray because its line sits highest on the chart.
SERIES_STYLE = {
    "tied": {"color": ACCENT, "label": "Tied"},
    "down_1": {"color": "#52514e", "label": "Down by one"},
    "up_1": {"color": "#898781", "label": "Up by one"},
}


def divergence_figure(
    curves: pd.DataFrame,
    contrasts: dict[str, float],
    *,
    n_games: int,
    seasons_label: str,
    out_dir: Path | str = FIGURES_DIR,
) -> list[Path]:
    """The headline figure: third-period shot-attempt curves entering each
    score state, with each state's late-window drop annotated at its line
    end.

    How to read it: each point is the league-average number of 5v5
    unblocked shot attempts a team generates in that game minute, given
    the score state it entered the minute with. Down-one teams (nothing
    banked) barely slow down; up-one teams (protecting two points) slow
    down sharply; tied teams sit far closer to the protectors than to the
    pushers -- the loser-point signature (decision 0008).

    Args:
        curves: output of analysis.descriptive.intensity_curves.
        contrasts: output of analysis.descriptive.headline_contrasts.
        n_games: number of games behind the curves (for the footer).
        seasons_label: human-readable season coverage (for the footer).
        out_dir: where to write divergence.png / divergence.svg.

    Returns:
        The written file paths.
    """
    apply_theme()
    fig, ax = plt.subplots(figsize=(9.5, 5.6))

    drop_keys = {"tied": "tied_drop_pct", "down_1": "down1_drop_pct", "up_1": "up1_drop_pct"}
    for state, style in SERIES_STYLE.items():
        sub = curves[curves["score_state"] == state].sort_values("minute")
        is_story = state == "tied"
        ax.plot(
            sub["minute"],
            sub["mean"],
            color=style["color"],
            zorder=3 if is_story else 2,
            linewidth=2.4 if is_story else 2.0,
        )
        ax.fill_between(
            sub["minute"],
            sub["lo"],
            sub["hi"],
            color=style["color"],
            alpha=RIBBON_ALPHA,
            linewidth=0,
            zorder=1,
        )
        end = sub.iloc[-1]
        drop = contrasts[drop_keys[state]]
        ax.annotate(
            f"{style['label']}  {drop:+.0f}%",
            xy=(end["minute"], end["mean"]),
            xytext=(7, 0),
            textcoords="offset points",
            va="center",
            fontsize=10.5,
            fontweight="bold" if is_story else "normal",
            color=INK_PRIMARY if is_story else INK_SECONDARY,
        )

    late_start = int(contrasts["late_start"])
    ax.axvline(late_start - 0.5, color=INK_MUTED, linewidth=1.0, linestyle=(0, (4, 4)))
    ax.annotate(
        "final five minutes",
        xy=(late_start - 0.5, ax.get_ylim()[1]),
        xytext=(-6, -2),
        textcoords="offset points",
        va="top",
        ha="right",
        fontsize=9.5,
        color=INK_MUTED,
    )

    ax.set_title(
        "With a guaranteed point five minutes away, tied teams play like lead-protectors",
        loc="left",
        color=INK_PRIMARY,
        pad=26,
    )
    ax.text(
        0,
        1.045,
        "Mean 5v5 unblocked shot attempts per team-minute, by score state entering the minute "
        "(third period). Percentages: minutes 56–58 vs 41–55.",
        transform=ax.transAxes,
        fontsize=10,
        color=INK_SECONDARY,
        va="bottom",
    )
    ax.set_xlabel("Game minute (third period)")
    ax.set_ylabel("Shot attempts per team-minute")
    ax.set_xlim(curves["minute"].min(), 66)
    ax.set_xticks(range(45, 61, 5))
    ax.grid(axis="x", visible=False)
    ax.legend(
        handles=[
            plt.Line2D([], [], color=SERIES_STYLE[s]["color"], label=SERIES_STYLE[s]["label"])
            for s in SERIES_STYLE
        ],
        loc="lower left",
        frameon=False,
        fontsize=9.5,
        labelcolor=INK_SECONDARY,
    )
    fig.text(
        0.01,
        -0.04,
        f"Source: MoneyPuck.com shot data, {seasons_label} regular seasons "
        f"(n = {n_games:,} games). 5v5 minutes only; empty-net and goalie-pulled shots "
        "excluded. One-goal curves end at minute 58: goalie pulls remove later minutes "
        "from the 5v5 sample.\nShaded bands: 95% game-cluster bootstrap CIs.",
        fontsize=8.5,
        color=INK_MUTED,
        ha="left",
    )
    return save_figure(fig, "divergence", out_dir=out_dir)
