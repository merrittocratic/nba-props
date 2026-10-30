import csv
import json
from datetime import UTC, datetime, timedelta

from conftest import FAKE_KEY, FakeHttp, fixture_bytes, fixture_json

from nbaprops import backfill, capture, odds_api, snapshots
from nbaprops.budget import CreditBudget
from nbaprops.http import Response
from nbaprops.storage import Manifest

WEEKNIGHT = datetime(2025, 1, 16, 0, 10, tzinfo=UTC)  # Wed 7:10 pm ET
SUNDAY_1PM = datetime(2025, 1, 19, 18, 0, tzinfo=UTC)
CHRISTMAS_NOON = datetime(2024, 12, 25, 17, 0, tzinfo=UTC)


def at(*args):
    return datetime(*args, tzinfo=UTC)


def manifest_rows(tmp_path):
    with open(tmp_path / "manifest.csv", newline="") as f:
        return list(csv.DictReader(f))


def test_weeknight_windows():
    assert snapshots.morning_at(WEEKNIGHT) == at(2025, 1, 15, 16)  # 11 am ET
    assert snapshots.close_at(WEEKNIGHT) == at(2025, 1, 15, 23, 10)
    assert snapshots.due_kind(WEEKNIGHT, at(2025, 1, 15, 2)) == "open"
    assert snapshots.due_kind(WEEKNIGHT, at(2025, 1, 15, 16)) == "morning"
    assert snapshots.due_kind(WEEKNIGHT, at(2025, 1, 15, 23, 15)) == "close"
    assert snapshots.due_kind(WEEKNIGHT, WEEKNIGHT) is None


def test_early_tips_keep_or_drop_morning():
    assert snapshots.morning_at(SUNDAY_1PM) == at(2025, 1, 19, 16)  # 11 am, close at noon
    assert snapshots.morning_at(CHRISTMAS_NOON) is None
    assert snapshots.window("open", CHRISTMAS_NOON)[1] == at(2024, 12, 25, 16)
    assert snapshots.due_kind(CHRISTMAS_NOON, at(2024, 12, 25, 15)) == "open"
    assert snapshots.due_kind(CHRISTMAS_NOON, at(2024, 12, 25, 16)) == "close"


def test_done_reads_only_successful_labeled_rows(tmp_path):
    m = Manifest(tmp_path)
    m.append({"source": "odds_api", "status": "200", "request": "GET /events/abc1/odds [open] x"})
    m.append({"source": "odds_api", "status": "429", "request": "GET /events/abc2/odds [close]"})
    m.append({"source": "other", "status": "200", "request": "GET /events/abc3/odds [close]"})
    assert snapshots.done(m, "odds_api") == {("abc1", "open")}


# --- live capture ---------------------------------------------------------


def live_http(odds_body: bytes, cost: str):
    return FakeHttp(
        [
            ("/odds", Response(200, odds_body, {"x-requests-last": cost})),
            ("/events", Response(200, fixture_bytes("odds_events.json"))),
        ]
    )


def empty_event_body():
    ev = fixture_json("odds_event_odds.json") | {"bookmakers": []}
    return json.dumps(ev).encode()


def test_live_open_check_with_no_lines_is_not_saved(tmp_path, make_recorder):
    rec = make_recorder(live_http(empty_event_body(), "0"))
    _, kinds = odds_api.run(rec, FAKE_KEY, CreditBudget(spent_today=0), at(2025, 1, 15, 2), 30)
    assert kinds == set()
    assert len(manifest_rows(tmp_path)) == 1  # just the events listing
    assert len(list((tmp_path / "raw/odds_api").rglob("*.json"))) == 1


def test_live_snapshot_taken_once_per_kind(tmp_path, make_recorder):
    http = live_http(fixture_bytes("odds_event_odds.json"), "12")
    now = at(2025, 1, 15, 2)
    _, kinds = odds_api.run(make_recorder(http), FAKE_KEY, CreditBudget(spent_today=0), now, 30)
    assert kinds == {"open"}
    odds_calls = sum(1 for c in http.calls if c[1].endswith("/odds"))
    odds_api.run(make_recorder(http), FAKE_KEY, CreditBudget(spent_today=0), now, 30)
    assert sum(1 for c in http.calls if c[1].endswith("/odds")) == odds_calls  # no refetch
    labels = [r["request"] for r in manifest_rows(tmp_path) if "/odds" in r["request"]]
    assert all("[open]" in lab for lab in labels) and len(labels) == 2  # two events


def test_capture_skips_markets_on_open_only_runs(tmp_path, monkeypatch, capsys):
    from test_capture import all_routes

    monkeypatch.setenv("ODDS_API_KEY", FAKE_KEY)
    http = all_routes()
    code = capture.main(["--data-dir", str(tmp_path)], http=http, clock=lambda: at(2025, 1, 15, 2))
    assert code == 0
    assert "kalshi: skipped" in capsys.readouterr().out
    assert not any("kalshi.com" in c[1] or "polymarket" in c[1] for c in http.calls)


# --- backfill -------------------------------------------------------------


class HistFake:
    """Historical API: lines appear at `posted_from`; the event is listed 24h before tip."""

    def __init__(self, posted_from: datetime):
        self.posted_from = posted_from
        self.event = fixture_json("odds_event_odds.json")
        self.tip = snapshots.parse_tip(self.event["commence_time"])
        self.calls = []

    def get(self, url, params=None):
        p = dict(params)
        self.calls.append((url, p))
        when = datetime.fromisoformat(p["date"].replace("Z", "+00:00"))
        wrap = {"timestamp": p["date"]}
        if url.endswith("/events"):
            listing = [{k: self.event[k] for k in ("id", "commence_time", "home_team")}]
            listing[0]["away_team"] = self.event["away_team"]
            body = wrap | {"data": listing if p["commenceTimeFrom"] <= p["date"] else []}
            return Response(200, json.dumps(body).encode(), {"x-requests-last": "1"})
        if when < self.tip - timedelta(hours=24):
            return Response(404, b'{"error_code":"EVENT_NOT_FOUND"}', {"x-requests-last": "0"})
        posted = when >= self.posted_from
        ev = self.event if posted else self.event | {"bookmakers": []}
        cost = 0 if not posted else (10 if p["markets"] == "player_points" else 120)
        body = json.dumps(wrap | {"data": ev}).encode()
        return Response(200, body, {"x-requests-last": str(cost), "x-requests-remaining": "4e6"})


def run_backfill(tmp_path, http, *extra):
    argv = ["--start", "2025-01-15", "--end", "2025-01-15", "--data-dir", str(tmp_path), *extra]
    return backfill.main(argv, http=http, clock=lambda: at(2026, 10, 25, 12))


def full_fetch_dates(http):
    return [
        p["date"] for u, p in http.calls if u.endswith("/odds") and p["markets"] != "player_points"
    ]


def test_backfill_finds_open_and_takes_three_snapshots(tmp_path, monkeypatch):
    monkeypatch.setenv("ODDS_API_KEY", FAKE_KEY)
    http = HistFake(posted_from=at(2025, 1, 15, 3, 7))  # 10:07 pm ET the night before
    assert run_backfill(tmp_path, http) == 0
    # open at the first 15-minute grid point at or after posting; grid starts at tip-30h
    assert full_fetch_dates(http) == [
        "2025-01-15T03:10:00Z",
        "2025-01-15T16:00:00Z",
        "2025-01-15T23:10:00Z",
    ]
    rows = manifest_rows(tmp_path)
    assert {r["source"] for r in rows} == {"odds_api_hist"}
    # paid probes are in the manifest so the cap sees them; free ones are not
    assert all(r["request_cost"] == "10" for r in rows if "discarded" in r["status"])
    probes = [u for u, p in http.calls if p.get("markets") == "player_points"]
    assert len(probes) <= 8


def test_backfill_resumes_without_refetching(tmp_path, monkeypatch):
    monkeypatch.setenv("ODDS_API_KEY", FAKE_KEY)
    run_backfill(tmp_path, HistFake(posted_from=at(2025, 1, 15, 3, 7)))
    again = HistFake(posted_from=at(2025, 1, 15, 3, 7))
    assert run_backfill(tmp_path, again) == 0
    assert full_fetch_dates(again) == []


def test_backfill_stops_at_its_own_cap(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("ODDS_API_KEY", FAKE_KEY)
    http = HistFake(posted_from=at(2025, 1, 15, 3, 7))
    run_backfill(tmp_path, http, "--daily-cap", "100")
    assert full_fetch_dates(http) == []
    assert "stopped: daily cap" in capsys.readouterr().out


def test_backfill_dry_run_lists_only(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("ODDS_API_KEY", FAKE_KEY)
    http = HistFake(posted_from=at(2025, 1, 15, 3, 7))
    run_backfill(tmp_path, http, "--dry-run")
    assert all(u.endswith("/events") for u, _ in http.calls)
    assert list(tmp_path.iterdir()) == []
    assert "snapshots not yet taken: 3" in capsys.readouterr().out
