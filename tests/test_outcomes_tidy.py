import json
from datetime import UTC, datetime

import pandas as pd
import pytest
from conftest import FakeHttp, fixture_bytes, fixture_json

from nbaprops import outcomes, tidy
from nbaprops.http import Response
from nbaprops.storage import Manifest, RawStore

FETCHED = datetime(2026, 10, 30, 12, tzinfo=UTC)


@pytest.fixture(autouse=True)
def no_pause(monkeypatch):
    monkeypatch.setattr(outcomes, "PAUSE", 0)


def espn_http(scoreboard=None):
    return FakeHttp(
        [
            ("/scoreboard", Response(200, scoreboard or fixture_bytes("espn_scoreboard.json"))),
            ("/summary", Response(200, fixture_bytes("espn_summary.json"))),
        ]
    )


def run_outcomes(tmp_path, http, *extra):
    argv = ["--start", "2025-01-15", "--end", "2025-01-15", "--data-dir", str(tmp_path), *extra]
    return outcomes.main(argv, http=http, clock=lambda: FETCHED)


# --- outcomes pull ----------------------------------------------------------


def test_outcomes_fetches_scoreboard_then_final_summaries(tmp_path):
    http = espn_http()
    assert run_outcomes(tmp_path, http) == 0
    urls = [c[1] for c in http.calls]
    assert sum(u.endswith("/scoreboard") for u in urls) == 1
    assert sum(u.endswith("/summary") for u in urls) == 2
    assert ("dates", "20250115") in http.calls[0][2]
    rows = Manifest(tmp_path).rows()
    assert {r["source"] for r in rows} == {"espn"}


def test_outcomes_resume_makes_no_requests(tmp_path):
    run_outcomes(tmp_path, espn_http())
    again = espn_http()
    assert run_outcomes(tmp_path, again) == 0
    assert again.calls == []  # scoreboard read back from disk, summaries already saved


def test_outcomes_skips_games_not_final(tmp_path):
    board = fixture_json("espn_scoreboard.json")
    board["events"][1]["status"]["type"]["name"] = "STATUS_POSTPONED"
    http = espn_http(json.dumps(board).encode())
    run_outcomes(tmp_path, http)
    assert sum(c[1].endswith("/summary") for c in http.calls) == 1


def test_outcomes_dry_run_writes_nothing(tmp_path, capsys):
    http = espn_http()
    run_outcomes(tmp_path, http, "--dry-run")
    assert all(c[1].endswith("/scoreboard") for c in http.calls)
    assert list(tmp_path.iterdir()) == []
    assert "final games: 2" in capsys.readouterr().out


# --- tidy -------------------------------------------------------------------


def test_normalize_name():
    assert tidy.normalize_name("Jaren Jackson Jr.") == "jaren jackson"
    assert tidy.normalize_name("Nikola Joki\u0107") == "nikola jokic"
    assert tidy.normalize_name("Kentavious Caldwell-Pope") == "kentavious caldwell pope"
    assert tidy.normalize_name("De'Aaron Fox") == "deaaron fox"
    assert tidy.team_name("LA Clippers") == "Los Angeles Clippers"


def odds_event_with_extras():
    """The fixture event plus lines for a DNP player, an inactive one, and an exact landing."""
    ev = fixture_json("odds_event_odds.json")
    points = next(m for m in ev["bookmakers"][0]["markets"] if m["key"] == "player_points")
    for player, point in (("Matt Ryan", 4.5), ("OG Anunoby", 17.0), ("Joel Embiid", 24.5)):
        points["outcomes"] += [
            {"name": "Over", "description": player, "price": -110, "point": point},
            {"name": "Under", "description": player, "price": -110, "point": point},
        ]
    return ev


def build_data_dir(tmp_path):
    store, manifest = RawStore(tmp_path), Manifest(tmp_path)
    ev = odds_event_with_extras()
    hist = {"timestamp": "2025-01-15T23:05:38Z", "data": ev}
    path = store.write("odds_api_hist", json.dumps(hist).encode(), FETCHED)
    manifest.append(
        {
            "source": "odds_api_hist",
            "fetched_at": FETCHED.isoformat(),
            "status": "200",
            "request": f"GET historical /events/{ev['id']}/odds [close] date=2025-01-15T23:10:00Z",
            "path": str(path),
        }
    )
    path = store.write("espn", fixture_bytes("espn_summary.json"), FETCHED)
    manifest.append(
        {
            "source": "espn",
            "fetched_at": FETCHED.isoformat(),
            "status": "200",
            "request": "GET summary event=401705127 (NY @ PHI 2025-01-16T00:00Z)",
            "path": str(path),
        }
    )
    return ev


def test_tidy_builds_joined_tables(tmp_path, capsys):
    ev = build_data_dir(tmp_path)
    assert tidy.main(["--data-dir", str(tmp_path)]) == 0
    out = tmp_path / "tidy"
    box = pd.read_parquet(out / "box_scores.parquet")
    lines = pd.read_parquet(out / "prop_lines.parquet")
    res = pd.read_parquet(out / "prop_outcomes.parquet")

    brunson = box[box["player_name"] == "Jalen Brunson"].iloc[0]
    assert (brunson["pts"], brunson["minutes"], brunson["home"]) == (38, 45, False)
    assert box.loc[box["player_name"] == "Matt Ryan", "did_not_play"].item()

    outcome_count = sum(len(m["outcomes"]) for b in ev["bookmakers"] for m in b["markets"])
    assert len(lines) == outcome_count / 2  # over and under side by side
    assert lines["over_price"].notna().all() and lines["under_price"].notna().all()
    assert (lines["kind"] == "close").all()
    assert lines["snapshot_ts"].iloc[0] == pd.Timestamp("2025-01-15T23:05:38Z")

    assert res["espn_game_id"].eq("401705127").all()
    assert res.loc[res["player_name"] != "Joel Embiid", "matched"].all()
    pts = res[res["market"] == "player_points"].set_index(["book", "player_name"])
    b = pts.loc[("draftkings", "Jalen Brunson")]
    assert b["actual"] == 38 and b["margin"] == 38 - b["point"]
    assert b["result"] == ("over" if 38 > b["point"] else "under")
    assert pts.loc[("draftkings", "Matt Ryan"), "result"] == "void"
    assert pts.loc[("draftkings", "OG Anunoby"), "result"] == "push"  # 17 points on 17.0
    assert "matched to a box-score player" in capsys.readouterr().out


def test_tidy_assists_market_uses_assists(tmp_path):
    build_data_dir(tmp_path)
    tidy.main(["--data-dir", str(tmp_path)])
    res = pd.read_parquet(tmp_path / "tidy" / "prop_outcomes.parquet")
    box = pd.read_parquet(tmp_path / "tidy" / "box_scores.parquet")
    ast = res[(res["market"] == "player_assists") & (res["player_name"] == "Jalen Brunson")]
    expected = box.loc[box["player_name"] == "Jalen Brunson", "ast"].item()
    assert (ast["actual"] == expected).all()


ROSTER = {
    tidy.normalize_name(n): str(i)
    for i, n in enumerate(
        [
            "Kyrie Irving",
            "Jerami Grant",
            "Derrick Jones Jr.",
            "Tim Hardaway Jr.",
            "Brook Lopez",
            "Robin Lopez",
            "Nic Claxton",
            "Danilo Gallinari",
            "Thanasis Antetokounmpo",
            "Goga Bitadze",
            "Bub Carrington",
        ]
    )
}


@pytest.mark.parametrize(
    "odds_name, expected, rule",
    [
        ("Kyrie Irving", "Kyrie Irving", "exact"),
        ("Irving, Kyrie", "Kyrie Irving", "comma"),
        ("Grant Jerami", "Jerami Grant", "reversed"),
        ("Brook Robert Lopez", "Brook Lopez", "first_last"),
        ("D. Jones Jr.", "Derrick Jones Jr.", "initial"),
        ("G. Bitadze", "Goga Bitadze", "initial"),
        ("Nicolas Claxton", "Nic Claxton", "nickname"),
        ("Danilo Galinari", "Danilo Gallinari", "fuzzy"),
        ("G Antetokounmpo", None, None),  # Giannis sat; must not become Thanasis
        ("R. Lopez", "Robin Lopez", "initial"),
        ("Lopez", None, None),  # two Lopezes, no way to choose
        ("Carlton Carrington", "Bub Carrington", "exact"),  # alias
    ],
)
def test_match_name_rules(odds_name, expected, rule):
    pid, method = tidy.match_name(odds_name, ROSTER)
    want = ROSTER[tidy.normalize_name(expected)] if expected else None
    assert (pid, method) == (want, rule)


def test_player_missing_from_box_score_is_void(tmp_path):
    build_data_dir(tmp_path)
    tidy.main(["--data-dir", str(tmp_path)])
    res = pd.read_parquet(tmp_path / "tidy" / "prop_outcomes.parquet")
    status = res.groupby("player_name", observed=True)["player_status"].first()
    assert status["Joel Embiid"] == "absent"  # not in the trimmed box score: inactive
    assert status["Matt Ryan"] == "dnp"
    assert status["Jalen Brunson"] == "played"
    assert (res.loc[res["player_status"] != "played", "result"] == "void").all()


def test_parse_summary_skips_partial_athletes():
    summary = fixture_json("espn_summary.json")
    _, rows = tidy.parse_summary(summary)
    summary["boxscore"]["players"][0]["statistics"][0]["athletes"].append(
        {"athlete": {"shortName": "Olbrich"}}
    )
    _, with_partial = tidy.parse_summary(summary)
    assert len(with_partial) == len(rows)
