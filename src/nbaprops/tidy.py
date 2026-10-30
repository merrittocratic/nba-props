"""Entry point: python -m nbaprops.tidy [--data-dir data]

Turns the raw capture into analysis tables under <data-dir>/tidy/ (parquet):

- games.parquet: one row per ESPN game (final score, tip-off, season)
- box_scores.parquet: one row per player per game, including players who didn't play
- prop_lines.parquet: one row per Odds API snapshot x book x market x player x line,
  over and under prices side by side (live capture and backfill both)
- prop_outcomes.parquet: prop_lines joined to the player's actual stat, with
  result (over / under / push / void) and margin (actual - line)

Rebuilt from scratch on every run; the raw files stay the source of truth.
Prints a match report: how many lines found their game and their player.
"""

from __future__ import annotations

import argparse
import difflib
import json
import re
import sys
import unicodedata
from datetime import timedelta
from pathlib import Path

import pandas as pd

from nbaprops import backfill, odds_api, outcomes
from nbaprops.snapshots import ET
from nbaprops.storage import Manifest

ODDS_SOURCES = (odds_api.SOURCE, backfill.SOURCE)
_KIND = re.compile(r"/events/([0-9a-f]+)/odds \[(\w+)\]")

# ESPN display names that differ from the Odds API's
TEAM_ALIASES = {"LA Clippers": "Los Angeles Clippers"}
# Player names that still differ after normalize_name, as {odds key: espn key}
PLAYER_ALIASES: dict[str, str] = {}

MARKET_STATS = {
    "player_points": ["pts"],
    "player_rebounds": ["reb"],
    "player_assists": ["ast"],
    "player_threes": ["fg3m"],
    "player_points_rebounds_assists": ["pts", "reb", "ast"],
    "player_points_rebounds": ["pts", "reb"],
}
MATCH_WINDOW = timedelta(hours=6)  # ESPN lists scheduled tip, the Odds API actual


def normalize_name(name: str) -> str:
    """Lowercase ASCII without punctuation or suffix: "Jaren Jackson Jr." -> "jaren jackson"."""
    ascii_ = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    words = re.sub(r"[^a-z ]", "", ascii_.lower().replace("-", " ")).split()
    while words and words[-1] in {"jr", "sr", "ii", "iii", "iv"}:
        words.pop()
    return " ".join(words)


def team_name(espn_name: str) -> str:
    return TEAM_ALIASES.get(espn_name, espn_name)


def _int(value) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _made_attempted(value) -> tuple[int | None, int | None]:
    if not isinstance(value, str) or "-" not in value:
        return None, None
    made, attempted = value.split("-", 1)
    return _int(made), _int(attempted)


def parse_summary(summary: dict) -> tuple[dict, list[dict]]:
    """One ESPN summary -> (game row, box score rows)."""
    comp = summary["header"]["competitions"][0]
    sides = {c["homeAway"]: c for c in comp["competitors"]}
    game_id = summary["header"]["id"]
    game = {
        "espn_game_id": game_id,
        "tip_utc": pd.Timestamp(comp["date"]),
        "season": summary["header"]["season"]["year"],
        "season_type": summary["header"]["season"]["type"],
        "status": comp["status"]["type"]["name"],
        "home_team": team_name(sides["home"]["team"]["displayName"]),
        "away_team": team_name(sides["away"]["team"]["displayName"]),
        "home_score": _int(sides["home"].get("score")),
        "away_score": _int(sides["away"].get("score")),
    }
    game["game_date_et"] = game["tip_utc"].tz_convert(ET).date()
    rows = []
    for team_block in summary["boxscore"]["players"]:
        team = team_name(team_block["team"]["displayName"])
        for group in team_block["statistics"]:
            labels = group["labels"]
            for a in group["athletes"]:
                s = dict(zip(labels, a.get("stats") or [], strict=False))  # DNP: no stats
                fgm, fga = _made_attempted(s.get("FG"))
                fg3m, fg3a = _made_attempted(s.get("3PT"))
                ftm, fta = _made_attempted(s.get("FT"))
                name = a["athlete"]["displayName"]
                rows.append(
                    {
                        "espn_game_id": game_id,
                        "espn_player_id": a["athlete"]["id"],
                        "player_name": name,
                        "player_key": normalize_name(name),
                        "team": team,
                        "home": team == game["home_team"],
                        "starter": bool(a.get("starter")),
                        "did_not_play": bool(a.get("didNotPlay")) or not a.get("stats"),
                        # ESPN fills `reason` on players who played too; keep it for DNPs only
                        "dnp_reason": (a.get("reason") or None) if a.get("didNotPlay") else None,
                        "ejected": bool(a.get("ejected")),
                        "minutes": _int(s.get("MIN")),
                        "pts": _int(s.get("PTS")),
                        "reb": _int(s.get("REB")),
                        "ast": _int(s.get("AST")),
                        "fg3m": fg3m,
                        "fg3a": fg3a,
                        "fgm": fgm,
                        "fga": fga,
                        "ftm": ftm,
                        "fta": fta,
                        "oreb": _int(s.get("OREB")),
                        "dreb": _int(s.get("DREB")),
                        "stl": _int(s.get("STL")),
                        "blk": _int(s.get("BLK")),
                        "tov": _int(s.get("TO")),
                        "pf": _int(s.get("PF")),
                        "plus_minus": _int(str(s.get("+/-", "")).replace("+", "")),
                    }
                )
    return game, rows


def parse_odds_snapshot(body: dict, source: str, kind: str, fetched_at: str) -> list[tuple]:
    """One saved event-odds response -> line rows (over/under paired)."""
    if source == backfill.SOURCE:
        event, snapshot_ts = body.get("data") or {}, body.get("timestamp")
    else:
        event, snapshot_ts = body, fetched_at
    rows = []
    for book in event.get("bookmakers", []):
        for market in book.get("markets", []):
            pairs: dict[tuple, dict] = {}
            for o in market.get("outcomes", []):
                key = (o.get("description"), o.get("point"))
                pairs.setdefault(key, {})[o.get("name")] = o.get("price")
            for (player, point), prices in pairs.items():
                rows.append(
                    (
                        source,
                        event.get("id"),
                        kind,
                        snapshot_ts,
                        event.get("commence_time"),
                        event.get("home_team"),
                        event.get("away_team"),
                        book["key"],
                        market["key"],
                        player,
                        point,
                        prices.get("Over"),
                        prices.get("Under"),
                        market.get("last_update"),
                    )
                )
    return rows


LINE_COLUMNS = [
    "source",
    "event_id",
    "kind",
    "snapshot_ts",
    "commence_time",
    "home_team",
    "away_team",
    "book",
    "market",
    "player_name",
    "point",
    "over_price",
    "under_price",
    "last_update",
]
CATEGORIES = ["source", "kind", "home_team", "away_team", "book", "market"]


def load_lines(manifest_rows: list[dict]) -> pd.DataFrame:
    chunks, rows = [], []
    for row in manifest_rows:
        if row["source"] not in ODDS_SOURCES or row["status"] != "200":
            continue
        if not (m := _KIND.search(row["request"])) or not row.get("path"):
            continue
        body = json.loads(Path(row["path"]).read_bytes())
        rows += parse_odds_snapshot(body, row["source"], m.group(2), row["fetched_at"])
        if len(rows) > 200_000:
            chunks.append(pd.DataFrame(rows, columns=LINE_COLUMNS))
            rows = []
    chunks.append(pd.DataFrame(rows, columns=LINE_COLUMNS))
    lines = pd.concat(chunks, ignore_index=True)
    for col in ("snapshot_ts", "commence_time", "last_update"):
        lines[col] = pd.to_datetime(lines[col], utc=True, format="ISO8601")
    lines["player_key"] = lines["player_name"].map(
        lambda n: PLAYER_ALIASES.get(normalize_name(n), normalize_name(n)) if n else None
    )
    return lines.astype({c: "category" for c in CATEGORIES})


def load_box_scores(manifest_rows: list[dict]) -> tuple[pd.DataFrame, pd.DataFrame]:
    games, box = {}, []
    for row in manifest_rows:
        if row["source"] != outcomes.SOURCE or row["status"] != "200":
            continue
        if not row["request"].startswith("GET summary") or not row.get("path"):
            continue
        game, rows = parse_summary(json.loads(Path(row["path"]).read_bytes()))
        games[game["espn_game_id"]] = game  # a refetch replaces the earlier copy
        box += rows
    games_df = pd.DataFrame(list(games.values()))
    box_df = pd.DataFrame(box).drop_duplicates(["espn_game_id", "espn_player_id"], keep="last")
    return games_df, box_df


def map_events(lines: pd.DataFrame, games: pd.DataFrame) -> pd.DataFrame:
    """Odds API event_id -> espn_game_id, by teams and tip-off within MATCH_WINDOW."""
    events = lines[["event_id", "commence_time", "home_team", "away_team"]].drop_duplicates(
        "event_id"
    )
    events = events.astype({"home_team": str, "away_team": str})
    cand = events.merge(games, on=["home_team", "away_team"])
    cand["gap"] = (cand["commence_time"] - cand["tip_utc"]).abs()
    cand = cand[cand["gap"] <= MATCH_WINDOW].sort_values("gap")
    return cand.drop_duplicates("event_id")[["event_id", "espn_game_id"]]


FUZZY_CUTOFF = 0.85


def match_name(name: str, roster: dict[str, str]) -> tuple[str | None, str | None]:
    """Find an Odds API player name in one game's box score: {player_key: espn_player_id}.

    Books format names inconsistently ("Irving, Kyrie", "Grant Jerami", "D. Jones Jr.",
    "Brook Robert Lopez", "Nicolas Claxton", "Danilo Galinari"). Rules run strictest
    first and only accept a unique candidate, so a miss means the player wasn't listed.
    Returns (espn_player_id, rule) or (None, None).
    """
    method = "exact"
    if "," in name:
        last, first = name.split(",", 1)
        name, method = f"{first} {last}", "comma"
    key = normalize_name(name)
    key = PLAYER_ALIASES.get(key, key)
    if key in roster:
        return roster[key], method
    words = key.split()
    if not words:
        return None, None
    by_words = {k: k.split() for k in roster}

    def unique(keys: list[str], rule: str):
        return (roster[keys[0]], rule) if len(keys) == 1 else (None, None)

    if len(words) == 2 and (flipped := f"{words[1]} {words[0]}") in roster:
        return roster[flipped], "reversed"
    if len(words) > 2 and (short := f"{words[0]} {words[-1]}") in roster:
        return roster[short], "first_last"
    same_last = [k for k, w in by_words.items() if w[-1] == words[-1]]
    first = words[0]
    if len(first) == 1:
        return unique([k for k in same_last if by_words[k][0][0] == first], "initial")
    prefix = [
        k
        for k in same_last
        if min(len(first), len(by_words[k][0])) >= 3
        and (first.startswith(by_words[k][0]) or by_words[k][0].startswith(first))
    ]
    if prefix:
        return unique(prefix, "nickname")
    scored = sorted(
        ((difflib.SequenceMatcher(None, key, k).ratio(), k) for k in roster), reverse=True
    )
    if scored and scored[0][0] >= FUZZY_CUTOFF:
        if len(scored) == 1 or scored[1][0] < scored[0][0] - 0.05:
            return roster[scored[0][1]], "fuzzy"
    return None, None


def match_players(lines: pd.DataFrame, box: pd.DataFrame) -> pd.DataFrame:
    """(espn_game_id, player_name) -> espn_player_id and the rule that matched."""
    rosters = {
        gid: dict(zip(g["player_key"], g["espn_player_id"], strict=True))
        for gid, g in box.groupby("espn_game_id")
    }
    pairs = lines.loc[lines["espn_game_id"].notna(), ["espn_game_id", "player_name"]]
    pairs = pairs.drop_duplicates()
    found = [
        match_name(name, rosters.get(gid, {}))
        for gid, name in zip(pairs["espn_game_id"], pairs["player_name"], strict=True)
    ]
    pairs["espn_player_id"] = [f[0] for f in found]
    pairs["match_method"] = [f[1] for f in found]
    return pairs


def build_outcomes(lines: pd.DataFrame, event_map: pd.DataFrame, box: pd.DataFrame):
    df = lines.merge(event_map, on="event_id", how="left")
    df = df.merge(match_players(df, box), on=["espn_game_id", "player_name"], how="left")
    stats = box[["espn_game_id", "espn_player_id", "did_not_play", "minutes", *_stat_cols()]]
    df = df.merge(stats, on=["espn_game_id", "espn_player_id"], how="left")
    df["matched"] = df["espn_player_id"].notna()
    actual = pd.Series(float("nan"), index=df.index)
    for market, cols in MARKET_STATS.items():
        is_market = df["market"] == market
        actual[is_market] = df.loc[is_market, cols].sum(axis=1, min_count=len(cols))
    df["actual"] = actual
    df["margin"] = df["actual"] - df["point"]

    # played: in the box score with stats; dnp: listed but didn't play; absent: the
    # game matched but the player isn't listed at all (inactive), which books void too
    has_game = df["espn_game_id"].notna()
    dnp = df["matched"] & df["did_not_play"].fillna(False).astype(bool)
    played = df["matched"] & ~dnp
    df["player_status"] = "no_game"
    df.loc[has_game & ~df["matched"], "player_status"] = "absent"
    df.loc[dnp, "player_status"] = "dnp"
    df.loc[played, "player_status"] = "played"
    df["result"] = pd.NA
    df.loc[dnp | (has_game & ~df["matched"]), "result"] = "void"
    df.loc[played & (df["margin"] > 0), "result"] = "over"
    df.loc[played & (df["margin"] < 0), "result"] = "under"
    df.loc[played & (df["margin"] == 0), "result"] = "push"
    return df.drop(columns=_stat_cols()).astype(
        {"result": "category", "player_status": "category", "match_method": "category"}
    )


def _stat_cols() -> list[str]:
    return sorted({c for cols in MARKET_STATS.values() for c in cols})


def report(lines: pd.DataFrame, event_map: pd.DataFrame, result: pd.DataFrame) -> list[str]:
    n = len(result)
    with_game = result["espn_game_id"].notna().sum()
    pct = lambda k, of: f"{k:,} ({k / max(of, 1):.1%})"  # noqa: E731
    out = [
        f"prop lines: {n:,} from {lines['event_id'].nunique():,} events",
        f"  matched to an ESPN game: {pct(with_game, n)}, "
        f"events unmatched: {lines['event_id'].nunique() - len(event_map):,}",
        f"  matched to a box-score player: {pct(result['matched'].sum(), with_game)}",
        "  match rule (lines): "
        + ", ".join(f"{k} {v:,}" for k, v in result["match_method"].value_counts().items()),
        "  player status (lines): "
        + ", ".join(f"{k} {v:,}" for k, v in result["player_status"].value_counts().items()),
        "  results: " + ", ".join(f"{k} {v:,}" for k, v in result["result"].value_counts().items()),
    ]
    absent = result[result["player_status"] == "absent"]
    if len(absent):
        top = absent.groupby(["player_name", "espn_game_id"], observed=True).size()
        top = top.sort_values(ascending=False).head(15)
        out.append(
            "  absent (not in box score, treated as void): "
            + ", ".join(f"{name} ({v})" for (name, _), v in top.items())
        )
    loose = result[result["match_method"].isin(["initial", "nickname", "fuzzy"])]
    if len(loose):
        pairs = loose[["player_name", "espn_game_id", "espn_player_id"]].drop_duplicates()
        out.append(f"  loose matches to eyeball: {len(pairs)} name/game pairs (see match_method)")
    return out


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="python -m nbaprops.tidy", description=__doc__)
    p.add_argument("--data-dir", default="data", type=Path)
    args = p.parse_args(argv)
    rows = Manifest(args.data_dir).rows()
    out_dir = args.data_dir / "tidy"
    out_dir.mkdir(parents=True, exist_ok=True)

    games, box = load_box_scores(rows)
    lines = load_lines(rows)
    if games.empty or lines.empty:
        print(f"nothing to join: {len(games)} games, {len(lines)} prop lines")
        return 1
    event_map = map_events(lines, games)
    result = build_outcomes(lines, event_map, box)

    games.to_parquet(out_dir / "games.parquet", index=False)
    box.to_parquet(out_dir / "box_scores.parquet", index=False)
    lines.to_parquet(out_dir / "prop_lines.parquet", index=False)
    result.to_parquet(out_dir / "prop_outcomes.parquet", index=False)
    print(f"\n=== tidy tables in {out_dir} ===")
    print(f"games: {len(games):,}, box-score rows: {len(box):,}")
    for line in report(lines, event_map, result):
        print(line)
    return 0


if __name__ == "__main__":
    sys.exit(main())
