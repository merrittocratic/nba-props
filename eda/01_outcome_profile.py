"""EDA Part A: outcome profile of player props vs the market line.

Catalog entries A1-A3 in docs/eda_catalog.md. Writes Plotly HTML to eda/figures/ and
prints the summary tables used to fill in the catalog.

    uv run --group eda python eda/01_outcome_profile.py
"""

from pathlib import Path

import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go

TIDY = Path("data/tidy_mini")
FIG = Path("eda/figures")

# Validated default categorical order (dataviz skill palette.md), light surface.
SERIES = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300"]
SURFACE = "#fcfcfb"
TEXT = "#0b0b0b"
MUTED = "#52514e"

MARKETS = {
    "player_points": "Points",
    "player_rebounds": "Rebounds",
    "player_assists": "Assists",
    "player_threes": "Threes",
    "player_points_rebounds": "Pts+Reb",
    "player_points_rebounds_assists": "Pts+Reb+Ast",
}
MARKET_COLOR = dict(zip(MARKETS.values(), SERIES, strict=True))
DFS = {"prizepicks", "underdog", "pick6", "betr_us_dfs"}
KEY = ["event_id", "kind", "market", "player_key"]
PG = ["event_id", "market", "player_key"]  # one player-game-market
WINDOWS = ["Q1 lowest", "Q2", "Q3", "Q4", "Q5 highest"]


def style(fig: go.Figure, title: str) -> go.Figure:
    fig.update_layout(
        title=title,
        template="simple_white",
        paper_bgcolor=SURFACE,
        plot_bgcolor=SURFACE,
        font=dict(color=TEXT, size=13),
        hoverlabel=dict(bgcolor="white", font_color=TEXT),
        legend_title_text="",
    )
    fig.update_xaxes(showgrid=False, linecolor=MUTED, tickcolor=MUTED)
    fig.update_yaxes(showgrid=True, gridcolor="#ecebe8", linecolor=MUTED, tickcolor=MUTED)
    fig.for_each_annotation(lambda a: a.update(text=a.text.split("=")[-1]))
    return fig


def save(fig: go.Figure, name: str) -> None:
    fig.write_html(FIG / name, include_plotlyjs="cdn")
    print(f"  wrote {FIG / name}")


def implied(american: pd.Series) -> pd.Series:
    """American odds -> implied probability (with vig)."""
    a = american.astype(float)
    return np.where(a < 0, -a / (-a + 100), 100 / (a + 100))


def load() -> pd.DataFrame:
    cols = [
        "event_id",
        "kind",
        "book",
        "market",
        "player_key",
        "espn_game_id",
        "point",
        "over_price",
        "under_price",
        "actual",
        "margin",
        "result",
        "player_status",
    ]
    po = pd.read_parquet(TIDY / "prop_outcomes.parquet", columns=cols)
    po = po[(po.player_status == "played") & po.result.isin(["over", "under", "push"])]
    po = po[po.point > 0]  # one bad wynnbet row at -18.5
    for c in ["kind", "book", "market", "result"]:
        po[c] = po[c].astype(str)

    games = pd.read_parquet(TIDY / "games.parquet", columns=["espn_game_id", "season"])
    po = po.merge(games, on="espn_game_id", how="left")
    po["market"] = po.market.map(MARKETS)

    io, iu = implied(po.over_price), implied(po.under_price)
    po["p_over"] = io / (io + iu)  # no-vig over probability; NaN when one side missing
    return po


def main_lines(po: pd.DataFrame) -> pd.DataFrame:
    """Each book's main line: the ladder rung with no-vig over prob nearest 50%."""
    po = po.assign(dist=(po.p_over - 0.5).abs().fillna(1.0))
    idx = po.groupby(["book", *KEY], observed=True).dist.idxmin()
    return po.loc[idx].drop(columns="dist")


def consensus(main: pd.DataFrame) -> pd.DataFrame:
    """Median of the books' main lines per player-game-market-snapshot."""
    g = main.groupby(KEY, observed=True)
    c = g.agg(
        line=("point", "median"),
        actual=("actual", "first"),
        season=("season", "first"),
        n_books=("book", "nunique"),
    ).reset_index()
    c["margin"] = c.actual - c.line
    return c


def a1(cons: pd.DataFrame) -> None:
    print("\nA1. Margin vs consensus close line")
    close = cons[cons.kind == "close"]
    t = close.groupby("market").margin.agg(
        n="size", mean="mean", median="median", sd="std", skew="skew"
    )
    print(t.round(2).to_string())

    fig = px.histogram(
        close,
        x="margin",
        facet_col="market",
        facet_col_wrap=3,
        color="market",
        color_discrete_map=MARKET_COLOR,
        histnorm="probability",
        nbins=120,
        category_orders={"market": list(MARKETS.values())},
    )
    fig.add_vline(x=0, line_color=MUTED, line_dash="dot")
    fig.update_xaxes(range=[-25, 25])
    fig.update_yaxes(matches=None, title="")
    fig.update_traces(hovertemplate="margin %{x}<br>share %{y:.3f}<extra></extra>")
    save(style(fig, "Actual minus consensus close line"), "a1_margin_hist.html")

    close = close.assign(line_bin=close.line.round(0))
    sd = (
        close.groupby(["market", "line_bin"])
        .margin.agg(sd="std", n="size")
        .reset_index()
        .query("n >= 200")
    )
    fig = px.line(
        sd,
        x="line_bin",
        y="sd",
        color="market",
        markers=True,
        color_discrete_map=MARKET_COLOR,
        hover_data={"n": True},
        category_orders={"market": list(MARKETS.values())},
    )
    x = np.linspace(0.5, sd.line_bin.max(), 100)
    fig.add_scatter(
        x=x,
        y=np.sqrt(x),
        mode="lines",
        name="sqrt(line) (Poisson)",
        line=dict(color=MUTED, dash="dot", width=2),
        hoverinfo="skip",
    )
    fig.update_traces(line_width=2, marker_size=8, selector=dict(mode="lines+markers"))
    fig.update_layout(xaxis_title="consensus close line", yaxis_title="sd of margin")
    save(style(fig, "Margin spread vs line level"), "a1_sd_vs_line.html")


def a2(main: pd.DataFrame) -> None:
    print("\nA2. Over rate at books' main close lines (pushes excluded)")
    close = main[(main.kind == "close") & (main.result != "push")]
    close = close.assign(over=(close.result == "over").astype(float))
    print(f"  overall over rate {close.over.mean():.4f}  n={len(close):,}")

    t = close.groupby(["market", "season"]).over.agg(rate="mean", n="size").reset_index()
    print(t.pivot(index="market", columns="season", values="rate").round(3).to_string())
    fig = px.line(
        t,
        x="season",
        y="rate",
        color="market",
        markers=True,
        color_discrete_map=MARKET_COLOR,
        hover_data={"n": True},
        category_orders={"market": list(MARKETS.values())},
    )
    fig.add_hline(y=0.5, line_color=MUTED, line_dash="dot")
    fig.update_traces(line_width=2, marker_size=8)
    fig.update_xaxes(dtick=1)
    fig.update_layout(yaxis_title="over rate", yaxis_tickformat=".0%")
    save(style(fig, "Over rate at main close lines, by season"), "a2_over_rate_market_season.html")

    close = close.assign(line_bin=np.floor(close.point) + 0.5)
    t = (
        close.groupby(["market", "line_bin"])
        .over.agg(rate="mean", n="size")
        .reset_index()
        .query("n >= 500")
    )
    t["se"] = np.sqrt(t.rate * (1 - t.rate) / t.n)
    print(
        t[t.line_bin <= 6.5]
        .pivot(index="line_bin", columns="market", values="rate")
        .round(3)
        .to_string()
    )
    fig = px.scatter(
        t,
        x="line_bin",
        y="rate",
        color="market",
        error_y=1.96 * t.se,
        facet_col="market",
        facet_col_wrap=3,
        hover_data={"n": True},
        color_discrete_map=MARKET_COLOR,
        category_orders={"market": list(MARKETS.values())},
    )
    fig.add_hline(y=0.5, line_color=MUTED, line_dash="dot")
    fig.update_traces(marker_size=8)
    fig.update_xaxes(matches=None, title="", showticklabels=True)
    fig.update_yaxes(tickformat=".0%", title="")
    fig.update_layout(showlegend=False)
    save(style(fig, "Over rate by line level (95% CI)"), "a2_over_rate_by_line.html")

    # Calibration: realized over rate minus the no-vig price. This, not the raw over
    # rate, is the edge: a 0.5 line priced -250 should hit the over ~70% of the time.
    priced = close.dropna(subset=["p_over"]).assign(resid=lambda d: d.over - d.p_over)
    print("\n  over rate minus no-vig implied, by market")
    print(
        priced.groupby("market")
        .agg(
            over=("over", "mean"),
            implied=("p_over", "mean"),
            resid=("resid", "mean"),
            n=("over", "size"),
        )
        .round(4)
        .to_string()
    )
    t = (
        priced.groupby(["market", "line_bin"])
        .resid.agg(resid="mean", sd="std", n="size")
        .reset_index()
        .query("n >= 500")
    )
    t["se"] = t.sd / np.sqrt(t.n)
    print(
        t[t.line_bin <= 6.5]
        .pivot(index="line_bin", columns="market", values="resid")
        .round(3)
        .to_string()
    )
    fig = px.scatter(
        t,
        x="line_bin",
        y="resid",
        color="market",
        error_y=1.96 * t.se,
        facet_col="market",
        facet_col_wrap=3,
        hover_data={"n": True},
        color_discrete_map=MARKET_COLOR,
        category_orders={"market": list(MARKETS.values())},
    )
    fig.add_hline(y=0, line_color=MUTED, line_dash="dot")
    fig.update_traces(marker_size=8)
    fig.update_xaxes(matches=None, title="", showticklabels=True)
    fig.update_yaxes(tickformat="+.0%", title="")
    fig.update_layout(showlegend=False)
    save(
        style(fig, "Over rate minus no-vig implied, by line level (95% CI)"),
        "a2_calibration_by_line.html",
    )


def a3(main: pd.DataFrame, cons: pd.DataFrame) -> None:
    print("\nA3. Open vs close accuracy (player-games with both)")
    oc = cons[cons.kind.isin(["open", "close"])]
    both = oc.groupby(["event_id", "market", "player_key"]).kind.transform("nunique") == 2
    oc = oc[both].assign(abs_err=lambda d: d.margin.abs())
    t = oc.groupby(["market", "kind"]).abs_err.mean().unstack()[["open", "close"]]
    print(t.round(3).to_string())
    tl = t.reset_index().melt(id_vars="market", var_name="snapshot", value_name="mae")
    fig = px.bar(
        tl,
        x="market",
        y="mae",
        color="snapshot",
        barmode="group",
        color_discrete_sequence=SERIES[:2],
        category_orders={"market": list(MARKETS.values())},
    )
    fig.update_traces(
        marker_line_color=SURFACE,
        marker_line_width=2,
        hovertemplate="%{x}<br>MAE %{y:.3f}<extra></extra>",
    )
    fig.update_layout(yaxis_title="mean absolute error vs actual", xaxis_title="")
    save(style(fig, "Open vs close line accuracy"), "a3_open_vs_close_mae.html")

    print("\nA3. Book main close line minus consensus (mean, sd)")
    close = main[main.kind == "close"].merge(cons[cons.kind == "close"][KEY + ["line"]], on=KEY)
    close["offset"] = close.point - close.line
    t = (
        close.groupby(["book", "market"])
        .offset.agg(mean="mean", sd="std", n="size")
        .reset_index()
        .query("n >= 2000")
    )
    t["type"] = np.where(t.book.isin(DFS), "DFS", "sportsbook")
    print(t.pivot(index="book", columns="market", values="sd").round(2).to_string())
    order = t.groupby("book").sd.mean().sort_values().index.tolist()
    fig = px.scatter(
        t,
        x="sd",
        y="book",
        color="market",
        symbol="type",
        color_discrete_map=MARKET_COLOR,
        hover_data={"mean": ":.2f", "n": True},
        category_orders={"book": order, "market": list(MARKETS.values())},
    )
    fig.update_traces(marker_size=9, marker_line_color=SURFACE, marker_line_width=2)
    fig.update_layout(xaxis_title="sd of (book line - consensus)", yaxis_title="")
    save(style(fig, "How far each book sits from consensus at close"), "a3_book_offset.html")


def a4(main: pd.DataFrame, cons: pd.DataFrame) -> None:
    """Pregame line movement (open -> morning -> close), by opening-line window."""
    print("\nA4. Line movement open -> morning -> close (consensus lines)")
    w = cons.pivot_table(index=PG, columns="kind", values="line").dropna(subset=["open", "close"])
    actual = cons.groupby(PG).actual.first()
    w = w.join(actual).reset_index()
    w["move"] = w.close - w.open
    # Window = quintile of the opening line within each market. Colour by quintile
    # (same 5 colours in every panel); the actual line range goes in the hover.
    w["window"] = w.groupby("market").open.transform(
        lambda s: pd.qcut(s.rank(method="first"), 5, labels=WINDOWS).astype(str)
    )
    rng = w.groupby(["market", "window"]).open.agg(["min", "max"])
    rng = (rng["min"].astype(str) + "-" + rng["max"].astype(str)).rename("line_range")
    print(f"  player-games with open and close: {len(w):,}")

    t = w.groupby("market").move.agg(
        n="size",
        mean="mean",
        share_flat=lambda s: (s == 0).mean(),
        share_up=lambda s: (s > 0).mean(),
        share_down=lambda s: (s < 0).mean(),
        mean_abs=lambda s: s.abs().mean(),
    )
    print(t.round(3).to_string())

    # Path: mean line relative to open at each snapshot, per window.
    rows = []
    for snap in ["open", "morning", "close"]:
        sub = w.dropna(subset=[snap]) if snap == "morning" else w
        g = (sub[snap] - sub.open).groupby([sub.market, sub.window]).agg(["mean", "size"])
        rows.append(g.reset_index().assign(snapshot=snap))
    path = pd.concat(rows).rename(columns={"mean": "vs_open", "size": "n"})
    path = path.join(rng, on=["market", "window"])
    print(
        path[path.snapshot == "close"]
        .pivot(index="window", columns="market", values="vs_open")
        .reindex(WINDOWS)
        .round(3)
        .to_string()
    )
    fig = px.line(
        path,
        x="snapshot",
        y="vs_open",
        color="window",
        facet_col="market",
        facet_col_wrap=3,
        markers=True,
        hover_data={"n": True, "line_range": True},
        color_discrete_sequence=SERIES[:5],
        category_orders={"market": list(MARKETS.values()), "window": WINDOWS},
    )
    fig.add_hline(y=0, line_color=MUTED, line_dash="dot")
    fig.update_traces(line_width=2, marker_size=8)
    fig.update_xaxes(title="", showticklabels=True)
    fig.update_yaxes(matches=None, title="", showticklabels=True)
    fig.update_layout(legend_title_text="opening line window (within market)")
    save(style(fig, "Average line move from open, by opening-line window"), "a4_move_path.html")

    # Does the move predict the result? Over rate vs the open and vs the close line,
    # next to the over rate the price implied. Implied = mean no-vig p_over of the books
    # whose main line equals the consensus line; both rates use only those player-games.
    w["direction"] = np.select([w.move > 0, w.move < 0], ["up", "down"], "flat")
    res = []
    for ref in ["open", "close"]:
        px_ = main[main.kind == ref].merge(w[[*PG, ref]], on=PG)
        px_ = px_[(px_.point == px_[ref]) & px_.p_over.notna()]
        implied = px_.groupby(PG).p_over.mean().rename("p")
        d = w.join(implied, on=PG, how="inner")
        d = d[d.actual != d[ref]]
        d["over"] = (d.actual > d[ref]).astype(float)
        g = d.groupby(["market", "direction"]).agg(
            over_rate=("over", "mean"), implied=("p", "mean"), n=("over", "size")
        )
        res.append(g.reset_index().assign(vs=f"vs {ref} line"))
    res = pd.concat(res)
    res["se"] = np.sqrt(res.over_rate * (1 - res.over_rate) / res.n)
    res["gap"] = res.over_rate - res.implied
    print(
        res.set_index(["vs", "market", "direction"])[["over_rate", "implied", "gap", "n"]]
        .round(3)
        .to_string()
    )

    long = pd.concat(
        [
            res.assign(series="actual over rate", rate=res.over_rate, err=1.96 * res.se),
            res.assign(series="implied by no-vig price", rate=res.implied, err=0.0),
        ]
    )
    fig = px.scatter(
        long,
        x="direction",
        y="rate",
        color="series",
        error_y="err",
        facet_col="market",
        facet_row="vs",
        hover_data={"n": True, "gap": ":+.3f", "err": False},
        color_discrete_map={"actual over rate": SERIES[0], "implied by no-vig price": MUTED},
        category_orders={
            "market": list(MARKETS.values()),
            "direction": ["down", "flat", "up"],
            "vs": ["vs open line", "vs close line"],
        },
    )
    fig.update_traces(marker_size=9, selector=dict(name="actual over rate"))
    fig.update_traces(
        marker=dict(symbol="line-ew-open", size=22, line=dict(width=3, color=MUTED)),
        selector=dict(name="implied by no-vig price"),
    )
    fig.update_xaxes(title="", showticklabels=True)
    fig.update_yaxes(tickformat=".0%", title="")
    fig.update_layout(height=650)
    save(
        style(fig, "Over rate vs price-implied rate, by direction of pregame line move"),
        "a4_move_vs_result.html",
    )


def main() -> None:
    FIG.mkdir(parents=True, exist_ok=True)
    po = load()
    main_ = main_lines(po)
    cons = consensus(main_)
    print(f"rows {len(po):,}  main lines {len(main_):,}  consensus {len(cons):,}")
    a1(cons)
    a2(main_)
    a3(main_, cons)
    a4(main_, cons)


if __name__ == "__main__":
    main()
