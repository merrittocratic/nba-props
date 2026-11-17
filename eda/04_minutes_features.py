"""EDA B3: minutes features (level, volatility, trend) against the result and the price.

Catalog entry B3 in docs/eda_catalog.md. Regular season, close snapshot. Every feature
uses only the player's games before the game being priced (no leakage):

    level      = mean minutes over the previous 10 games played
    volatility = standard deviation of minutes over those 10 games
    trend      = mean of the previous 3 games minus mean of the previous 10

    uv run --group eda python eda/04_minutes_features.py
"""

import importlib

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from charts import MAIN_NOTE, MUTED, SERIES, TIDY, save, style, titled
from plotly.subplots import make_subplots

base = importlib.import_module("01_outcome_profile")  # load, main_lines, MARKETS, PG

WINDOW = 10  # previous games played
SHORT = 3
MIN_GAMES = 5  # fewer previous games than this: no feature
MIN_BAND = 300  # player-games per dot
# Feature bands: (inner edges, labels); each band is [lo, hi), in minutes.
FEATURES = {
    "level": (
        "average minutes, previous 10 games",
        [18, 24, 30, 34],
        ["under 18", "18 to <24", "24 to <30", "30 to <34", "34+"],
    ),
    "volatility": (
        "standard deviation of minutes, previous 10 games",
        [3, 5, 7, 9],
        ["under 3", "3 to <5", "5 to <7", "7 to <9", "9+"],
    ),
    "trend": (
        "last 3 games minus last 10 games, average minutes",
        [-4, -2, 2, 4],
        ["down 4+", "down 2 to 4", "within 2", "up 2 to 4", "up 4+"],
    ),
}
FEATURE_NOTE = (
    f"Minutes features use only the player's previous {WINDOW} games played before this game"
    f" (at least {MIN_GAMES}; games he sat out are skipped, seasons are not separated)."
)
UNIT_NOTE = (
    "Unit = one player-game in one market, regular season, close snapshot; over rate and"
    " price are averaged over the books pricing it (pushes excluded)."
)


def minutes_features() -> pd.DataFrame:
    """One row per player-game played, with features from his earlier games only."""
    bx = pd.read_parquet(
        TIDY / "box_scores.parquet",
        columns=["espn_game_id", "player_key", "did_not_play", "minutes", "starter"],
    )
    gm = pd.read_parquet(TIDY / "games.parquet", columns=["espn_game_id", "tip_utc"])
    bx = bx[~bx.did_not_play & (bx.minutes > 0)].merge(gm, on="espn_game_id")
    bx = bx.sort_values(["player_key", "tip_utc"])
    prev = bx.groupby("player_key").minutes.shift()  # exclude the game itself
    g = prev.groupby(bx.player_key)
    roll = g.rolling(WINDOW, min_periods=MIN_GAMES)
    bx["level"] = roll.mean().reset_index(level=0, drop=True)
    bx["volatility"] = roll.std().reset_index(level=0, drop=True)
    short = g.rolling(SHORT, min_periods=SHORT).mean().reset_index(level=0, drop=True)
    bx["trend"] = short - bx.level
    bx["minutes_vs_level"] = bx.minutes - bx.level
    return bx.dropna(subset=["level", "volatility", "trend"])[
        [
            "espn_game_id",
            "player_key",
            "minutes",
            "level",
            "volatility",
            "trend",
            "minutes_vs_level",
        ]
    ]


def player_games(phase: str = "regular season") -> pd.DataFrame:
    """One row per player-game-market at the close: margin, over rate, price."""
    po = base.load()
    main = base.main_lines(po)
    d = main[(main.kind == "close") & (main.phase == phase) & main.p_over.notna()]
    d = d.assign(over=np.where(d.result == "push", np.nan, (d.result == "over").astype(float)))
    pg = (
        d.groupby([*base.PG, "espn_game_id"], observed=True)
        .agg(
            line=("point", "median"),
            actual=("actual", "first"),
            over=("over", "mean"),
            p=("p_over", "mean"),
        )
        .reset_index()
    )
    pg["margin"] = pg.actual - pg.line
    pg["gap"] = pg.over - pg.p
    return pg


def banded(df: pd.DataFrame, feature: str) -> pd.Series:
    _, edges, labels = FEATURES[feature]
    return pd.cut(df[feature], [-np.inf, *edges, np.inf], labels=labels, right=False)


def gap_by_band(df: pd.DataFrame, feature: str) -> pd.DataFrame:
    d = df.dropna(subset=["gap"]).assign(band=banded(df, feature))
    t = d.groupby(["market", "band"], observed=True).agg(
        gap=("gap", "mean"),
        sd=("gap", "std"),
        n=("gap", "size"),
        margin=("margin", "mean"),
        margin_sd=("margin", "std"),
        played_vs_level=("minutes_vs_level", "mean"),
    )
    t["se"] = t.sd / np.sqrt(t.n)
    return t.drop(columns="sd")


def gap_chart(df: pd.DataFrame, feature: str) -> None:
    """Over rate minus price by feature band, one panel per market."""
    desc, _, labels = FEATURES[feature]
    t = gap_by_band(df, feature)
    print(f"\nB3 {feature}: {desc}")
    print(t.round(3).to_string())
    markets = list(base.MARKETS.values())
    fig = make_subplots(
        rows=2, cols=3, subplot_titles=markets, shared_yaxes=True, vertical_spacing=0.16
    )
    for i, market in enumerate(markets):
        s = t.loc[market]
        s = s[s.n >= MIN_BAND]
        fig.add_trace(
            go.Scatter(
                x=s.index.astype(str),
                y=s.gap,
                error_y=dict(type="data", array=1.96 * s.se, color=SERIES[0]),
                customdata=s[["n", "margin", "played_vs_level"]],
                mode="markers",
                marker=dict(color=SERIES[0], size=9),
                showlegend=False,
                hovertemplate=(
                    f"{market}, {feature} %{{x}}<br>over rate minus price: %{{y:+.1%}}"
                    "<br>average margin: %{customdata[1]:+.2f}<br>minutes played vs level:"
                    " %{customdata[2]:+.1f}<br>player-games: %{customdata[0]:,}<extra></extra>"
                ),
            ),
            row=i // 3 + 1,
            col=i % 3 + 1,
        )
    fig.add_hline(y=0, line_color=MUTED, line_dash="dot")
    fig.update_xaxes(categoryorder="array", categoryarray=labels)
    fig.update_yaxes(tickformat="+.0%")
    fig.update_layout(height=680)
    title = titled(
        f"Minutes {feature} vs the price: do overs fall short more in some groups?",
        f"x = {desc}, in minutes (each group includes its lower edge). y = over rate minus"
        " mean no-vig over probability; below 0 = overs hit less often than priced."
        f" Bars = 95% CI across player-games; groups under {MIN_BAND} left out.",
        UNIT_NOTE,
        FEATURE_NOTE + " " + MAIN_NOTE,
    )
    save(style(fig, title), f"b3_{feature}_gap.html")


def spread_chart(df: pd.DataFrame) -> None:
    """Points: spread of the margin by minutes volatility, within line-level groups."""
    edges, line_labels = base.BANDS["Points"]
    d = df[df.market == "Points"].assign(
        band=lambda x: banded(x, "volatility"),
        line_band=lambda x: pd.cut(x.line, [0, *edges, np.inf], labels=line_labels, right=False),
    )
    t = d.groupby(["line_band", "band"], observed=True).margin.agg(sd="std", n="size")
    t = t[t.n >= MIN_BAND]
    print("\nB3 volatility: sd of points margin by line level and minutes volatility")
    print(t.sd.unstack().round(2).to_string())
    print(t.n.unstack().to_string())
    fig = go.Figure()
    for j, lb in enumerate(line_labels):
        if lb not in t.index.get_level_values(0):
            continue
        s = t.loc[lb]
        fig.add_trace(
            go.Scatter(
                x=s.index.astype(str),
                y=s.sd,
                customdata=s[["n"]],
                name=f"line {lb}",
                mode="lines+markers",
                line=dict(color=SERIES[j], width=2),
                marker=dict(size=8),
                hovertemplate=(
                    f"points line {lb}, volatility %{{x}}<br>sd of margin %{{y:.2f}} points"
                    "<br>player-games: %{customdata[0]:,}<extra></extra>"
                ),
            )
        )
    fig.update_xaxes(
        categoryorder="array",
        categoryarray=FEATURES["volatility"][2],
        title_text="standard deviation of minutes, previous 10 games (minutes)",
    )
    fig.update_yaxes(title_text="standard deviation of (actual points - line)")
    fig.update_layout(height=560, legend_title_text="")
    title = titled(
        "Are results more spread out for players with unstable minutes? (points)",
        "Each line = one group of consensus close points lines (under 10, 10 to <15, 15 to"
        " <20, 20 to <25, 25+). x = how much the player's minutes varied over his previous"
        " 10 games. y = spread of actual points around the line; higher = less predictable.",
        f"Regular season, close snapshot, one count per player-game; groups under {MIN_BAND}"
        " left out. " + FEATURE_NOTE,
    )
    save(style(fig, title), "b3_volatility_spread.html")


def main() -> None:
    feats = minutes_features()
    pg = player_games().merge(feats, on=["espn_game_id", "player_key"], how="inner")
    print(f"player-game-markets with minutes features: {len(pg):,}")
    print(pg[["level", "volatility", "trend", "minutes_vs_level"]].describe().round(2).to_string())
    print(pg[["level", "volatility", "trend"]].corr().round(2).to_string())
    for feature in FEATURES:
        gap_chart(pg, feature)
    spread_chart(pg)


if __name__ == "__main__":
    main()
