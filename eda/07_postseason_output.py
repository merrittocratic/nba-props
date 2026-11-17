"""EDA B10: why output per minute drops in the postseason: pace, usage or efficiency.

Catalog entry B10 in docs/eda_catalog.md (follow-up to A6 and B9). Points per minute is
exactly the product of three factors, so the postseason drop splits among them:

    pace       = team possessions per minute while the player is on the floor
    usage      = share of those possessions the player ends himself
    efficiency = points per possession he ends

Each player's postseason is compared with the same player's regular season of the same
year, weighted by his postseason minutes. The market side: does the closing game total
fall by as much as actual scoring?

    uv run --group eda python eda/07_postseason_output.py
"""

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from charts import MUTED, SERIES, TIDY, save, style, titled

MIN_REGULAR_GAMES = 20
FT_WEIGHT = 0.44  # share of free throws that end a possession (standard estimate)
TIERS = ([18, 24, 30, 34], ["under 18", "18 to <24", "24 to <30", "30 to <34", "34+"])
STATS = ["minutes", "poss", "used", "pts", "ast", "reb", "fga", "fgm", "fg3m", "fta", "tov"]
FACTORS = {
    "pace": "pace (possessions per minute)",
    "usage": "usage (share of possessions he ends)",
    "efficiency": "efficiency (points per possession he ends)",
}
BOOT = 1000


def player_games() -> pd.DataFrame:
    """One row per player-game played, with the possessions his team had while he played."""
    bx = pd.read_parquet(TIDY / "box_scores.parquet")
    gm = pd.read_parquet(TIDY / "games.parquet", columns=["espn_game_id", "season", "season_type"])
    bx = bx[~bx.did_not_play & (bx.minutes > 0)].merge(gm, on="espn_game_id")
    bx = bx[bx.season_type.isin([2, 3, 5])].copy()
    bx["post"] = bx.season_type.isin([3, 5])
    bx["used"] = bx.fga + FT_WEIGHT * bx.fta + bx.tov  # possessions the player ends
    team = bx.groupby(["espn_game_id", "team"])[["fga", "fta", "tov", "oreb", "minutes"]].sum()
    team["poss"] = team.fga + FT_WEIGHT * team.fta + team.tov - team.oreb
    game = team.groupby("espn_game_id").agg(poss=("poss", "mean"), minutes=("minutes", "mean"))
    game["poss_per_min"] = game.poss / (game.minutes / 5)  # game length incl. overtime
    bx = bx.merge(game.poss_per_min, on="espn_game_id")
    bx["poss"] = bx.poss_per_min * bx.minutes  # team possessions while he was on the floor
    return bx


def player_seasons(bx: pd.DataFrame) -> pd.DataFrame:
    """Per player-season: postseason totals next to regular-season totals rescaled to the
    same minutes, so every comparison is the same players at the same weights."""
    keys = ["player_key", "season"]
    reg = bx[~bx.post].groupby(keys)[STATS].sum()
    reg["games"] = bx[~bx.post].groupby(keys).size()
    post = bx[bx.post].groupby(keys)[STATS].sum()
    d = reg.merge(post, on=keys, suffixes=("_reg", "_post"))
    d = d[d.games >= MIN_REGULAR_GAMES]
    edges, labels = TIERS
    d["tier"] = pd.cut(
        d.minutes_reg / d.games, [0, *edges, np.inf], labels=labels, right=False
    ).astype(str)
    scale = d.minutes_post / d.minutes_reg
    for s in STATS:
        d[f"{s}_reg"] = d[f"{s}_reg"] * scale
    return d.reset_index()


def rates(t: pd.DataFrame, phase: str) -> dict:
    """Factor values from summed totals for one phase ('reg' or 'post')."""
    v = {s: t[f"{s}_{phase}"].sum() for s in STATS}
    return {
        "pts_per_36": 36 * v["pts"] / v["minutes"],
        "pace": v["poss"] / v["minutes"],
        "usage": v["used"] / v["poss"],
        "efficiency": v["pts"] / v["used"],
        "ast_per_36": 36 * v["ast"] / v["minutes"],
        "ast_per_100_poss": 100 * v["ast"] / v["poss"],
        "reb_per_36": 36 * v["reb"] / v["minutes"],
        "poss_per_48": 48 * v["poss"] / v["minutes"],
        "efg": (v["fgm"] + 0.5 * v["fg3m"]) / v["fga"],
        "fta_per_fga": v["fta"] / v["fga"],
        "tov_share_of_used": v["tov"] / v["used"],
    }


def changes(t: pd.DataFrame) -> pd.Series:
    """Postseason vs regular season, as log changes (so the factors add to the total)."""
    r, p = rates(t, "reg"), rates(t, "post")
    out = {k: np.log(p[k] / r[k]) for k in FACTORS}
    out["total"] = np.log(p["pts_per_36"] / r["pts_per_36"])
    return pd.Series(out)


def decompose(d: pd.DataFrame) -> pd.DataFrame:
    rng = np.random.default_rng(42)
    rows = []
    for tier in TIERS[1]:
        t = d[d.tier == tier]
        est = changes(t)
        # Resample player-seasons with replacement for a 95% interval.
        boot = pd.DataFrame([changes(t.iloc[rng.integers(0, len(t), len(t))]) for _ in range(BOOT)])
        for k in est.index:
            rows.append(
                {
                    "tier": tier,
                    "part": k,
                    "change": est[k],
                    "lo": boot[k].quantile(0.025),
                    "hi": boot[k].quantile(0.975),
                    "n": len(t),
                }
            )
    return pd.DataFrame(rows)


def decomposition_chart(dec: pd.DataFrame) -> None:
    fig = go.Figure()
    names = {**FACTORS, "total": "total: points per minute"}
    for j, (part, name) in enumerate(names.items()):
        s = dec[dec.part == part]
        fig.add_trace(
            go.Bar(
                x=s.tier,
                y=s.change,
                name=name,
                marker=dict(
                    color=MUTED if part == "total" else SERIES[j],
                    line=dict(color="#fcfcfb", width=2),
                ),
                error_y=dict(
                    type="data",
                    symmetric=False,
                    array=s.hi - s.change,
                    arrayminus=s.change - s.lo,
                    color="#0b0b0b",
                    thickness=1,
                ),
                customdata=s[["n"]],
                hovertemplate=(
                    f"{name}<br>%{{x}} minutes per game<br>postseason vs regular season:"
                    " %{y:+.1%}<br>player-seasons: %{customdata[0]:,}<extra></extra>"
                ),
            )
        )
    fig.add_hline(y=0, line_color=MUTED)
    fig.update_layout(
        barmode="group",
        xaxis_title="player's regular-season minutes per game that season",
        yaxis_title="postseason vs regular season (log change)",
        yaxis_tickformat="+.0%",
        height=560,
    )
    fig.update_xaxes(categoryorder="array", categoryarray=TIERS[1])
    title = titled(
        "Why playoff scoring per minute drops: pace, usage or efficiency",
        "Each bar = the change from a player's regular season to his postseason of the same"
        " year, pooled over players in the group and weighted by postseason minutes. The"
        " three coloured bars add up to the grey total. Lines = 95% interval from"
        " resampling player-seasons.",
        "Pace = team possessions per minute while he is on the floor. Usage = share of those"
        " possessions he ends with a shot, free-throw trip or turnover. Efficiency = points"
        f" per possession he ends. Players with {MIN_REGULAR_GAMES}+ regular-season games"
        " and postseason minutes, 2023-24 to 2025-26 seasons plus the 2023 playoffs from"
        " May 3. Changes are log changes: -0.05 is about -5%.",
    )
    save(style(fig, title), "b10_postseason_decomposition.html")


def game_totals() -> None:
    """Closing game total against actual scoring, for teams that reached the postseason."""
    gm = pd.read_parquet(TIDY / "games.parquet")
    gm = gm[gm.season_type.isin([2, 3, 5]) & (gm.status == "STATUS_FINAL")]
    gl = pd.read_parquet(TIDY / "game_lines.parquet", columns=["kind", "espn_game_id", "total"])
    close = gl[gl.kind == "close"].groupby("espn_game_id").total.median().rename("line")
    gm = gm.merge(close, on="espn_game_id").dropna(subset=["line"])
    gm["actual"] = gm.home_score + gm.away_score
    gm["post"] = gm.season_type.isin([3, 5])
    tg = pd.concat(
        [
            gm.assign(team=gm[c])[["team", "season", "post", "line", "actual"]]
            for c in ("home_team", "away_team")
        ]
    )
    n_post = tg[tg.post].groupby(["team", "season"]).size().rename("w")
    tg = tg.merge(n_post, on=["team", "season"])  # team-seasons with postseason games
    tg["w"] = np.where(
        tg.post, 1.0, tg.w / tg.groupby(["team", "season", "post"]).line.transform("size")
    )
    out = tg.groupby("post").apply(
        lambda x: pd.Series(
            {
                "closing total": np.average(x.line, weights=x.w),
                "actual total": np.average(x.actual, weights=x.w),
                "team-games": len(x),
            }
        ),
        include_groups=False,
    )
    out.index = ["regular season", "postseason"]
    out["actual minus closing"] = out["actual total"] - out["closing total"]
    print("\nB10 game totals, teams that reached the postseason (regular season reweighted")
    print("to each team's postseason games)")
    print(out.round(2).to_string())
    print("log change, postseason vs regular season:")
    print(np.log(out.loc["postseason"] / out.loc["regular season"]).iloc[:2].round(4).to_string())
    g = gm.assign(miss=gm.actual - gm.line).groupby("post").miss
    print("actual minus closing total, per game: mean, se, n")
    print(pd.DataFrame({"mean": g.mean(), "se": g.sem(), "n": g.size()}).round(2).to_string())


def main() -> None:
    d = player_seasons(player_games())
    print(f"player-seasons with regular season and postseason: {len(d):,}")
    print(d.groupby("tier").agg(n=("tier", "size"), post_minutes=("minutes_post", "sum")))
    print("\nB10 rates by tier (regular season rescaled to postseason minutes, then postseason)")
    table = {}
    for tier in [*TIERS[1], "all"]:
        t = d if tier == "all" else d[d.tier == tier]
        for phase in ("reg", "post"):
            table[(tier, phase)] = rates(t, phase)
    print(pd.DataFrame(table).T.round(3).to_string())
    dec = decompose(d)
    print("\nB10 decomposition (log change, postseason vs regular season)")
    print(dec.pivot(index="tier", columns="part", values="change").loc[TIERS[1]].round(4))
    print(changes(d).round(4).rename("all tiers").to_string())
    decomposition_chart(dec)
    game_totals()


if __name__ == "__main__":
    main()
