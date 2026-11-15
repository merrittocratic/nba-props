"""EDA A8: the price-adjusted line, and whether its pregame move predicts the result.

Catalog entry A8 in docs/eda_catalog.md. Points only. A book's position is its line plus
its price, so the price-adjusted line folds the price into the line:

    adjusted line = line + (no-vig over probability - 50%) / price per point

where price per point is how much over probability one point of line is worth at that
line level, measured from the books that post ladders.

    uv run --group eda python eda/03_adjusted_line.py
"""

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from charts import DFS, MAIN_NOTE, MUTED, SERIES, TIDY, implied, save, style, titled
from plotly.subplots import make_subplots

PG = ["event_id", "player_key"]  # one player-game (points only here)
BOOK_SNAP = ["book", "event_id", "player_key", "kind"]
# Line-level groups for measuring price per point: [lo, hi) on the midpoint of two rungs.
SLOPE_EDGES = [0, 7.5, 10, 12.5, 15, 17.5, 20, 22.5, 25, 27.5, 30, 100]
# Adjusted-move bands, in points of adjusted line (close minus open). Each is [lo, hi).
MOVE_EDGES = [-np.inf, -1, -0.5, -0.15, 0.15, 0.5, 1, np.inf]
MOVE_LABELS = [
    "down 1+",
    "down 0.5 to 1",
    "down 0.15 to 0.5",
    "within 0.15",
    "up 0.15 to 0.5",
    "up 0.5 to 1",
    "up 1+",
]
ADJ_NOTE = (
    "Adjusted line = line + (no-vig over probability - 50%) / price per point, so 24.5 with"
    " the over at 52% is about 24.8. Consensus = median across sportsbooks (DFS sites left"
    " out). Move = consensus adjusted line at close minus at open, in points."
)


def load() -> pd.DataFrame:
    cols = [
        "event_id",
        "kind",
        "book",
        "player_key",
        "point",
        "over_price",
        "under_price",
        "actual",
        "player_status",
    ]
    d = pd.read_parquet(
        TIDY / "prop_outcomes.parquet",
        columns=cols,
        filters=[("market", "==", "player_points"), ("kind", "in", ["open", "close"])],
    )
    d["book"] = d.book.astype(str)
    d["kind"] = d.kind.astype(str)
    d = d[(d.player_status == "played") & ~d.book.isin(DFS) & (d.point > 0)]
    d = d.dropna(subset=["over_price", "under_price", "actual"])
    io, iu = implied(d.over_price), implied(d.under_price)
    d["p_over"] = io / (io + iu)
    return d.drop(columns=["player_status", "over_price", "under_price"])


def price_per_point(d: pd.DataFrame) -> pd.DataFrame:
    """Over probability per point of line, by line level, from adjacent ladder rungs.

    Uses pairs of rungs one point apart at the same book, player-game and snapshot that
    sit on either side of 50%, so the slope is measured where the main line is.
    """
    d = d.sort_values([*BOOK_SNAP, "point"])
    g = d.groupby(BOOK_SNAP, sort=False)
    pairs = d.assign(point_up=g.point.shift(-1), p_up=g.p_over.shift(-1)).dropna(
        subset=["point_up"]
    )
    pairs = pairs[(pairs.point_up - pairs.point == 1) & (pairs.p_over >= 0.5) & (pairs.p_up < 0.5)]
    pairs = pairs.assign(mid=(pairs.point + pairs.point_up) / 2, slope=pairs.p_over - pairs.p_up)
    pairs["band"] = pd.cut(pairs.mid, SLOPE_EDGES, right=False)
    t = pairs.groupby("band", observed=True).agg(
        line=("mid", "median"), per_point=("slope", "median"), n=("slope", "size")
    )
    print("\nA8.1 Price per point of line (ladder books, rung pairs around 50%)")
    print(t.round(4).to_string())
    print("books:", pairs.book.value_counts().to_dict())
    return t


def adjusted(d: pd.DataFrame, slopes: pd.DataFrame) -> pd.DataFrame:
    """One row per player-game: consensus raw and adjusted line at open and close."""
    d = d.assign(dist=(d.p_over - 0.5).abs())
    main = d.loc[d.groupby(BOOK_SNAP).dist.idxmin()].copy()
    per_point = np.interp(main.point, slopes.line, slopes.per_point)
    main["adj"] = main.point + (main.p_over - 0.5) / per_point
    cons = main.groupby([*PG, "kind"]).agg(
        line=("point", "median"),
        adj=("adj", "median"),
        books=("book", "nunique"),
        actual=("actual", "first"),
    )
    # Price actually on offer at the consensus line: books whose main line equals it.
    at = main.merge(cons[["line"]].reset_index(), on=[*PG, "kind"])
    at = at[at.point == at.line]
    cons["p_at_line"] = at.groupby([*PG, "kind"]).p_over.mean()
    w = cons.unstack("kind")
    w.columns = [f"{a}_{b}" for a, b in w.columns]
    w = w.dropna(subset=["line_open", "line_close"]).reset_index()
    w["actual"] = w.pop("actual_close")
    w["raw_move"] = w.line_close - w.line_open
    w["adj_move"] = w.adj_close - w.adj_open
    w["band"] = pd.cut(w.adj_move, MOVE_EDGES, labels=MOVE_LABELS, right=False).astype(str)
    return w.drop(columns="actual_open")


def fit(x: pd.Series, y: pd.Series) -> tuple[float, float, int]:
    slope, _ = np.polyfit(x, y, 1)
    return slope, float(np.corrcoef(x, y)[0, 1]), len(x)


def regressions(w: pd.DataFrame) -> None:
    print("\nA8.2 Does the move predict where the result lands relative to the open?")
    print("    y = actual - open line (raw or adjusted); slope 1.0 = a 1-point move is worth")
    print("    1 point of result; corr = share-of-signal measure")
    rows = {
        "raw line move, all": fit(w.raw_move, w.actual - w.line_open),
        "adjusted move, all": fit(w.adj_move, w.actual - w.adj_open),
        "adjusted move, raw line unchanged": fit(
            w.adj_move[w.raw_move == 0], (w.actual - w.adj_open)[w.raw_move == 0]
        ),
        "adjusted move, raw line moved": fit(
            w.adj_move[w.raw_move != 0], (w.actual - w.adj_open)[w.raw_move != 0]
        ),
    }
    t = pd.DataFrame(rows, index=["slope", "corr", "n"]).T
    print(t.round(4).to_string())
    print(
        f"  sd of raw move {w.raw_move.std():.3f}, of adjusted move {w.adj_move.std():.3f};"
        f" raw line unchanged in {(w.raw_move == 0).mean():.1%} of player-games"
    )


def gap_table(w: pd.DataFrame, ref: str) -> pd.DataFrame:
    """Over rate against the `ref` line minus the price on offer there, by move band."""
    d = w.dropna(subset=[f"p_at_line_{ref}"])
    d = d[d.actual != d[f"line_{ref}"]]
    d = d.assign(over=(d.actual > d[f"line_{ref}"]).astype(float))
    t = d.groupby("band").agg(
        over=("over", "mean"),
        implied=(f"p_at_line_{ref}", "mean"),
        n=("over", "size"),
        move=("adj_move", "mean"),
    )
    t["gap"] = t.over - t.implied
    t["se"] = np.sqrt(t.over * (1 - t.over) / t.n)
    return t.reindex(MOVE_LABELS)


def dose_response(w: pd.DataFrame) -> None:
    """Chart 1: average result relative to the open adjusted line, by size of the move."""
    d = w.assign(landed=w.actual - w.adj_open)
    t = d.groupby("band").agg(
        move=("adj_move", "mean"),
        landed=("landed", "mean"),
        sd=("landed", "std"),
        n=("landed", "size"),
    )
    t = t.reindex(MOVE_LABELS)
    t["se"] = t.sd / np.sqrt(t.n)
    base = t.loc["within 0.15", "landed"]
    print("\nA8.3 Where the result lands vs the open adjusted line, by adjusted-move band")
    print(t.round(3).to_string())
    fig = go.Figure()
    xs = np.array([t.move.min(), t.move.max()])
    fig.add_trace(
        go.Scatter(
            x=xs,
            y=xs + base,
            name="if a 1-point move were worth exactly 1 point",
            mode="lines",
            line=dict(color=MUTED, dash="dot", width=2),
            hoverinfo="skip",
        )
    )
    fig.add_trace(
        go.Scatter(
            x=t.move,
            y=t.landed,
            error_y=dict(type="data", array=1.96 * t.se, color=SERIES[0]),
            text=t.index,
            customdata=t[["n"]],
            name="average result",
            mode="markers",
            marker=dict(color=SERIES[0], size=10),
            hovertemplate=(
                "move band: %{text}<br>average move %{x:+.2f} points<br>result landed"
                " %{y:+.2f} points from the open adjusted line<br>player-games:"
                " %{customdata[0]:,}<extra></extra>"
            ),
        )
    )
    fig.update_layout(
        xaxis_title="average adjusted-line move, open to close (points)",
        yaxis_title="average of actual points minus open adjusted line",
        height=560,
    )
    title = titled(
        "When the adjusted line moves, does the result follow?",
        "Each dot = the player-games in one move band (down 1+, down 0.5 to 1, down 0.15 to"
        " 0.5, within 0.15, up 0.15 to 0.5, up 0.5 to 1, up 1+). y = how far the actual"
        " points landed from the open adjusted line, on average; bars = 95% CI.",
        "Dotted line = what a fully informative move would give, shifted by the no-move"
        " band's average (results average slightly above the line because scoring is"
        " right-skewed).",
        ADJ_NOTE,
    )
    save(style(fig, title), "a8_move_vs_result.html")


def gap_chart(w: pd.DataFrame) -> None:
    """Chart 2: over rate minus the price on offer, against open and against close."""
    print("\nA8.4 Over rate minus price on offer, by adjusted-move band")
    groups = {"all player-games": w, "raw line did not move": w[w.raw_move == 0]}
    fig = make_subplots(rows=1, cols=2, subplot_titles=list(groups), horizontal_spacing=0.08)
    for col, (name, sub) in enumerate(groups.items(), start=1):
        for ref, color in (("open", SERIES[0]), ("close", SERIES[1])):
            t = gap_table(sub, ref)
            t = t[t.n >= 300]
            print(f"{name}, vs {ref} line and price")
            print(t.round(4).to_string())
            fig.add_trace(
                go.Scatter(
                    x=t.index,
                    y=t.gap,
                    error_y=dict(type="data", array=1.96 * t.se, color=color),
                    customdata=t[["n", "over", "implied"]],
                    name=f"bet at the {ref}",
                    legendgroup=ref,
                    showlegend=col == 1,
                    mode="markers",
                    marker=dict(color=color, size=10),
                    hovertemplate=(
                        f"bet at the {ref}, move %{{x}}<br>over rate %{{customdata[1]:.1%}},"
                        " price implied %{customdata[2]:.1%}<br>gap %{y:+.1%}"
                        "<br>player-games: %{customdata[0]:,}<extra></extra>"
                    ),
                ),
                row=1,
                col=col,
            )
        fig.add_hline(y=0, line_color=MUTED, line_dash="dot", row=1, col=col)
    fig.update_xaxes(categoryorder="array", categoryarray=MOVE_LABELS, tickangle=-30)
    fig.update_xaxes(title_text="adjusted-line move, open to close (points)")
    fig.update_yaxes(tickformat="+.0%")
    fig.update_yaxes(title_text="over rate minus price-implied over probability", col=1)
    fig.update_layout(height=600)
    title = titled(
        "Is there an edge in the move, at the open or at the close?",
        "Each dot = player-games in one move band. y = share that went over the consensus"
        " line minus the mean no-vig over probability at the books offering that line; above"
        " 0 = overs beat the price. Blue scores a bet at the open, orange at the close."
        " Bars = 95% CI; bands under 300 player-games left out.",
        "Right panel = only player-games whose consensus raw line was the same at open and"
        " close, so any move there is price only.",
        ADJ_NOTE + " " + MAIN_NOTE,
    )
    save(style(fig, title), "a8_edge_by_move.html")


def main() -> None:
    d = load()
    slopes = price_per_point(d)
    w = adjusted(d, slopes)
    print(f"\nplayer-games with open and close: {len(w):,}")
    print(w[["raw_move", "adj_move", "books_open", "books_close"]].describe().round(3).to_string())
    print(w.band.value_counts().reindex(MOVE_LABELS).to_string())
    regressions(w)
    dose_response(w)
    gap_chart(w)


if __name__ == "__main__":
    main()
