"""Shared chart helpers for the EDA scripts: colours, titles with small print, saving.

Every chart title goes through `titled`, which adds the small print that says what the
unit, the axes and the groups are. Import from a script run as `python eda/<script>.py`.
"""

import textwrap
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.graph_objects as go

TIDY = Path("data/tidy_mini")
FIG = Path("eda/figures")

# Validated default categorical order (dataviz skill palette.md), light surface.
SERIES = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300"]
SURFACE = "#fcfcfb"
TEXT = "#0b0b0b"
MUTED = "#52514e"

# DFS sites: lines are real, prices are placeholders (-137 both sides).
DFS = {"prizepicks", "underdog", "pick6", "betr_us_dfs"}
MAIN_NOTE = (
    "Main line = the book's line priced nearest 50/50; no-vig probability = over price"
    " rescaled so over + under = 100%."
)


def style(fig: go.Figure, title: str) -> go.Figure:
    fig.update_layout(
        # Pin the title to the top so the small print grows downward into the margin.
        title=dict(text=title, yref="container", y=1, yanchor="top", pad=dict(t=16)),
        template="simple_white",
        paper_bgcolor=SURFACE,
        plot_bgcolor=SURFACE,
        font=dict(color=TEXT, size=13),
        hoverlabel=dict(bgcolor="white", font_color=TEXT),
        legend_title_text="",
        margin_t=85 + 26 * title.count("<br>"),
    )
    fig.update_xaxes(showgrid=False, linecolor=MUTED, tickcolor=MUTED)
    fig.update_yaxes(showgrid=True, gridcolor="#ecebe8", linecolor=MUTED, tickcolor=MUTED)
    fig.for_each_annotation(lambda a: a.update(text=a.text.split("=")[-1]))
    return fig


def titled(title: str, *notes: str) -> str:
    """Chart title plus small print saying what the unit, axes and groups are.

    The notes are joined and wrapped to short lines so they fit a laptop-width window.
    """
    lines = textwrap.wrap(" ".join(notes), width=160)
    return title + "".join(f"<br><sup>{line}</sup>" for line in lines)


def save(fig: go.Figure, name: str) -> None:
    FIG.mkdir(parents=True, exist_ok=True)
    fig.write_html(FIG / name, include_plotlyjs="cdn")
    print(f"  wrote {FIG / name}")


def implied(american: pd.Series) -> pd.Series:
    """American odds -> implied probability (with vig)."""
    a = american.astype(float)
    return np.where(a < 0, -a / (-a + 100), 100 / (a + 100))
