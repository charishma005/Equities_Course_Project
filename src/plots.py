"""Shared plotting helpers: one style for every report figure (CLAUDE.md 1.3).

Figures are static PNGs at config.FIG_DPI with a title (including the sample
period), labeled axes with units, and a legend whenever there is more than
one series. Colors are fixed categorical slots, assigned in order.
"""

from __future__ import annotations

import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import config  # noqa: E402

SERIES = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100"]  # categorical slots 1-4
INK = "#0b0b0b"
INK_SECONDARY = "#52514e"
MUTED = "#898781"
GRID = "#e1e0d9"
BASELINE = "#c3c2b7"
SURFACE = "#fcfcfb"


def new_figure(width: float = 9.0, height: float = 4.5):
    """Return (fig, ax) with the project style: light surface, hairline grid,
    muted axes, no top/right spines."""
    fig, ax = plt.subplots(figsize=(width, height), facecolor=SURFACE)
    ax.set_facecolor(SURFACE)
    ax.grid(True, axis="y", color=GRID, linewidth=0.8)
    ax.set_axisbelow(True)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        ax.spines[side].set_color(BASELINE)
    ax.tick_params(colors=MUTED, labelcolor=INK_SECONDARY)
    return fig, ax


def finish(fig, ax, title: str, xlabel: str, ylabel: str, path: Path,
           legend: bool = True) -> Path:
    """Apply title/labels/legend, save to `path` as PNG, close, return path."""
    ax.set_title(title, color=INK, fontsize=12, loc="left")
    ax.set_xlabel(xlabel, color=INK_SECONDARY)
    ax.set_ylabel(ylabel, color=INK_SECONDARY)
    if legend:
        ax.legend(frameon=False, labelcolor=INK_SECONDARY)
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.tight_layout()
    fig.savefig(path, dpi=config.FIG_DPI, facecolor=SURFACE)
    plt.close(fig)
    return path
