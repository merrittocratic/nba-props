"""EDA A7: how one book's line and price move together before tip-off (points).

Catalog entry A7 in docs/eda_catalog.md (the A5 follow-up). Follows each sportsbook's
points line and price for one player-game across the pregame snapshots and classifies
every step between two consecutive snapshots.

    uv run --group eda python eda/02_line_price_moves.py
"""

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from charts import DFS, MAIN_NOTE, MUTED, SERIES, TEXT, TIDY, implied, save, style, titled
from plotly.subplots import make_subplots

# The two regular grids of points snapshots (see README, Intraday backfill).
SOURCES = ["odds_api_intraday_hist", "odds_api_neartip_hist"]
CHAIN = ["book", "event_id", "player_key"]  # one book's line for one player-game
# A book is a "ladder book" when it usually posts several lines per player; its main line
# is then just whichever rung is nearest 50/50, so its "line moves" are a different thing.
LADDER_SHARE = 0.2
# Step lengths kept, in minutes between two consecutive snapshots of the same chain.
STEPS = {"15-minute steps (last 2 hours)": (10, 20), "2-hour steps (earlier)": (100, 140)}
MIN_TIME_STEPS = 20_000  # per time-to-tip group in chart 1
MIN_BOOK_STEPS = 20_000
TYPES = ["price only", "line moved"]
TYPE_COLOR = dict(zip(TYPES, SERIES, strict=False))
STEP_NOTE = (
    "Step = two consecutive snapshots of the same book, player and game. Line moved = the"
    " main line changed; price only = same line, over or under price changed."
)
BOOKS_NOTE = (
    "Sportsbooks that post one points line per player (ladder books and DFS sites left"
    " out). Points only."
)


def load() -> tuple[pd.DataFrame, set[str]]:
    """One row per book, player-game and snapshot: main line, prices, minutes to tip."""
    cols = [
        "source",
        "event_id",
        "snapshot_ts",
        "commence_time",
        "book",
        "player_key",
        "point",
        "over_price",
        "under_price",
    ]
    d = pd.read_parquet(
        TIDY / "prop_lines.parquet",
        columns=cols,
        filters=[("market", "==", "player_points"), ("source", "in", SOURCES)],
    )
    d["book"] = d.book.astype(str)
    d = d[~d.book.isin(DFS) & d.player_key.notna()]
    d = d.dropna(subset=["over_price", "under_price"])
    d["mins"] = (d.commence_time - d.snapshot_ts).dt.total_seconds() / 60
    d = d[(d.mins > 0) & (d.mins < 31 * 60)]
    io, iu = implied(d.over_price), implied(d.under_price)
    d["p_over"] = io / (io + iu)

    rungs = d.groupby([*CHAIN, "snapshot_ts"]).point.transform("nunique")
    multi = (rungs > 1).groupby(d.book).mean()
    ladder = set(multi[multi > LADDER_SHARE].index)
    print("share of snapshots with more than one line, by book:")
    print(multi.sort_values(ascending=False).round(3).to_string())

    d["dist"] = (d.p_over - 0.5).abs()
    d = d.loc[d.groupby([*CHAIN, "snapshot_ts"]).dist.idxmin()]
    return d.drop(columns=["dist", "source", "commence_time"]), ladder


def steps(d: pd.DataFrame) -> pd.DataFrame:
    """Consecutive snapshot pairs within a chain, classified."""
    d = d.sort_values([*CHAIN, "snapshot_ts"])
    g = d.groupby(CHAIN, sort=False)
    s = d.assign(
        line0=g.point.shift(),
        p0=g.p_over.shift(),
        over0=g.over_price.shift(),
        under0=g.under_price.shift(),
        mins0=g.mins.shift(),
    ).dropna(subset=["line0"])
    s["length"] = s.mins0 - s.mins
    s["grid"] = ""
    for name, (lo, hi) in STEPS.items():
        s.loc[s.length.between(lo, hi), "grid"] = name
    s = s[s.grid != ""].copy()
    s["d_line"] = s.point - s.line0
    price_changed = (s.over_price != s.over0) | (s.under_price != s.under0)
    s["type"] = np.select([s.d_line != 0, price_changed], ["line moved", "price only"], "none")
    s["direction"] = np.select([s.d_line > 0, s.d_line < 0], ["up", "down"], "none")
    return s


def move_types_by_time(s: pd.DataFrame) -> None:
    """Chart 1: share of steps that are price-only vs line moves, by time to tip-off."""
    print("\nA7.1 Share of steps by type and time to tip-off (single-line sportsbooks)")
    fig = make_subplots(rows=1, cols=2, subplot_titles=list(STEPS), horizontal_spacing=0.09)
    for col, grid in enumerate(STEPS, start=1):
        sub = s[s.grid == grid].copy()
        if col == 1:
            sub["when"] = (sub.mins / 15).round() * 15  # minutes to tip at the end of the step
            unit = "min"
        else:
            sub["when"] = (sub.mins / 120).round() * 2  # hours to tip at the end of the step
            unit = "h"
        t = sub.groupby("when").type.value_counts(normalize=True).unstack(fill_value=0)
        t["n"] = sub.groupby("when").size()
        t = t[t.n >= MIN_TIME_STEPS].sort_index(ascending=False)
        print(grid)
        print(t.round(4).to_string())
        labels = [f"{int(w)} {unit}" for w in t.index]
        for ty in TYPES:
            fig.add_trace(
                go.Scatter(
                    x=labels,
                    y=t[ty],
                    customdata=t[["n"]],
                    name=ty,
                    legendgroup=ty,
                    showlegend=col == 1,
                    mode="lines+markers",
                    line=dict(color=TYPE_COLOR[ty], width=2),
                    marker=dict(size=8),
                    hovertemplate=(
                        f"{ty}<br>step ending %{{x}} before tip: %{{y:.1%}} of steps"
                        "<br>steps: %{customdata[0]:,}<extra></extra>"
                    ),
                ),
                row=1,
                col=col,
            )
    fig.update_yaxes(tickformat=".0%", rangemode="tozero")
    fig.update_yaxes(title_text="share of steps", col=1)
    fig.update_xaxes(title_text="time to tip-off at the end of the step")
    title = titled(
        "How often a book changes its price vs its line, by time to tip-off",
        STEP_NOTE,
        "The remaining steps had no change. The two panels are not comparable in height: a"
        " 2-hour step has eight times as long to change as a 15-minute step. Times with"
        f" under {MIN_TIME_STEPS:,} steps are left out.",
        BOOKS_NOTE,
    )
    save(style(fig, title), "a7_move_type_by_time.html")


def move_chance_by_price(s: pd.DataFrame) -> None:
    """Chart 2: chance the line moves in the next step, by where the price sits now."""
    print("\nA7.2 Chance the line moves next step, by current no-vig over probability")
    s = s.assign(p_bin=(s.p0 * 100).round())
    fig = make_subplots(rows=1, cols=2, subplot_titles=list(STEPS), horizontal_spacing=0.09)
    for col, grid in enumerate(STEPS, start=1):
        sub = s[s.grid == grid]
        t = sub.groupby("p_bin").agg(
            up=("direction", lambda x: (x == "up").mean()),
            down=("direction", lambda x: (x == "down").mean()),
            n=("direction", "size"),
        )
        t = t[(t.n >= 1000) & t.index.to_series().between(38, 62)]
        print(grid)
        print(t.round(4).to_string())
        for name, color in (("up", SERIES[0]), ("down", SERIES[1])):
            fig.add_trace(
                go.Scatter(
                    x=t.index / 100,
                    y=t[name],
                    customdata=t[["n"]],
                    name=f"line moves {name}",
                    legendgroup=name,
                    showlegend=col == 1,
                    mode="lines+markers",
                    line=dict(color=color, width=2),
                    marker=dict(size=8),
                    hovertemplate=(
                        f"line moves {name}<br>over priced at %{{x:.0%}} now: %{{y:.1%}} of"
                        " next steps<br>steps: %{customdata[0]:,}<extra></extra>"
                    ),
                ),
                row=1,
                col=col,
            )
        fig.add_vline(x=0.5, line_color=MUTED, line_dash="dot", row=1, col=col)
    fig.update_yaxes(tickformat=".0%", rangemode="tozero")
    fig.update_yaxes(title_text="share of next steps where the line moved", col=1)
    fig.update_xaxes(
        tickformat=".0%", title_text="no-vig over probability at the start of the step"
    )
    title = titled(
        "How far does a book shade the price before it moves the line?",
        "x = the book's no-vig over probability on its current line (1-point groups; right"
        " of 50% = over is the favourite). y = share of steps starting there in which the"
        " line then moved up or down. Groups under 1,000 steps are left out.",
        STEP_NOTE,
        BOOKS_NOTE + " " + MAIN_NOTE,
    )
    save(style(fig, title), "a7_move_chance_by_price.html")


def reset_after_move(s: pd.DataFrame) -> pd.DataFrame:
    """Table: where the price sat before a line move and where it was reset to."""
    m = s[s.type == "line moved"]
    t = m.groupby(["grid", "direction"]).agg(
        n=("p0", "size"),
        size=("d_line", lambda x: x.abs().mean()),
        one_point=("d_line", lambda x: (x.abs() == 1).mean()),
        p_before=("p0", "median"),
        p_after=("p_over", "median"),
    )
    print("\nA7.3 Line moves: size, and no-vig over probability before and after (median)")
    print(t.round(3).to_string())
    return t


def by_book(s: pd.DataFrame, ladder: set[str]) -> None:
    """Chart 3: each book's style: how often it changes price only vs moves the line."""
    print("\nA7.4 By book (15-minute steps)")
    near = s[s.grid == next(iter(STEPS))]
    g = near.groupby("book")
    t = pd.DataFrame(
        {
            "steps": g.size(),
            "price_only": g.type.apply(lambda x: (x == "price only").mean()),
            "line_moved": g.type.apply(lambda x: (x == "line moved").mean()),
            "before_up": near[near.direction == "up"].groupby("book").p0.median(),
            "before_down": near[near.direction == "down"].groupby("book").p0.median(),
        }
    )
    t = t[t.steps >= MIN_BOOK_STEPS].sort_values("line_moved")
    t["kind"] = np.where(t.index.isin(ladder), "ladder book", "single-line book")
    print(t.round(3).to_string())

    fig = go.Figure()
    for kind, color, symbol in (
        ("single-line book", SERIES[0], "circle"),
        ("ladder book", SERIES[1], "diamond"),
    ):
        k = t[t.kind == kind]
        fig.add_trace(
            go.Scatter(
                x=k.price_only,
                y=k.line_moved,
                text=k.index,
                customdata=k[["steps", "before_down", "before_up"]],
                name=kind,
                mode="markers+text",
                textposition="top center",
                textfont=dict(color=TEXT, size=11),
                marker=dict(color=color, size=11, symbol=symbol),
                hovertemplate=(
                    "%{text}<br>price-only changes: %{x:.1%} of steps<br>line moves:"
                    " %{y:.1%} of steps<br>steps: %{customdata[0]:,}<br>median over"
                    " probability before a move down / up: %{customdata[1]:.1%} /"
                    " %{customdata[2]:.1%}<extra></extra>"
                ),
            )
        )
    fig.update_xaxes(tickformat=".0%", title_text="share of steps with a price-only change")
    fig.update_yaxes(
        tickformat=".0%", title_text="share of steps where the line moved", rangemode="tozero"
    )
    fig.update_layout(height=600)
    title = titled(
        "Each book's style in the last 2 hours: reprice or move the line?",
        "Each dot = one sportsbook (Odds API key; williamhill_us = Caesars), 15-minute steps"
        " in the last 2 hours before tip-off, points only. Right = changes its price often"
        " without moving the line; up = moves the line often.",
        STEP_NOTE,
        "Ladder books post several lines per player; their main line is whichever is nearest"
        f" 50/50. Books under {MIN_BOOK_STEPS:,} steps are left out.",
    )
    save(style(fig, title), "a7_book_style.html")


def main() -> None:
    d, ladder = load()
    print(f"book-snapshots {len(d):,}  ladder books: {sorted(ladder)}")
    s = steps(d)
    print(f"steps {len(s):,}")
    print(s.groupby("grid").type.value_counts(normalize=True).round(4).to_string())
    single = s[~s.book.isin(ladder)]
    print(f"steps at single-line sportsbooks {len(single):,}: {sorted(single.book.unique())}")
    move_types_by_time(single)
    move_chance_by_price(single)
    reset_after_move(single)
    by_book(s, ladder)


if __name__ == "__main__":
    main()
