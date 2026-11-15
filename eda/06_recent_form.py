"""EDA B8: the line against the player's recent average, by market.

Catalog entry B8 in docs/eda_catalog.md. Regular season, close snapshot. For each
player-game and market, compare the consensus line with the player's average of that
stat over his previous 10 games played (never the game itself):

    line vs average = line / 10-game average - 1     (-20% = line is a fifth below it)

No model is fitted here, so every season can be used. B9 first hinted at the effect in
2025-26 data, so earlier seasons are reported separately as an independent check.

    uv run --group eda python eda/06_recent_form.py
"""

import importlib

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from charts import DFS, MAIN_NOTE, MUTED, SERIES, TIDY, save, style, titled
from plotly.subplots import make_subplots

base = importlib.import_module("01_outcome_profile")  # load, main_lines, MARKETS, PG

WINDOW, MIN_GAMES = 10, 5
LONG, LONG_MIN = 30, 15
MIN_AVG = 0.5  # 10-game average below this: ratio is not meaningful
MIN_BAND = 300
STATS = {
    "Points": ["pts"],
    "Rebounds": ["reb"],
    "Assists": ["ast"],
    "Threes": ["fg3m"],
    "Pts+Reb": ["pts", "reb"],
    "Pts+Reb+Ast": ["pts", "reb", "ast"],
}
EDGES = [-0.2, -0.1, 0.1, 0.2]  # each band is [lo, hi)
LABELS = ["20%+ below", "10 to 20% below", "within 10%", "10 to 20% above", "20%+ above"]
PERIODS = {"2023-24 and 2024-25": [2024, 2025], "2025-26 onward": [2026, 2027]}
STREAK_EDGES = [-0.1, 0.1]
STREAK_LABELS = ["cold (10-game avg 10%+ below 30-game)", "steady", "hot (10%+ above)"]
RATIO_NOTE = (
    "x = consensus close line relative to the player's average of that stat over his"
    " previous 10 games played (at least 5; never the game itself): '20%+ below' = the line"
    " is at least a fifth lower than his recent average. Each group includes its lower edge."
)
UNIT_NOTE = (
    "Unit = one player-game in one market, regular season, close snapshot; over rate and"
    " price are averaged over the books pricing it (pushes excluded). y = over rate minus"
    " mean no-vig over probability; above 0 = overs beat the price."
)


def recent_averages() -> pd.DataFrame:
    """Long table: player-game x market, 10-game and 30-game averages before the game."""
    cols = sorted({c for stat in STATS.values() for c in stat})
    bx = pd.read_parquet(
        TIDY / "box_scores.parquet",
        columns=["espn_game_id", "player_key", "did_not_play", "minutes", *cols],
    )
    gm = pd.read_parquet(TIDY / "games.parquet", columns=["espn_game_id", "tip_utc"])
    bx = bx[~bx.did_not_play & (bx.minutes > 0)].merge(gm, on="espn_game_id")
    bx = bx.sort_values(["player_key", "tip_utc"]).reset_index(drop=True)
    out = []
    for market, stat_cols in STATS.items():
        value = bx[stat_cols].sum(axis=1)
        prev = value.groupby(bx.player_key).shift()
        g = prev.groupby(bx.player_key)
        out.append(
            pd.DataFrame(
                {
                    "espn_game_id": bx.espn_game_id,
                    "player_key": bx.player_key,
                    "market": market,
                    "avg10": g.rolling(WINDOW, min_periods=MIN_GAMES)
                    .mean()
                    .reset_index(level=0, drop=True),
                    "avg30": g.rolling(LONG, min_periods=LONG_MIN)
                    .mean()
                    .reset_index(level=0, drop=True),
                }
            )
        )
    return pd.concat(out).dropna(subset=["avg10"])


def player_games() -> pd.DataFrame:
    """One row per player-game-market at the close, with the over's return at sportsbooks."""
    main = base.main_lines(base.load())
    d = main[(main.kind == "close") & (main.phase == "regular season") & main.p_over.notna()]
    d = d.assign(over=np.where(d.result == "push", np.nan, (d.result == "over").astype(float)))
    o = d.over_price.astype(float)
    win = np.where(o < 0, 100 / -o, o / 100)
    d["over_profit"] = np.select([d.result == "over", d.result == "push"], [win, 0.0], -1.0)
    u = d.under_price.astype(float)
    win_u = np.where(u < 0, 100 / -u, u / 100)
    d["under_profit"] = np.select([d.result == "under", d.result == "push"], [win_u, 0.0], -1.0)
    # DFS prices are placeholders, not payouts.
    d.loc[d.book.isin(DFS), ["over_profit", "under_profit"]] = np.nan
    pg = (
        d.groupby([*base.PG, "espn_game_id"], observed=True)
        .agg(
            line=("point", "median"),
            actual=("actual", "first"),
            season=("season", "first"),
            over=("over", "mean"),
            p=("p_over", "mean"),
            over_return=("over_profit", "mean"),
            under_return=("under_profit", "mean"),
        )
        .reset_index()
    )
    pg["gap"] = pg.over - pg.p
    return pg.dropna(subset=["gap"])


def summarize(d: pd.DataFrame, keys: list[str]) -> pd.DataFrame:
    t = d.groupby(keys, observed=True).agg(
        gap=("gap", "mean"),
        sd=("gap", "std"),
        over_return=("over_return", "mean"),
        ret_sd=("over_return", "std"),
        under_return=("under_return", "mean"),
        under_sd=("under_return", "std"),
        n=("gap", "size"),
        line=("line", "mean"),
        avg10=("avg10", "mean"),
        actual=("actual", "mean"),
    )
    t["se"] = t.pop("sd") / np.sqrt(t.n)
    t["return_se"] = t.pop("ret_sd") / np.sqrt(t.n)
    t["under_se"] = t.pop("under_sd") / np.sqrt(t.n)
    return t


def by_market_chart(d: pd.DataFrame) -> None:
    t = summarize(d, ["market", "period", "band"])
    print("\nB8 gap vs price by line-vs-average band, market and period")
    print(t.round(3).to_string())
    markets = list(STATS)
    fig = make_subplots(
        rows=2, cols=3, subplot_titles=markets, shared_yaxes=True, vertical_spacing=0.3
    )
    for i, market in enumerate(markets):
        for j, period in enumerate(PERIODS):
            s = t.loc[(market, period)]
            s = s[s.n >= MIN_BAND]
            fig.add_trace(
                go.Scatter(
                    x=s.index.astype(str),
                    y=s.gap,
                    error_y=dict(type="data", array=1.96 * s.se, color=SERIES[j]),
                    customdata=s[["n", "line", "avg10", "actual", "over_return"]],
                    name=period,
                    legendgroup=period,
                    showlegend=i == 0,
                    mode="markers",
                    marker=dict(color=SERIES[j], size=9),
                    hovertemplate=(
                        f"{market}, {period}<br>line %{{x}} his 10-game average<br>over rate"
                        " minus price: %{y:+.1%}<br>average line %{customdata[1]:.1f},"
                        " 10-game average %{customdata[2]:.1f}, actual %{customdata[3]:.1f}"
                        "<br>return on overs at sportsbooks: %{customdata[4]:+.1%}"
                        "<br>player-games: %{customdata[0]:,}<extra></extra>"
                    ),
                ),
                row=i // 3 + 1,
                col=i % 3 + 1,
            )
    fig.add_hline(y=0, line_color=MUTED, line_dash="dot")
    fig.update_xaxes(categoryorder="array", categoryarray=LABELS, tickangle=-25)
    fig.update_yaxes(tickformat="+.0%")
    fig.update_layout(height=820)
    title = titled(
        "Line below the player's recent average: do overs beat the price?",
        RATIO_NOTE,
        UNIT_NOTE + f" Bars = 95% CI; groups under {MIN_BAND} left out.",
        "The two colours are separate seasons, so one is a check on the other. " + MAIN_NOTE,
    )
    save(style(fig, title), "b8_line_vs_average_gap.html")


def streak_chart(d: pd.DataFrame) -> None:
    """Is it hot streaks? Split by 10-game average relative to the 30-game average."""
    d = d.dropna(subset=["avg30"])
    d = d[d.avg30 >= MIN_AVG].assign(
        streak=lambda x: pd.cut(
            x.avg10 / x.avg30 - 1,
            [-np.inf, *STREAK_EDGES, np.inf],
            labels=STREAK_LABELS,
            right=False,
        )
    )
    t = summarize(d, ["streak", "band"])
    print("\nB8 gap vs price by streak and line-vs-average band (all markets, all seasons)")
    print(t.round(3).to_string())
    print(pd.crosstab(d.streak, d.band, normalize="index").round(3).to_string())
    worst = d[(d.streak == STREAK_LABELS[2]) & (d.band == LABELS[-1])]
    print("\nB8 hot players with the line 20%+ above the 10-game average: by period, by market")
    cols = ["gap", "se", "under_return", "under_se", "n"]
    print(summarize(worst, ["period"])[cols].round(3).to_string())
    print(summarize(worst, ["market"])[cols].round(3).to_string())
    games = worst.groupby("period").espn_game_id.nunique()
    print(
        "distinct games:",
        games.to_dict(),
        " distinct player-games:",
        len(worst.drop_duplicates(["espn_game_id", "player_key"])),
    )
    fig = go.Figure()
    for j, streak in enumerate(STREAK_LABELS):
        s = t.loc[streak]
        s = s[s.n >= MIN_BAND]
        fig.add_trace(
            go.Scatter(
                x=s.index.astype(str),
                y=s.gap,
                error_y=dict(type="data", array=1.96 * s.se, color=SERIES[j]),
                customdata=s[["n", "over_return"]],
                name=streak,
                mode="markers",
                marker=dict(color=SERIES[j], size=10),
                hovertemplate=(
                    f"{streak}<br>line %{{x}} his 10-game average<br>over rate minus price:"
                    " %{y:+.1%}<br>return on overs at sportsbooks: %{customdata[1]:+.1%}"
                    "<br>player-game-markets: %{customdata[0]:,}<extra></extra>"
                ),
            )
        )
    fig.add_hline(y=0, line_color=MUTED, line_dash="dot")
    fig.update_xaxes(
        categoryorder="array",
        categoryarray=LABELS,
        title_text="consensus close line relative to the player's 10-game average",
    )
    fig.update_yaxes(tickformat="+.0%", title_text="over rate minus price-implied probability")
    fig.update_layout(height=560)
    title = titled(
        "Is it hot streaks? The same test split by recent form",
        "Colour = the player's 10-game average relative to his 30-game average (at least 15"
        " of the 30): hot = 10%+ above, cold = 10%+ below, steady = in between. All six"
        " markets and all seasons pooled.",
        RATIO_NOTE,
        UNIT_NOTE + f" Bars = 95% CI across player-game-markets; groups under {MIN_BAND} left out.",
    )
    save(style(fig, title), "b8_streak_split.html")


def main() -> None:
    pg = player_games().merge(recent_averages(), on=["espn_game_id", "player_key", "market"])
    pg = pg[pg.avg10 >= MIN_AVG].copy()
    pg["ratio"] = pg.line / pg.avg10 - 1
    pg["band"] = pd.cut(pg.ratio, [-np.inf, *EDGES, np.inf], labels=LABELS, right=False)
    pg["period"] = pg.season.map({s: p for p, ss in PERIODS.items() for s in ss})
    pg = pg.dropna(subset=["period"])
    print(f"player-game-markets: {len(pg):,}")
    print(pd.crosstab(pg.market, pg.band, normalize="index").round(3).to_string())
    print("\nB8 all markets pooled, by period")
    print(summarize(pg, ["period", "band"]).round(3).to_string())
    by_market_chart(pg)
    streak_chart(pg)


if __name__ == "__main__":
    main()
