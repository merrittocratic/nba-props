import json
from datetime import UTC, datetime

import pandas as pd
from conftest import FAKE_KEY
from test_outcomes_tidy import build_data_dir

from nbaprops import gamelines, tidy
from nbaprops.http import Response

# Two games on 2025-01-15 ET: 7:00 pm and 8:00 pm tip-offs (UTC 00:00 and 01:00 next day).
GAMES = [
    {
        "id": "aa01",
        "commence_time": "2025-01-16T00:00:00Z",
        "home_team": "Philadelphia 76ers",
        "away_team": "New York Knicks",
    },
    {
        "id": "aa02",
        "commence_time": "2025-01-16T01:00:00Z",
        "home_team": "Boston Celtics",
        "away_team": "Chicago Bulls",
    },
]


def book_lines(ev):
    home, away = ev["home_team"], ev["away_team"]
    return {
        "key": "draftkings",
        "markets": [
            {
                "key": "h2h",
                "outcomes": [{"name": home, "price": -150}, {"name": away, "price": 130}],
            },
            {
                "key": "spreads",
                "outcomes": [
                    {"name": home, "price": -110, "point": -3.5},
                    {"name": away, "price": -110, "point": 3.5},
                ],
            },
            {
                "key": "totals",
                "outcomes": [
                    {"name": "Over", "price": -105, "point": 221.5},
                    {"name": "Under", "price": -115, "point": 221.5},
                ],
            },
        ],
    }


class SlateFake:
    def __init__(self):
        self.calls = []

    def get(self, url, params=None):
        p = dict(params)
        self.calls.append((url, p))
        if url.endswith("/events"):
            body = {"timestamp": p["date"], "data": GAMES}
            return Response(200, json.dumps(body).encode(), {"x-requests-last": "1"})
        data = [ev | {"bookmakers": [book_lines(ev)]} for ev in GAMES]
        body = {"timestamp": p["date"], "data": data}
        return Response(200, json.dumps(body).encode(), {"x-requests-last": "30"})

    def snapshot_dates(self):
        return [p["date"] for u, p in self.calls if u.endswith("/odds")]


def run(tmp_path, http, *extra):
    argv = ["--start", "2025-01-15", "--end", "2025-01-15", "--data-dir", str(tmp_path), *extra]
    return gamelines.main(argv, http=http, clock=lambda: datetime(2026, 10, 31, tzinfo=UTC))


def test_gamelines_morning_and_each_close(tmp_path, monkeypatch):
    monkeypatch.setenv("ODDS_API_KEY", FAKE_KEY)
    http = SlateFake()
    assert run(tmp_path, http) == 0
    # 11:00 ET morning, then one hour before each tip-off
    assert http.snapshot_dates() == [
        "2025-01-15T16:00:00Z",
        "2025-01-15T23:00:00Z",
        "2025-01-16T00:00:00Z",
    ]
    _, p = next(c for c in http.calls if c[0].endswith("/odds"))
    assert (p["markets"], p["regions"]) == ("h2h,spreads,totals", "us")


def test_gamelines_resume_skips_saved(tmp_path, monkeypatch):
    monkeypatch.setenv("ODDS_API_KEY", FAKE_KEY)
    run(tmp_path, SlateFake())
    again = SlateFake()
    run(tmp_path, again)
    assert again.snapshot_dates() == []


def test_gamelines_dry_run_plans_spend(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("ODDS_API_KEY", FAKE_KEY)
    http = SlateFake()
    run(tmp_path, http, "--dry-run")
    assert http.snapshot_dates() == []
    assert "planned spend: up to 90 credits" in capsys.readouterr().out


def test_tidy_game_lines_table(tmp_path, monkeypatch):
    monkeypatch.setenv("ODDS_API_KEY", FAKE_KEY)
    gl_dir, main_dir = tmp_path / "gamelines", tmp_path / "main"
    run(gl_dir, SlateFake())
    # the main dir holds props and the ESPN summary for NYK @ PHI (2025-01-16 00:00Z)
    build_data_dir(main_dir)
    tidy.main(["--data-dir", str(main_dir), "--data-dir", str(gl_dir)])
    gl = pd.read_parquet(main_dir / "tidy" / "game_lines.parquet")
    assert len(gl) == 3 * 2  # three snapshots x two games, one book
    row = gl[(gl["event_id"] == "aa01") & (gl["minutes_before_tip"] == 60)].iloc[0]
    assert (row["home_spread"], row["total"], row["home_ml"], row["away_ml"]) == (
        -3.5,
        221.5,
        -150,
        130,
    )
    assert (row["over_price"], row["under_price"], row["kind"]) == (-105, -115, "close")
    assert row["espn_game_id"] == "401705127"
    assert gl.loc[gl["event_id"] == "aa02", "espn_game_id"].isna().all()  # no ESPN summary
