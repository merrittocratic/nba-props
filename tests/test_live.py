import json
from datetime import UTC, datetime, timedelta

import pandas as pd
from conftest import FAKE_KEY, fixture_bytes, fixture_json

from nbaprops import inplay, live, snapshots, tidy
from nbaprops.http import Response
from nbaprops.storage import Manifest, RawStore

TIP = datetime(2026, 11, 3, 0, 10, 30, tzinfo=UTC)


class LiveFake:
    """Live API: the fixture event tipping off at TIP, with lines until `ends_after` minutes,
    then empty, or a 404 once `gone_after` minutes have passed."""

    def __init__(self, ends_after=130, gone_after=None, listed=True):
        self.event = fixture_json("odds_event_odds.json") | {
            "commence_time": "2026-11-03T00:10:30Z"
        }
        self.ends_after, self.gone_after, self.listed = ends_after, gone_after, listed
        self.now = TIP
        self.calls = []

    def get(self, url, params=None):
        self.calls.append(url)
        if url.endswith("/events"):
            keys = ("id", "commence_time", "home_team", "away_team")
            listing = [{k: self.event[k] for k in keys}] if self.listed else []
            return Response(200, json.dumps(listing).encode(), {"x-requests-last": "0"})
        minute = (self.now - TIP).total_seconds() / 60
        if self.gone_after is not None and minute > self.gone_after:
            return Response(404, b'{"message": "Event not found"}', {"x-requests-last": "0"})
        live_lines = minute <= self.ends_after
        body = self.event if live_lines else self.event | {"bookmakers": []}
        cost = "1" if live_lines else "0"
        return Response(
            200, json.dumps(body).encode(), {"x-requests-last": cost, "x-requests-remaining": "4e6"}
        )

    def odds_calls(self):
        return sum(u.endswith("/odds") for u in self.calls)


def run_at(tmp_path, http, minute, seconds=40, *extra):
    http.now = TIP + timedelta(minutes=minute, seconds=seconds)
    argv = ["--data-dir", str(tmp_path), *extra]
    return live.main(argv, http=http, clock=lambda: http.now)


def saved(tmp_path):
    return sorted(k for _, k in snapshots.done(Manifest(tmp_path), live.SOURCE))


def test_live_one_snapshot_per_five_minutes(tmp_path, monkeypatch):
    monkeypatch.setenv("ODDS_API_KEY", FAKE_KEY)
    http = LiveFake()
    for minute in (0, 3, 5, 12):  # minute 3 falls in the same step as 0
        assert run_at(tmp_path, http, minute) == 0
    assert http.odds_calls() == 3
    assert saved(tmp_path) == [inplay.kind(0), inplay.kind(5), inplay.kind(10)]


def test_live_stops_after_two_empty_snapshots_late(tmp_path, monkeypatch):
    monkeypatch.setenv("ODDS_API_KEY", FAKE_KEY)
    http = LiveFake(ends_after=131)
    for minute in range(120, 160, 5):
        run_at(tmp_path, http, minute)
    assert http.odds_calls() == 5  # 120..130 with lines, 135 and 140 empty, then stop
    assert inplay.kind(140) in saved(tmp_path)  # empties are saved: the stop rule reads them


def test_live_early_empty_snapshots_do_not_stop(tmp_path, monkeypatch):
    monkeypatch.setenv("ODDS_API_KEY", FAKE_KEY)
    http = LiveFake(ends_after=-1)  # e.g. lines pulled during a long review
    for minute in (20, 25, 30):
        run_at(tmp_path, http, minute)
    assert http.odds_calls() == 3


def test_live_404_is_not_a_failure(tmp_path, monkeypatch):
    monkeypatch.setenv("ODDS_API_KEY", FAKE_KEY)
    http = LiveFake(gone_after=100)
    assert run_at(tmp_path, http, 105) == 0
    assert saved(tmp_path) == []


def test_live_ignores_games_before_tip_and_after_window(tmp_path, monkeypatch):
    monkeypatch.setenv("ODDS_API_KEY", FAKE_KEY)
    http = LiveFake()
    run_at(tmp_path, http, -1)
    run_at(tmp_path, http, inplay.MAX_MINUTES + 1)
    assert http.odds_calls() == 0


def test_live_quiet_listing_writes_nothing(tmp_path, monkeypatch):
    monkeypatch.setenv("ODDS_API_KEY", FAKE_KEY)
    assert run_at(tmp_path, LiveFake(listed=False), 0) == 0
    assert list(tmp_path.iterdir()) == []


def test_live_stops_at_daily_cap(tmp_path, monkeypatch):
    monkeypatch.setenv("ODDS_API_KEY", FAKE_KEY)
    http = LiveFake()
    for minute in (0, 5, 10):
        run_at(tmp_path, http, minute, 40, "--daily-cap", "2")
    assert saved(tmp_path) == [inplay.kind(0), inplay.kind(5)]


def test_tidy_reads_live_snapshots(tmp_path, monkeypatch):
    monkeypatch.setenv("ODDS_API_KEY", FAKE_KEY)
    run_at(tmp_path, LiveFake(), 5)
    path = RawStore(tmp_path).write(
        "espn", fixture_bytes("espn_summary.json"), datetime(2026, 11, 3, 4, tzinfo=UTC)
    )
    Manifest(tmp_path).append(
        {"source": "espn", "status": "200", "request": "GET summary event=401705127", "path": path}
    )
    tidy.main(["--data-dir", str(tmp_path)])
    lines = pd.read_parquet(tmp_path / "tidy" / "prop_lines.parquet")
    assert set(lines["kind"]) == {"inplay_005"} and set(lines["source"]) == {live.SOURCE}
    assert lines["snapshot_ts"].iloc[0] == pd.Timestamp(TIP + timedelta(minutes=5, seconds=40))
