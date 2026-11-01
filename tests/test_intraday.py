import json
from datetime import UTC, datetime, timedelta

import pandas as pd
from conftest import FAKE_KEY, fixture_bytes, fixture_json

from nbaprops import intraday, snapshots, tidy
from nbaprops.http import Response
from nbaprops.storage import Manifest, RawStore


class PregameFake:
    """Historical API for one game: listed 24h before tip, lines posted from `posted_from`."""

    def __init__(self, posted_from: datetime):
        self.event = fixture_json("odds_event_odds.json")
        self.tip = snapshots.parse_tip(self.event["commence_time"])
        self.posted_from = posted_from
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
        if when < self.tip - timedelta(hours=24):
            return Response(404, b'{"error_code":"EVENT_NOT_FOUND"}', {"x-requests-last": "0"})
        posted = when >= self.posted_from
        ev = self.event if posted else self.event | {"bookmakers": []}
        body = json.dumps({"timestamp": p["date"], "data": ev}).encode()
        cost = "10" if posted else "0"
        return Response(200, body, {"x-requests-last": cost, "x-requests-remaining": "4e6"})

    def odds_calls(self):
        return [p for u, p in self.calls if u.endswith("/odds")]


def run(tmp_path, http, *extra):
    argv = ["--start", "2025-01-15", "--end", "2025-01-15", "--data-dir", str(tmp_path), *extra]
    return intraday.main(argv, http=http, clock=lambda: datetime(2026, 11, 1, 12, tzinfo=UTC))


def saved_kinds(tmp_path):
    return sorted(k for _, k in snapshots.done(Manifest(tmp_path), intraday.SOURCE))


def test_slots_match_live_labels():
    tip = datetime(2025, 1, 16, 0, 10, tzinfo=UTC)
    got = intraday.slots(tip)
    assert [k for k, _ in got] == [f"pts_t{h:02d}" for h in range(28, 0, -2)]
    for k, at in got:  # each fetch time falls inside its own slot, as the live capture sees it
        assert snapshots.intraday_kind(tip, at) == k


def test_intraday_saves_only_slots_with_lines(tmp_path, monkeypatch):
    monkeypatch.setenv("ODDS_API_KEY", FAKE_KEY)
    tip = PregameFake(datetime(2025, 1, 1, tzinfo=UTC)).tip
    http = PregameFake(posted_from=tip - timedelta(hours=21))
    assert run(tmp_path, http) == 0
    # posted 21h out: pts_t20 is fetched 21h55m out, before posting; pts_t18 on have lines.
    assert saved_kinds(tmp_path) == sorted(f"pts_t{h:02d}" for h in range(18, 0, -2))
    for p in http.odds_calls():
        assert p["markets"] == "player_points" and p["regions"] == "us"


def test_intraday_404_and_empty_are_free_and_not_failures(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("ODDS_API_KEY", FAKE_KEY)
    tip = PregameFake(datetime(2025, 1, 1, tzinfo=UTC)).tip
    http = PregameFake(posted_from=tip - timedelta(hours=4))  # pts_t02 fetched 3h55m out
    assert run(tmp_path, http) == 0
    assert saved_kinds(tmp_path) == ["pts_t02"]
    out = capsys.readouterr().out
    assert "failures: 0" in out


def test_intraday_resume_skips_saved(tmp_path, monkeypatch):
    monkeypatch.setenv("ODDS_API_KEY", FAKE_KEY)
    tip = PregameFake(datetime(2025, 1, 1, tzinfo=UTC)).tip
    http = PregameFake(posted_from=tip - timedelta(hours=30))
    run(tmp_path, http)
    first = len(http.odds_calls())
    run(tmp_path, http)
    # only the slots before the event was listed (404, not saved) are re-checked
    rechecked = len(http.odds_calls()) - first
    assert rechecked == 14 - len(saved_kinds(tmp_path))


def test_intraday_stops_at_cap(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("ODDS_API_KEY", FAKE_KEY)
    tip = PregameFake(datetime(2025, 1, 1, tzinfo=UTC)).tip
    http = PregameFake(posted_from=tip - timedelta(hours=30))
    run(tmp_path, http, "--daily-cap", "31")  # listing 1 + three 10-credit snapshots
    assert len(saved_kinds(tmp_path)) == 3
    assert "stopped: daily cap" in capsys.readouterr().out


def test_tidy_includes_intraday_snapshots(tmp_path, monkeypatch):
    monkeypatch.setenv("ODDS_API_KEY", FAKE_KEY)
    tip = PregameFake(datetime(2025, 1, 1, tzinfo=UTC)).tip
    run(tmp_path, PregameFake(posted_from=tip - timedelta(hours=6)))  # t04 at 5h55m
    path = RawStore(tmp_path).write(
        "espn", fixture_bytes("espn_summary.json"), datetime(2026, 11, 1, tzinfo=UTC)
    )
    Manifest(tmp_path).append(
        {"source": "espn", "status": "200", "request": "GET summary event=401705127", "path": path}
    )
    assert tidy.main(["--data-dir", str(tmp_path)]) == 0
    lines = pd.read_parquet(tmp_path / "tidy" / "prop_lines.parquet")
    assert set(lines.kind.astype(str)) == {"pts_t04", "pts_t02"}
    assert set(lines.source.astype(str)) == {intraday.SOURCE}
