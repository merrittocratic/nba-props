import json
from datetime import UTC, datetime, timedelta

import pandas as pd
from conftest import FAKE_KEY, fixture_bytes, fixture_json

from nbaprops import inplay, snapshots, tidy
from nbaprops.http import Response
from nbaprops.storage import Manifest, RawStore


class InPlayFake:
    """Historical API for one game: in-game lines from tip-off to `ends_after` minutes,
    with optional gaps (minutes with no lines)."""

    def __init__(self, ends_after=130, gaps=(), gone_after=None):
        self.event = fixture_json("odds_event_odds.json")
        self.tip = snapshots.parse_tip(self.event["commence_time"])
        self.ends_after, self.gaps, self.gone_after = ends_after, set(gaps), gone_after
        self.calls = []

    def get(self, url, params=None):
        p = dict(params)
        self.calls.append((url, p))
        if url.endswith("/events"):
            listing = [
                {k: self.event[k] for k in ("id", "commence_time", "home_team", "away_team")}
            ]
            body = {"timestamp": p["date"], "data": listing}
            return Response(200, json.dumps(body).encode(), {"x-requests-last": "1"})
        when = datetime.fromisoformat(p["date"].replace("Z", "+00:00"))
        minute = int((when - self.tip).total_seconds() // 60)
        live = 0 <= minute <= self.ends_after and minute not in self.gaps
        if self.gone_after is not None and minute > self.gone_after:
            return Response(404, b'{"message": "Event not found"}', {"x-requests-last": "0"})
        ev = self.event if live else self.event | {"bookmakers": []}
        body = json.dumps({"timestamp": p["date"], "data": ev}).encode()
        cost = "10" if live else "0"
        return Response(200, body, {"x-requests-last": cost, "x-requests-remaining": "4e6"})

    def odds_minutes(self):
        return [
            int((datetime.fromisoformat(p["date"].replace("Z", "+00:00")) - self.tip).seconds // 60)
            for u, p in self.calls
            if u.endswith("/odds")
        ]


def run(tmp_path, http, *extra):
    argv = ["--start", "2025-01-15", "--end", "2025-01-15", "--data-dir", str(tmp_path), *extra]
    return inplay.main(argv, http=http, clock=lambda: datetime(2026, 10, 30, 12, tzinfo=UTC))


def saved_kinds(tmp_path):
    return sorted(k for _, k in snapshots.done(Manifest(tmp_path), inplay.SOURCE))


def test_inplay_every_five_minutes_until_lines_stop(tmp_path, monkeypatch):
    monkeypatch.setenv("ODDS_API_KEY", FAKE_KEY)
    http = InPlayFake(ends_after=130)
    assert run(tmp_path, http) == 0
    assert http.odds_minutes() == list(range(0, 145, 5))  # 135 and 140 empty: stop
    assert saved_kinds(tmp_path) == [inplay.kind(m) for m in range(0, 135, 5)]
    _, p = next(c for c in http.calls if c[0].endswith("/odds"))
    assert (p["markets"], p["regions"]) == ("player_points", "us")


def test_inplay_404_after_game_ends_is_not_a_failure(tmp_path, monkeypatch):
    monkeypatch.setenv("ODDS_API_KEY", FAKE_KEY)
    http = InPlayFake(ends_after=130, gone_after=135)
    assert run(tmp_path, http) == 0
    assert http.odds_minutes() == list(range(0, 145, 5))
    assert {r["status"] for r in Manifest(tmp_path).rows()} == {"200"}


def test_inplay_mid_game_gap_does_not_stop(tmp_path, monkeypatch):
    monkeypatch.setenv("ODDS_API_KEY", FAKE_KEY)
    http = InPlayFake(ends_after=130, gaps={40, 45, 50})
    run(tmp_path, http)
    assert inplay.kind(55) in saved_kinds(tmp_path)
    assert inplay.kind(45) not in saved_kinds(tmp_path)  # empty snapshots aren't saved
    costs = [int(r["request_cost"]) for r in Manifest(tmp_path).rows()]
    assert 0 not in costs  # free empty checks leave no manifest rows


def test_inplay_resume_rechecks_only_the_tail(tmp_path, monkeypatch):
    monkeypatch.setenv("ODDS_API_KEY", FAKE_KEY)
    run(tmp_path, InPlayFake(ends_after=130))
    again = InPlayFake(ends_after=130)
    run(tmp_path, again)
    assert again.odds_minutes() == [135, 140]


def test_inplay_stops_at_cap(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("ODDS_API_KEY", FAKE_KEY)
    run(tmp_path, InPlayFake(), "--daily-cap", "51")  # listing (1) + five snapshots
    assert len(saved_kinds(tmp_path)) == 5
    assert "stopped: daily cap" in capsys.readouterr().out


def test_tidy_includes_inplay_snapshots(tmp_path, monkeypatch):
    monkeypatch.setenv("ODDS_API_KEY", FAKE_KEY)
    run(tmp_path, InPlayFake(ends_after=10))
    path = RawStore(tmp_path).write(
        "espn", fixture_bytes("espn_summary.json"), datetime(2026, 10, 30, tzinfo=UTC)
    )
    Manifest(tmp_path).append(
        {"source": "espn", "status": "200", "request": "GET summary event=401705127", "path": path}
    )
    assert tidy.main(["--data-dir", str(tmp_path)]) == 0
    lines = pd.read_parquet(tmp_path / "tidy" / "prop_lines.parquet")
    assert set(lines["kind"]) == {"inplay_000", "inplay_005", "inplay_010"}
    assert set(lines["source"]) == {"odds_api_inplay"}
    assert lines["snapshot_ts"].min() == pd.Timestamp(InPlayFake().tip) + timedelta(0)
