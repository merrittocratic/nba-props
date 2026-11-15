"""EDA Part A: outcome profile of player props vs the market line.

Catalog entries A1-A4 and A6 in docs/eda_catalog.md. Writes Plotly HTML to eda/figures/ and
prints the summary tables used to fill in the catalog.

    uv run --group eda python eda/01_outcome_profile.py
"""

import textwrap
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from plotly.subplots import make_subplots

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
# Seasons the data covers only in part (data starts 2023-05-03; last pull 2026-10-29).
SEASON_NOTES = {2023: " (playoffs only)", 2027: " (first weeks)"}
PHASES = {2: "regular season", 3: "postseason", 5: "postseason"}  # play-in with playoffs
# Shared small print: what a consensus line is and what a book's main line is.
CONSENSUS_NOTE = "Consensus line = median of the books' main lines for that player and market."
MAIN_NOTE = (
    "Main line = the book's line priced nearest 50/50; no-vig probability = over price"
    " rescaled so over + under = 100%."
)

# Opening-line bands for A4: market -> (inner edges, labels). Each band is [lo, hi): it
# includes its lower edge. Fixed ranges, not quantiles: prop lines take few distinct
# values (17 for threes), so equal-count groups would split one line value across groups.
BANDS = {
    "Points": ([10, 15, 20, 25], ["under 10", "10 to <15", "15 to <20", "20 to <25", "25+"]),
    "Rebounds": ([3, 5, 7, 9], ["under 3", "3 to <5", "5 to <7", "7 to <9", "9+"]),
    "Assists": ([2, 4, 6, 8], ["under 2", "2 to <4", "4 to <6", "6 to <8", "8+"]),
    "Threes": ([1, 2, 3], ["under 1", "1 to <2", "2 to <3", "3+"]),
    "Pts+Reb": ([15, 20, 25, 30], ["under 15", "15 to <20", "20 to <25", "25 to <30", "30+"]),
    "Pts+Reb+Ast": (
        [15, 20, 25, 30, 35],
        ["under 15", "15 to <20", "20 to <25", "25 to <30", "30 to <35", "35+"],
    ),
}


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


def season_label(season: float) -> str:
    """ESPN labels a season by its end year: 2024 -> '2023-24'."""
    y = int(season)
    return f"{y - 1}-{y % 100:02d}" + SEASON_NOTES.get(y, "")


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

    games = pd.read_parquet(
        TIDY / "games.parquet", columns=["espn_game_id", "season", "season_type"]
    )
    po = po.merge(games, on="espn_game_id", how="left")
    # ESPN season_type: 2 regular season, 3 playoffs, 5 play-in. Preseason (1) never
    # appears: the Odds API lists it under a different sport key, which we don't pull.
    po["phase"] = po.pop("season_type").map(PHASES)
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
        category_orders={"market": list(MARKETS.values())},
    )
    # One-unit bins on whole numbers: a half-point line gives margins of ..., -0.5, +0.5,
    # ..., so each bin holds exactly one of them (automatic bins would hold uneven counts).
    fig.update_traces(
        xbins=dict(start=-25, end=25, size=1),
        hovertemplate="margin %{x}<br>share %{y:.3f}<extra></extra>",
        showlegend=False,
    )
    fig.add_vline(x=0, line_color=MUTED, line_dash="dot")
    fig.update_xaxes(range=[-25, 25], showticklabels=True)
    fig.update_yaxes(matches=None, title="", tickformat=".0%", showticklabels=True)
    title = titled(
        "Margin: actual stat minus consensus close line",
        "One count per player-game (players who played). x = margin in stat units, 1-unit"
        " bins; y = share of player-games; y scale differs by panel. Right of 0 = went over.",
        CONSENSUS_NOTE + " Tails beyond +/-25 (under 0.6% of any market) are not shown.",
    )
    fig = style(fig, title)
    save(fig, "a1_margin_hist.html")

    # floor + 0.5, not round(): numpy rounds halves to even (2.5 -> 2, 3.5 -> 4), which
    # would pool two different lines into each even number.
    close = close.assign(line_bin=np.floor(close.line) + 0.5)
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
    fig.update_layout(
        xaxis_title="consensus close line (each half-point line is its own group)",
        yaxis_title="standard deviation of margin (stat units)",
    )
    title = titled(
        "How spread out results are, by line level",
        "Each dot = all player-games at one consensus close line (e.g. 12.5; a rare"
        " whole-number consensus such as 12.0 is grouped with 12.5). Lines with under 200"
        " player-games are left out.",
        "y = standard deviation of (actual - line). Dotted curve = sqrt(line), the spread a"
        " pure Poisson count would have. " + CONSENSUS_NOTE,
    )
    save(style(fig, title), "a1_sd_vs_line.html")


def a2(main: pd.DataFrame) -> None:
    print("\nA2. Over rate at books' main close lines (pushes excluded)")
    close = main[(main.kind == "close") & (main.result != "push")]
    close = close.assign(over=(close.result == "over").astype(float))
    print(f"  overall over rate {close.over.mean():.4f}  n={len(close):,}")

    t = close.groupby(["market", "season"]).over.agg(rate="mean", n="size").reset_index()
    print(t.pivot(index="market", columns="season", values="rate").round(3).to_string())
    t = t.sort_values("season").assign(season_name=lambda d: d.season.map(season_label))
    fig = px.line(
        t,
        x="season_name",
        y="rate",
        color="market",
        markers=True,
        color_discrete_map=MARKET_COLOR,
        hover_data={"n": True},
        category_orders={
            "market": list(MARKETS.values()),
            "season_name": t.season_name.unique().tolist(),
        },
    )
    fig.add_hline(y=0.5, line_color=MUTED, line_dash="dot")
    fig.update_traces(line_width=2, marker_size=8)
    fig.update_layout(
        yaxis_title="over rate (share of book-lines that went over)",
        yaxis_tickformat=".0%",
        xaxis_title="season (preseason, regular season, play-in and playoffs pooled)",
    )
    title = titled(
        "Over rate at books' main close lines, by season",
        "Unit = one book's main line for one player-game at the close snapshot (so a player"
        " priced by 8 books counts 8 times). Pushes excluded. Dotted line = 50%.",
        MAIN_NOTE + " The first and last seasons are partial, so their points are noisy.",
    )
    save(style(fig, title), "a2_over_rate_market_season.html")

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
    by_line_note = (
        "Each dot = all book-lines at one main line value (x, in stat units; e.g. every"
        " 2.5). Values with under 500 book-lines are left out. Bars = 95% CI, too narrow:"
        " books pricing the same player-game are not independent."
    )
    title = titled(
        "Over rate by line level",
        by_line_note,
        "y = share of book-lines that went over (pushes excluded); dotted line = 50%. " + MAIN_NOTE,
    )
    save(style(fig, title), "a2_over_rate_by_line.html")

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
    title = titled(
        "Over rate minus the price-implied over probability, by line level",
        by_line_note,
        "y = actual over rate minus mean no-vig over probability, in percentage points."
        " Below 0 = overs hit less often than priced. Only book-lines with both prices. "
        + MAIN_NOTE,
    )
    save(style(fig, title), "a2_calibration_by_line.html")


def a3(main: pd.DataFrame, cons: pd.DataFrame) -> None:
    print("\nA3. Open vs close accuracy (player-games with both)")
    oc = cons[cons.kind.isin(["open", "close"])]
    both = oc.groupby(["event_id", "market", "player_key"]).kind.transform("nunique") == 2
    oc = oc[both].assign(abs_err=lambda d: d.margin.abs())
    t = oc.groupby(["market", "kind"]).abs_err.mean().unstack()[["open", "close"]]
    print(t.round(3).to_string())
    # Plot the change, not the two levels: open and close differ by about 1%, which
    # side-by-side bars from zero can't show, and the markets' error sizes differ 4x.
    tl = t.assign(
        change=t.close / t.open - 1,
        n=oc[oc.kind == "close"].groupby("market").size(),
    ).reindex(list(MARKETS.values()))
    tl["label"] = [f"{o:.3f} to {c:.3f}" for o, c in zip(tl.open, tl.close, strict=True)]
    fig = go.Figure(
        go.Bar(
            x=tl.index,
            y=tl.change,
            text=tl.label,
            textposition="outside",
            textfont=dict(color=TEXT),
            marker=dict(color=SERIES[0], line=dict(color=SURFACE, width=2)),
            width=0.5,
            customdata=tl[["open", "close", "n"]],
            hovertemplate=(
                "%{x}<br>open error %{customdata[0]:.3f}, close error %{customdata[1]:.3f}"
                "<br>change %{y:+.2%}<br>player-games: %{customdata[2]:,}<extra></extra>"
            ),
        )
    )
    fig.add_hline(y=0, line_color=MUTED)
    fig.update_layout(
        yaxis_title="change in average miss, open to close",
        yaxis_tickformat="+.1%",
        xaxis_title="",
    )
    title = titled(
        "Is the close line more accurate than the open line?",
        "Average miss = mean of |actual - consensus line| in stat units, over player-games"
        " that have both an open and a close consensus line.",
        "Bar = close miss / open miss - 1; below 0 = the close is more accurate. Bar labels"
        " give the average miss at open and at close. " + CONSENSUS_NOTE,
    )
    save(style(fig, title), "a3_open_vs_close_mae.html")

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
    fig.update_layout(
        xaxis_title="standard deviation of (book's main line - consensus line), stat units",
        yaxis_title="",
        height=620,
    )
    title = titled(
        "How far each book's line sits from consensus at close",
        "Each dot = one book in one market: the spread of (its main close line - consensus"
        " close line) over player-games. Further right = disagrees with the other books"
        " more often or by more.",
        "Books are Odds API keys (williamhill_us = Caesars), sorted by average spread;"
        " book-markets under 2,000 lines left out. The consensus includes the book itself. "
        + CONSENSUS_NOTE,
    )
    save(style(fig, title), "a3_book_offset.html")


def a4(main: pd.DataFrame, cons: pd.DataFrame) -> None:
    """Pregame line movement (open -> morning -> close), by opening-line band."""
    print("\nA4. Line movement open -> morning -> close (consensus lines)")
    w = cons.pivot_table(index=PG, columns="kind", values="line").dropna(subset=["open", "close"])
    actual = cons.groupby(PG).actual.first()
    w = w.join(actual).reset_index()
    w["move"] = w.close - w.open
    # Band = fixed range of the consensus opening line (BANDS, one set per market).
    # A band is a property of the line that night, not of the player: the same player
    # lands in different bands on different nights.
    w["band"] = ""
    for market, (edges, labels) in BANDS.items():
        m = w.market == market
        w.loc[m, "band"] = pd.cut(
            w.loc[m, "open"], [0, *edges, np.inf], labels=labels, right=False
        ).astype(str)
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

    # Path: mean line relative to open at each snapshot, per band.
    rows = []
    for snap in ["open", "morning", "close"]:
        sub = w.dropna(subset=[snap]) if snap == "morning" else w
        g = (sub[snap] - sub.open).groupby([sub.market, sub.band]).agg(["mean", "size"])
        rows.append(g.reset_index().assign(snapshot=snap))
    path = pd.concat(rows).rename(columns={"mean": "vs_open", "size": "n"})
    summary = w.groupby(["market", "band"]).agg(
        n=("move", "size"),
        players=("player_key", "nunique"),
        median_open=("open", "median"),
        move_to_close=("move", "mean"),
        share_moved=("move", lambda s: (s != 0).mean()),
    )
    order = [(mk, b) for mk, (_, labels) in BANDS.items() for b in labels]
    print(summary.reindex(order).round(3).to_string())

    # One panel and one legend per market, because the bands differ by market.
    names = list(BANDS)
    fig = make_subplots(rows=2, cols=3, subplot_titles=names, horizontal_spacing=0.13)
    for i, market in enumerate(names):
        r, c = divmod(i, 3)
        legend = "legend" if i == 0 else f"legend{i + 1}"
        for j, band in enumerate(BANDS[market][1]):
            d = path[(path.market == market) & (path.band == band)]
            d = d.set_index("snapshot").reindex(["open", "morning", "close"]).reset_index()
            fig.add_trace(
                go.Scatter(
                    x=d.snapshot,
                    y=d.vs_open,
                    customdata=d[["n"]],
                    name=band,
                    legend=legend,
                    mode="lines+markers",
                    line=dict(color=SERIES[j], width=2),
                    marker=dict(size=8),
                    hovertemplate=(
                        f"{market}, opening line {band}<br>%{{x}}: %{{y:+.3f}} vs open"
                        "<br>player-games: %{customdata[0]:,}<extra></extra>"
                    ),
                ),
                row=r + 1,
                col=c + 1,
            )
        xd = fig.layout["xaxis" if i == 0 else f"xaxis{i + 1}"].domain
        yd = fig.layout["yaxis" if i == 0 else f"yaxis{i + 1}"].domain
        fig.layout[legend] = dict(
            x=xd[1] + 0.004,
            y=yd[1],
            xanchor="left",
            yanchor="top",
            title_text="opening line",
            font_size=11,
            title_font_size=11,
            bgcolor="rgba(0,0,0,0)",
        )
    fig.add_hline(y=0, line_color=MUTED, line_dash="dot")
    title = titled(
        "Average line move from open, by opening-line band",
        "y = consensus line minus the same player's consensus opening line, in stat units,"
        " averaged over player-games (unmoved lines count as 0). Band = range of the opening"
        " line (each includes its lower edge); y-axis scale differs by panel.",
        CONSENSUS_NOTE,
    )
    fig = style(fig, title)
    for i in range(len(names)):
        fig.layout["legend" if i == 0 else f"legend{i + 1}"].title.text = "opening line"
    fig.update_layout(height=720, margin_r=90)
    save(fig, "a4_move_path.html")

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
    fig.update_layout(height=700)
    title = titled(
        "Over rate vs price-implied rate, by direction of the pregame line move",
        "Direction = consensus close line vs consensus open line for the same player-game:"
        " down, flat (equal) or up. Top row scores results against the open line, bottom"
        " row against the close line.",
        "Dot = actual over rate (pushes excluded, 95% CI). Dash = mean no-vig over"
        " probability at the books whose main line equals the consensus line; player-games"
        " with no such book are left out.",
        CONSENSUS_NOTE + " " + MAIN_NOTE,
    )
    save(style(fig, title), "a4_move_vs_result.html")


def a6(main: pd.DataFrame) -> None:
    """Regular season vs postseason: over rate against the no-vig price, and under ROI."""
    print("\nA6. Regular season vs postseason (close, books' main lines)")
    d = main[(main.kind == "close") & main.p_over.notna() & main.phase.notna()].copy()
    d["over"] = np.where(d.result == "push", np.nan, (d.result == "over").astype(float))
    # Profit per 1 staked on the under at that sportsbook's price (push = 0).
    u = d.under_price.astype(float)
    win = np.where(u < 0, 100 / -u, u / 100)
    d["under_profit"] = np.select([d.result == "under", d.result == "push"], [win, 0.0], -1.0)
    # DFS sites show a placeholder price (-137 both sides), not a payout: leave them out.
    d.loc[d.book.isin(DFS), "under_profit"] = np.nan
    # One row per player-game (mean over its books), so books pricing the same
    # player-game are not counted as independent.
    pg = (
        d.groupby([*PG, "phase", "season"], observed=True)
        .agg(over=("over", "mean"), p=("p_over", "mean"), roi=("under_profit", "mean"))
        .reset_index()
        .dropna(subset=["over"])
    )
    pg["gap"] = pg.over - pg.p

    def table(keys: list[str]) -> pd.DataFrame:
        g = pg.groupby(keys).agg(
            over=("over", "mean"),
            implied=("p", "mean"),
            gap=("gap", "mean"),
            gap_sd=("gap", "std"),
            under_roi=("roi", "mean"),
            roi_sd=("roi", "std"),
            n=("gap", "size"),
        )
        g["gap_se"] = g.pop("gap_sd") / np.sqrt(g.n)
        g["roi_se"] = g.pop("roi_sd") / np.sqrt(g.n)
        return g

    for keys in (["phase"], ["phase", "market"], ["phase", "season"]):
        print(table(keys).round(4).to_string())

    t = table(["market", "phase"]).reset_index()
    fig = px.scatter(
        t,
        x="gap",
        y="market",
        color="phase",
        error_x=1.96 * t.gap_se,
        color_discrete_map={"regular season": SERIES[0], "postseason": SERIES[1]},
        hover_data={"n": ":,", "over": ":.3f", "implied": ":.3f", "under_roi": ":+.3f"},
        category_orders={
            "market": list(MARKETS.values()),
            "phase": ["regular season", "postseason"],
        },
    )
    fig.add_vline(x=0, line_color=MUTED, line_dash="dot")
    fig.update_traces(marker_size=10)
    fig.update_layout(
        xaxis_title="actual over rate minus no-vig over probability (percentage points)",
        xaxis_tickformat="+.0%",
        yaxis_title="",
        height=520,
    )
    title = titled(
        "Do overs fall short of the price more in the postseason?",
        "Each dot = all player-games in one market and phase, at books' main close lines."
        " x = share that went over minus the mean no-vig over probability; left of 0 ="
        " overs hit less often than priced. Bars = 95% CI across player-games (each"
        " player-game is the mean of its books; pushes excluded).",
        "Postseason = play-in and playoffs, 2023 to 2026. Preseason is not in the data. "
        + MAIN_NOTE,
    )
    save(style(fig, title), "a6_phase_gap.html")


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
    a6(main_)


if __name__ == "__main__":
    main()
