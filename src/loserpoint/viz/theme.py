"""Single source of truth for figure styling.

Palette and chrome follow the project's data-viz standard: series colors
carry identity on marks only (text always wears ink tokens), the story
series gets the accent hue and context series get de-emphasis gray
("emphasis" form), grids are hairline and recessive. Every figure saves
PNG (for the README, 2x scale) and SVG (for the memo) via `save_figure`.
"""

from __future__ import annotations

from pathlib import Path

import matplotlib
import matplotlib.pyplot as plt

matplotlib.use("Agg")  # headless everywhere; figures are file artifacts

# --- palette (light surface; validated categorical slots + ink tokens) ---
SURFACE = "#fcfcfb"
INK_PRIMARY = "#0b0b0b"
INK_SECONDARY = "#52514e"
INK_MUTED = "#898781"
GRIDLINE = "#e1e0d9"
BASELINE = "#c3c2b7"

ACCENT = "#2a78d6"  # categorical slot 1 (blue): the story series
CONTEXT_GRAY = "#898781"  # de-emphasis: comparison series
RIBBON_ALPHA = 0.10  # CI ribbons are a wash, never a block

FIGURES_DIR = Path("docs/figures")

FONT_STACK = ["system-ui", "-apple-system", "Segoe UI", "Helvetica Neue", "Arial", "sans-serif"]


def apply_theme() -> None:
    """Set matplotlib rcParams for the project look. Call once per figure
    script, before creating any figure."""
    plt.rcParams.update(
        {
            "figure.facecolor": SURFACE,
            "axes.facecolor": SURFACE,
            "savefig.facecolor": SURFACE,
            "font.family": "sans-serif",
            "font.sans-serif": FONT_STACK,
            "text.color": INK_PRIMARY,
            "axes.edgecolor": BASELINE,
            "axes.labelcolor": INK_SECONDARY,
            "axes.grid": True,
            "grid.color": GRIDLINE,
            "grid.linewidth": 1.0,
            "axes.spines.top": False,
            "axes.spines.right": False,
            "axes.spines.left": False,
            "xtick.color": INK_MUTED,
            "ytick.color": INK_MUTED,
            "xtick.labelsize": 10,
            "ytick.labelsize": 10,
            "axes.titlesize": 15,
            "axes.labelsize": 11,
            "lines.linewidth": 2.0,
            "lines.solid_capstyle": "round",
            "lines.solid_joinstyle": "round",
        }
    )


def save_figure(fig: plt.Figure, name: str, out_dir: Path | str = FIGURES_DIR) -> list[Path]:
    """Save a figure as both PNG (2x, for the README) and SVG (for the memo).

    Args:
        fig: the figure to save.
        name: file stem, e.g. "divergence" -> divergence.png + divergence.svg.
        out_dir: destination directory (created if missing).

    Returns:
        The two written paths.
    """
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    paths = []
    for ext, dpi in (("png", 200), ("svg", None)):
        path = out_dir / f"{name}.{ext}"
        fig.savefig(path, dpi=dpi, bbox_inches="tight")
        paths.append(path)
    return paths
