"""EDA B9: a minutes projection, and whether it says anything the price doesn't.

Catalog entry B9 in docs/eda_catalog.md. Regular season. A linear model (ordinary least
squares, fitted with numpy) predicts a player's minutes tonight from what is known before
the game. Fitted on the 2023-24 and 2024-25 seasons, tested on 2025-26 onward.

Two versions:
  pregame   - history only: every input is known before tip-off.
  hindsight - the same plus the rotation minutes the team is actually missing tonight.
              That is read from tonight's box score, so it is NOT usable as a feature; it
              shows how much a real injury report would be worth.

    uv run --group eda python eda/05_minutes_projection.py
"""

import importlib

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from charts import MAIN_NOTE, MUTED, SERIES, TIDY, save, style, titled
from plotly.subplots import make_subplots

b3 = importlib.import_module("04_minutes_features")  # player_games, base, UNIT_NOTE

WINDOW, SHORT, MIN_GAMES = 10, 3, 5
ROTATION_LOOKBACK = 5  # team games used to decide who is in the rotation
ROTATION_MIN_GAMES = 2  # played at least this many of them
TRAIN_SEASONS = [2024, 2025]  # ESPN labels a season by its end year
MIN_BAND = 300
PREGAME = [
    "level",
    "last3",
    "last1",
    "start_share",
    "started_last",
    "back_to_back",
    "long_rest",
    "games_missed",
    "home",
    "abs_spread",
    "abs_spread_x_level",
    "team_missing_last",
    "team_missing_last_x_level",
]
HINDSIGHT = [*PREGAME, "team_missing_tonight", "team_missing_tonight_x_level"]
POSTSEASON = [*PREGAME, "post", "post_x_level", "post_x_started_last", "post_x_abs_spread"]
LEVEL_TIERS = ([18, 24, 30, 34], ["under 18", "18 to <24", "24 to <30", "30 to <34", "34+"])
# (inner edges, labels) in minutes; each band is [lo, hi).
VS_LEVEL = ([-3, -1, 1, 3], ["3+ below", "1 to 3 below", "within 1", "1 to 3 above", "3+ above"])
ADJUSTMENT = ([-2, -1, 1, 2], ["2+ fewer", "1 to 2 fewer", "within 1", "1 to 2 more", "2+ more"])
VS_LINE = ([-4, -2, 2, 4], ["4+ below", "2 to 4 below", "within 2", "2 to 4 above", "4+ above"])
MODEL_NOTE = (
    "Projection = linear model of minutes on the player's previous 10 games (level, last 3,"
    " last game, share started), rest, games just missed, home/away, point spread and the"
    " rotation minutes his team was missing last game. Fitted on 2023-24 and 2024-25; every"
    " dot here is from 2025-26 onward, which the model never saw."
)


def team_missing(played: pd.DataFrame) -> pd.DataFrame:
    """Rotation minutes missing per team-game: players in the recent rotation who sat out.

    Rotation = played at least ROTATION_MIN_GAMES of the team's previous
    ROTATION_LOOKBACK games; each absent player counts his average minutes in them.
    """
    tg = played[["team", "espn_game_id", "tip_utc"]].drop_duplicates()
    tg = tg.sort_values(["team", "tip_utc"])
    tg["team_game"] = tg.groupby("team").cumcount()
    p = played.merge(tg[["team", "espn_game_id", "team_game"]], on=["team", "espn_game_id"])
    recent = pd.concat(
        [
            p[["team", "player_key", "minutes"]].assign(team_game=p.team_game + k)
            for k in range(1, ROTATION_LOOKBACK + 1)
        ]
    )
    rot = recent.groupby(["team", "team_game", "player_key"]).minutes.agg(["mean", "size"])
    rot = rot[rot["size"] >= ROTATION_MIN_GAMES].reset_index()
    tonight = p[["team", "team_game", "player_key"]].assign(played=True)
    rot = rot.merge(tonight, on=["team", "team_game", "player_key"], how="left")
    missing = rot[rot.played.isna()].groupby(["team", "team_game"])["mean"].sum()
    tg = tg.merge(missing.rename("team_missing_tonight"), on=["team", "team_game"], how="left")
    tg["team_missing_tonight"] = tg.team_missing_tonight.fillna(0.0)
    tg["team_missing_last"] = tg.groupby("team").team_missing_tonight.shift().fillna(0.0)
    return tg


def features() -> pd.DataFrame:
    """One row per regular-season player-game played, inputs from before the game."""
    bx = pd.read_parquet(
        TIDY / "box_scores.parquet",
        columns=[
            "espn_game_id",
            "player_key",
            "team",
            "home",
            "starter",
            "did_not_play",
            "minutes",
            "pts",
        ],
    )
    gm = pd.read_parquet(
        TIDY / "games.parquet", columns=["espn_game_id", "tip_utc", "season", "season_type"]
    )
    bx = bx[~bx.did_not_play & (bx.minutes > 0)].merge(gm, on="espn_game_id")
    bx = bx[bx.season_type.isin([2, 3, 5])]  # history may include postseason games
    tg = team_missing(bx)
    bx = bx.merge(
        tg[["team", "espn_game_id", "team_game", "team_missing_tonight", "team_missing_last"]],
        on=["team", "espn_game_id"],
    )
    bx = bx.sort_values(["player_key", "tip_utc"]).reset_index(drop=True)
    g = bx.groupby("player_key")

    def rolled(col: str, n: int, min_periods: int, how: str) -> pd.Series:
        prev = g[col].shift()  # never the game itself
        r = prev.groupby(bx.player_key).rolling(n, min_periods=min_periods)
        return getattr(r, how)().reset_index(level=0, drop=True)

    bx["starter"] = bx.starter.astype(float)
    bx["level"] = rolled("minutes", WINDOW, MIN_GAMES, "mean")
    bx["last3"] = rolled("minutes", SHORT, SHORT, "mean")
    bx["last1"] = g.minutes.shift()
    bx["start_share"] = rolled("starter", WINDOW, MIN_GAMES, "mean")
    bx["started_last"] = g.starter.shift()
    bx["pts_per_min"] = rolled("pts", WINDOW, MIN_GAMES, "sum") / rolled(
        "minutes", WINDOW, MIN_GAMES, "sum"
    )
    rest = (bx.tip_utc - g.tip_utc.shift()).dt.total_seconds() / 86400
    bx["back_to_back"] = (rest < 1.5).astype(float)
    bx["long_rest"] = (rest >= 4).astype(float)
    # Team games the player sat out since he last played for this team (0 if none or traded).
    same_team = bx.team == g.team.shift()
    gap = bx.team_game - g.team_game.shift() - 1
    bx["games_missed"] = np.where(same_team, gap.clip(0, 10), 0.0)
    bx["home"] = bx.home.astype(float)

    gl = pd.read_parquet(
        TIDY / "game_lines.parquet", columns=["kind", "espn_game_id", "home_spread"]
    )
    spread = gl[gl.kind == "close"].groupby("espn_game_id").home_spread.median().abs()
    bx = bx.merge(spread.rename("abs_spread"), on="espn_game_id", how="left")
    bx["abs_spread"] = bx.abs_spread.fillna(bx.abs_spread.median())
    for col in ("abs_spread", "team_missing_last", "team_missing_tonight"):
        bx[f"{col}_x_level"] = bx[col] * (bx.level - 24) / 10  # effect differs by role
    # Postseason (play-in and playoffs): rotations shrink, so the effect of a player's
    # level, of having started, and of the spread may differ. See catalog A6 and B9.
    bx["post"] = bx.season_type.isin([3, 5]).astype(float)
    bx["post_x_level"] = bx.post * (bx.level - 24) / 10
    bx["post_x_started_last"] = bx.post * bx.started_last
    bx["post_x_abs_spread"] = bx.post * bx.abs_spread
    return bx.dropna(subset=["level", "last3", "last1", "start_share"])


def fit(train: pd.DataFrame, cols: list[str]) -> np.ndarray:
    """Ordinary least squares with an intercept: minimise squared error in minutes."""
    x = np.column_stack([np.ones(len(train)), train[cols].to_numpy(float)])
    beta, *_ = np.linalg.lstsq(x, train.minutes.to_numpy(float), rcond=None)
    return beta


def predict(df: pd.DataFrame, cols: list[str], beta: np.ndarray) -> np.ndarray:
    return beta[0] + df[cols].to_numpy(float) @ beta[1:]


def accuracy(test: pd.DataFrame, lined: pd.Series) -> pd.DataFrame:
    rows = {}
    for name, pred in {
        "last game": test.last1,
        "10-game average": test.level,
        "projection (pregame)": test.proj,
        "projection (hindsight on absences)": test.proj_hindsight,
    }.items():
        err = test.minutes - pred
        rows[name] = {
            "avg miss, all": err.abs().mean(),
            "avg miss, players with a points line": err[lined].abs().mean(),
            "rmse, all": np.sqrt((err**2).mean()),
        }
    return pd.DataFrame(rows).T


def accuracy_chart(acc: pd.DataFrame, n_all: int, n_lined: int) -> None:
    fig = go.Figure()
    for col, color, n in (
        ("avg miss, all", SERIES[0], n_all),
        ("avg miss, players with a points line", SERIES[1], n_lined),
    ):
        fig.add_trace(
            go.Bar(
                x=acc[col],
                y=acc.index,
                orientation="h",
                name=f"{col.split(', ')[1]} ({n:,} player-games)",
                marker=dict(color=color, line=dict(color="#fcfcfb", width=2)),
                text=acc[col].round(2),
                textposition="outside",
                hovertemplate="%{y}<br>average miss %{x:.2f} minutes<extra></extra>",
            )
        )
    fig.update_layout(
        barmode="group",
        xaxis_title="average miss in minutes (mean absolute error), 2025-26 onward",
        yaxis=dict(autorange="reversed"),
        height=480,
    )
    title = titled(
        "How well can minutes be projected before the game?",
        "Each bar = the average gap between predicted and actual minutes for regular-season"
        " player-games from 2025-26 onward. Shorter = better. Hindsight on absences uses"
        " who actually sat out tonight, so it is a ceiling, not a usable forecast.",
        MODEL_NOTE,
    )
    save(style(fig, title), "b9_projection_accuracy.html")


def gap_panels(
    df: pd.DataFrame,
    col: str,
    bands: tuple,
    markets: list[str],
    x_title: str,
    name: str,
    title: str,
    *notes: str,
) -> None:
    edges, labels = bands
    d = df.dropna(subset=["gap", col]).assign(
        band=lambda x: pd.cut(x[col], [-np.inf, *edges, np.inf], labels=labels, right=False)
    )
    t = d.groupby(["market", "band"], observed=True).agg(
        gap=("gap", "mean"),
        sd=("gap", "std"),
        n=("gap", "size"),
        margin=("margin", "mean"),
        played_vs_proj=("played_vs_proj", "mean"),
    )
    t["se"] = t.sd / np.sqrt(t.n)
    print(f"\n{name}: gap vs price by {col}")
    print(t.drop(columns="sd").round(3).to_string())
    cols = min(3, len(markets))
    rows = -(-len(markets) // cols)
    fig = make_subplots(rows=rows, cols=cols, subplot_titles=markets, shared_yaxes=True)
    for i, market in enumerate(markets):
        s = t.loc[market]
        s = s[s.n >= MIN_BAND]
        fig.add_trace(
            go.Scatter(
                x=s.index.astype(str),
                y=s.gap,
                error_y=dict(type="data", array=1.96 * s.se, color=SERIES[0]),
                customdata=s[["n", "margin", "played_vs_proj"]],
                mode="markers",
                marker=dict(color=SERIES[0], size=9),
                showlegend=False,
                hovertemplate=(
                    f"{market}, %{{x}}<br>over rate minus price: %{{y:+.1%}}<br>average"
                    " margin: %{customdata[1]:+.2f}<br>minutes played minus projection:"
                    " %{customdata[2]:+.1f}<br>player-games: %{customdata[0]:,}<extra></extra>"
                ),
            ),
            row=i // cols + 1,
            col=i % cols + 1,
        )
    fig.add_hline(y=0, line_color=MUTED, line_dash="dot")
    fig.update_xaxes(categoryorder="array", categoryarray=labels)
    fig.update_xaxes(title_text=x_title, row=rows)
    fig.update_yaxes(tickformat="+.0%")
    fig.update_layout(height=360 * rows + 140)
    save(style(fig, titled(title, *notes)), name)


def postseason(f: pd.DataFrame, b_regular: np.ndarray) -> None:
    """Does the regular-season projection carry over to the postseason? Fix and test."""
    last_train = max(TRAIN_SEASONS)
    train = f[f.season <= last_train]  # regular season plus the postseasons up to then
    test = f[(f.season > last_train) & (f.post == 1)].copy()
    beta = fit(train, POSTSEASON)
    print(
        f"\nB9 postseason: train {len(train):,} player-games ({int(train.post.sum()):,}"
        f" postseason), test {len(test):,} (postseason after {last_train - 1}-{last_train % 100})"
    )
    print(pd.Series(beta, ["intercept", *POSTSEASON]).round(3).tail(4).to_string())
    models = {
        "10-game average": test.level,
        "regular-season model": pd.Series(predict(test, PREGAME, b_regular), test.index),
        "model with postseason terms": pd.Series(predict(test, POSTSEASON, beta), test.index),
    }
    edges, labels = LEVEL_TIERS
    tier = pd.cut(test.level, [0, *edges, np.inf], labels=labels, right=False)
    overall, bias = {}, {}
    for name, pred in models.items():
        err = test.minutes - pred
        overall[name] = {"avg miss": err.abs().mean(), "actual minus projected": err.mean()}
        bias[name] = err.groupby(tier, observed=True).mean()
    print(pd.DataFrame(overall).T.round(3).to_string())
    bias = pd.DataFrame(bias)
    bias["n"] = tier.value_counts()
    print(bias.round(2).to_string())

    fig = go.Figure()
    for j, name in enumerate(list(models)[1:]):
        fig.add_trace(
            go.Bar(
                x=bias.index.astype(str),
                y=bias[name],
                name=name,
                marker=dict(color=SERIES[j], line=dict(color="#fcfcfb", width=2)),
                customdata=bias[["n"]],
                hovertemplate=(
                    f"{name}<br>10-game average %{{x}} minutes<br>actual minus projected:"
                    " %{y:+.1f} minutes<br>player-games: %{customdata[0]:,}<extra></extra>"
                ),
            )
        )
    fig.add_hline(y=0, line_color=MUTED)
    fig.update_layout(
        barmode="group",
        xaxis_title="player's average minutes over his previous 10 games",
        yaxis_title="actual minutes minus projected minutes",
        height=520,
    )
    title = titled(
        "Playoff minutes: where the regular-season projection goes wrong",
        f"Each bar = postseason player-games (play-in and playoffs) after {last_train - 1}-"
        f"{last_train % 100}, grouped by the player's 10-game average minutes. Below 0 = he"
        " played less than projected; above 0 = more.",
        "Regular-season model = fitted on regular-season games only. Model with postseason"
        " terms = the same inputs plus a postseason indicator on its own and multiplied by"
        " the player's level, by started-last-game and by the spread, fitted on earlier"
        " regular seasons and postseasons.",
    )
    save(style(fig, title), "b9_postseason_bias.html")


def phase_panels(pg: pd.DataFrame, markets: list[str]) -> None:
    """Over rate minus price by minutes level, regular season next to postseason."""
    edges, labels = LEVEL_TIERS
    d = pg.dropna(subset=["gap", "level"]).assign(
        band=lambda x: pd.cut(x.level, [-np.inf, *edges, np.inf], labels=labels, right=False)
    )
    t = d.groupby(["market", "phase", "band"], observed=True).agg(
        gap=("gap", "mean"), sd=("gap", "std"), n=("gap", "size"), margin=("margin", "mean")
    )
    t["se"] = t.sd / np.sqrt(t.n)
    print("\nB9 postseason price test: gap by minutes level and phase")
    print(t.drop(columns="sd").round(3).to_string())
    fig = make_subplots(
        rows=2, cols=3, subplot_titles=markets, shared_yaxes=True, vertical_spacing=0.16
    )
    for i, market in enumerate(markets):
        for j, phase in enumerate(["regular season", "postseason"]):
            s = t.loc[(market, phase)]
            s = s[s.n >= MIN_BAND]
            fig.add_trace(
                go.Scatter(
                    x=s.index.astype(str),
                    y=s.gap,
                    error_y=dict(type="data", array=1.96 * s.se, color=SERIES[j]),
                    customdata=s[["n", "margin"]],
                    mode="markers",
                    name=phase,
                    legendgroup=phase,
                    showlegend=i == 0,
                    marker=dict(color=SERIES[j], size=9),
                    hovertemplate=(
                        f"{market}, {phase}, %{{x}} minutes<br>over rate minus price:"
                        " %{y:+.1%}<br>average margin: %{customdata[1]:+.2f}<br>player-games:"
                        " %{customdata[0]:,}<extra></extra>"
                    ),
                ),
                row=i // 3 + 1,
                col=i % 3 + 1,
            )
    fig.add_hline(y=0, line_color=MUTED, line_dash="dot")
    fig.update_xaxes(categoryorder="array", categoryarray=labels)
    fig.update_xaxes(title_text="average minutes, previous 10 games", row=2)
    fig.update_yaxes(tickformat="+.0%")
    fig.update_layout(height=860, scattermode="group")
    title = titled(
        "Is the playoff under lean a bench-player effect? Price gap by minutes role",
        "x = the player's average minutes over his previous 10 games played (each group"
        " includes its lower edge). y = over rate minus mean no-vig over probability; below"
        f" 0 = overs hit less often than priced. Bars = 95% CI; groups under {MIN_BAND}"
        " player-games left out.",
        "Unit = one player-game in one market at the close snapshot; over rate and price are"
        " averaged over the books pricing it (pushes excluded). Postseason = play-in and"
        " playoffs, 2023 (from May 3) to 2026. " + MAIN_NOTE,
    )
    save(style(fig, title), "b9_postseason_gap_by_level.html")


def postseason_price(every: pd.DataFrame) -> None:
    """Does the price already allow for playoff rotations? Catalog B9, price test."""
    post = every[every.post == 1]
    parts = []
    for season in sorted(post.season.unique()):
        train = every[every.season != season]  # each postseason projected by the others
        t = post[post.season == season].copy()
        t["proj_regular"] = predict(t, PREGAME, fit(train[train.post == 0], PREGAME))
        t["proj"] = predict(t, POSTSEASON, fit(train, POSTSEASON))
        parts.append(t)
    proj = pd.concat(parts)
    proj["adjustment"] = proj.proj - proj.proj_regular
    print("\nB9 postseason adjustment (postseason-terms projection minus regular-season model)")
    print(proj.adjustment.describe().round(2).to_string())

    keys = ["espn_game_id", "player_key"]
    both = pd.concat([b3.player_games(p).assign(phase=p) for p in ("regular season", "postseason")])
    markets = list(b3.base.MARKETS.values())
    phase_panels(both.merge(every[[*keys, "level"]], on=keys), markets)

    pg = both[both.phase == "postseason"].merge(
        proj[[*keys, "season", "minutes", "level", "proj", "proj_regular", "adjustment"]],
        on=keys,
    )
    pg["played_vs_proj"] = pg.minutes - pg.proj
    print(f"\npostseason player-game-markets with a projection: {len(pg):,}")
    print(pg.groupby("season").size().to_string())
    gap_panels(
        pg,
        "adjustment",
        ADJUSTMENT,
        markets,
        "minutes added by postseason terms",
        "b9_postseason_adjustment_gap.html",
        "Does the price already allow for playoff rotations?",
        "x = projection with postseason terms minus the regular-season model's projection,"
        " in minutes (each group includes its lower edge): more = the playoffs should give"
        " him more minutes than his regular-season pattern says. y = over rate minus mean"
        f" no-vig over probability. Bars = 95% CI; groups under {MIN_BAND} left out.",
        "Unit = one postseason player-game (play-in and playoffs, 2023 to 2026) in one"
        " market at the close snapshot. Each postseason is projected by models fitted on"
        " every other season, so no game is scored by a model that saw it.",
        MAIN_NOTE,
    )


def main() -> None:
    every = features()
    f = every[every.post == 0]  # the regular-season projection and price tests
    train = f[f.season.isin(TRAIN_SEASONS)]
    test = f[~f.season.isin(TRAIN_SEASONS) & (f.season > max(TRAIN_SEASONS))].copy()
    print(f"player-games: train {len(train):,} ({TRAIN_SEASONS}), test {len(test):,}")
    b_pre, b_hind = fit(train, PREGAME), fit(train, HINDSIGHT)
    print("\nB9 coefficients (minutes per unit of each input; intercept first)")
    coef = pd.DataFrame(
        {
            "pregame": pd.Series(b_pre, ["intercept", *PREGAME]),
            "hindsight": pd.Series(b_hind, ["intercept", *HINDSIGHT]),
        }
    )
    print(coef.round(3).to_string())
    test["proj"] = predict(test, PREGAME, b_pre)
    test["proj_hindsight"] = predict(test, HINDSIGHT, b_hind)
    postseason(every, b_pre)
    postseason_price(every)

    pg = b3.player_games()
    pg = pg.merge(
        test[
            [
                "espn_game_id",
                "player_key",
                "minutes",
                "level",
                "proj",
                "proj_hindsight",
                "pts_per_min",
                "team_missing_tonight",
            ]
        ],
        on=["espn_game_id", "player_key"],
        how="inner",
    )
    pg["played_vs_proj"] = pg.minutes - pg.proj
    pg["proj_vs_level"] = pg.proj - pg.level
    pts = pg[pg.market == "Points"].copy()
    pts["line_minutes"] = pts.line / pts.pts_per_min  # minutes the line implies at his rate
    pts["proj_vs_line"] = pts.proj - pts.line_minutes
    pts["hind_vs_line"] = pts.proj_hindsight - pts.line_minutes

    lined = test.set_index(["espn_game_id", "player_key"]).index.isin(
        pts.set_index(["espn_game_id", "player_key"]).index
    )
    acc = accuracy(test, pd.Series(lined, index=test.index))
    print("\nB9 projection accuracy on the test seasons (minutes)")
    print(acc.round(3).to_string())
    accuracy_chart(acc, len(test), int(lined.sum()))
    print("\nprojection minus actual by projected band (calibration)")
    cal = test.assign(b=pd.cut(test.proj, [0, 12, 18, 24, 30, 34, 60])).groupby("b", observed=True)
    print(
        cal.agg(proj=("proj", "mean"), actual=("minutes", "mean"), n=("minutes", "size"))
        .round(2)
        .to_string()
    )

    markets = list(b3.base.MARKETS.values())
    gap_panels(
        pg,
        "proj_vs_level",
        VS_LEVEL,
        markets,
        "projected minutes minus 10-game average (minutes)",
        "b9_proj_vs_level_gap.html",
        "When the projection differs from the player's average minutes, is the price off?",
        "x = projected minutes minus the player's 10-game average (each group includes its"
        " lower edge). y = over rate minus mean no-vig over probability; below 0 = overs hit"
        f" less often than priced. Bars = 95% CI; groups under {MIN_BAND} left out.",
        b3.UNIT_NOTE,
        MODEL_NOTE + " " + MAIN_NOTE,
    )
    line_note = (
        "Line-implied minutes = points line divided by the player's points per minute over"
        " his previous 10 games: the minutes he would need, at his usual rate, to score the"
        " line. x = projected minutes minus that."
    )
    gap_panels(
        pts,
        "proj_vs_line",
        VS_LINE,
        ["Points"],
        "projected minutes minus line-implied minutes",
        "b9_proj_vs_line_gap.html",
        "Does the points line imply more or fewer minutes than the projection? (points)",
        line_note + " y = over rate minus mean no-vig over probability. Bars = 95% CI.",
        b3.UNIT_NOTE,
        MODEL_NOTE + " " + MAIN_NOTE,
    )
    gap_panels(
        pts,
        "hind_vs_line",
        VS_LINE,
        ["Points"],
        "hindsight projection minus line-implied minutes",
        "b9_hindsight_vs_line_gap.html",
        "Ceiling check: the same test with hindsight on who sat out tonight (points)",
        "NOT a usable feature: the projection here knows which teammates actually sat out."
        " It shows the most an accurate injury report could add. " + line_note,
        b3.UNIT_NOTE,
        MODEL_NOTE + " " + MAIN_NOTE,
    )


if __name__ == "__main__":
    main()
