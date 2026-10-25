import csv
import json
from datetime import UTC, datetime

from conftest import FAKE_KEY, FakeHttp, fixture_bytes, fixture_json

from nbaprops import kalshi, odds_api, polymarket
from nbaprops.budget import CreditBudget
from nbaprops.http import Response

ODDS_HEADERS = {"x-requests-last": "10", "x-requests-remaining": "19000"}


def odds_http():
    return FakeHttp(
        [
            ("/odds", Response(200, fixture_bytes("odds_event_odds.json"), ODDS_HEADERS)),
            (
                "/events",
                Response(
                    200,
                    fixture_bytes("odds_events.json"),
                    {"x-requests-last": "0", "x-requests-remaining": "19010"},
                ),
            ),
        ]
    )


def manifest_rows(tmp_path):
    with open(tmp_path / "manifest.csv", newline="") as f:
        return list(csv.DictReader(f))


def test_odds_api_writes_raw_files_and_manifest(tmp_path, make_recorder, clock):
    http = odds_http()
    rec = make_recorder(http)
    budget = CreditBudget(spent_today=0)
    odds_api.run(rec, FAKE_KEY, budget, clock(), 24)

    rows = manifest_rows(tmp_path)
    assert [r["source"] for r in rows] == ["odds_api"] * 3
    assert [r["request_cost"] for r in rows] == ["0", "10", "10"]
    assert all(r["status"] == "200" for r in rows)
    expected_outcomes = odds_api.count_outcomes(fixture_json("odds_event_odds.json"))
    assert rows[1]["row_count"] == str(expected_outcomes)
    # raw bodies are stored unmodified
    assert open(rows[1]["path"], "rb").read() == fixture_bytes("odds_event_odds.json")
    assert budget.spent_today == 20
    # every paid call asks for all markets and regions
    _, _, params = http.calls[1]
    assert ("markets", ",".join(odds_api.MARKETS)) in params
    assert ("regions", "us,us_dfs") in params


def test_odds_api_key_never_written(tmp_path, make_recorder, clock, caplog):
    caplog.set_level("INFO")
    odds_api.run(make_recorder(odds_http()), FAKE_KEY, CreditBudget(spent_today=0), clock(), 24)
    for path in tmp_path.rglob("*"):
        if path.is_file():
            assert FAKE_KEY not in path.read_text()
    assert FAKE_KEY not in caplog.text


def test_odds_api_stops_at_daily_cap(tmp_path, make_recorder, clock):
    http = odds_http()
    budget = CreditBudget(spent_today=580)  # room for one event (worst case 12, billed 10)
    odds_api.run(make_recorder(http), FAKE_KEY, budget, clock(), 24)
    rows = manifest_rows(tmp_path)
    assert [r["status"][:8] for r in rows] == ["200", "200", "skipped:"]
    assert sum(1 for c in http.calls if c[1].endswith("/odds")) == 1


def test_odds_api_stops_at_monthly_floor(tmp_path, make_recorder, clock):
    http = FakeHttp(
        [
            (
                "/events",
                Response(200, fixture_bytes("odds_events.json"), {"x-requests-remaining": "3005"}),
            )
        ]
    )
    odds_api.run(make_recorder(http), FAKE_KEY, CreditBudget(spent_today=0), clock(), 24)
    rows = manifest_rows(tmp_path)
    assert all("monthly floor" in r["status"] for r in rows[1:])
    assert len(http.calls) == 1


def test_odds_api_failure_is_logged_and_run_continues(tmp_path, make_recorder, clock):
    http = FakeHttp(
        [
            (
                "/odds",
                [
                    Response(401, b'{"message":"bad key"}'),
                    Response(200, fixture_bytes("odds_event_odds.json")),
                ],
            ),
            ("/events", Response(200, fixture_bytes("odds_events.json"))),
        ]
    )
    rec = make_recorder(http)
    odds_api.run(rec, FAKE_KEY, CreditBudget(spent_today=0), clock(), 24)
    statuses = [r["status"] for r in manifest_rows(tmp_path)]
    assert statuses == ["200", "401", "200"]  # 401 not retried, next event still fetched
    assert rec.failures == 1


def test_kalshi_pages_and_batches_orderbooks(tmp_path, make_recorder, monkeypatch):
    monkeypatch.setattr(kalshi, "SERIES", ("KXNBAPTS",))
    monkeypatch.setattr(kalshi, "ORDERBOOK_BATCH", 2)
    page1 = fixture_json("kalshi_markets.json") | {"cursor": "abc"}
    http = FakeHttp(
        [
            ("/markets/orderbooks", Response(200, fixture_bytes("kalshi_orderbooks.json"))),
            (
                "/markets",
                [
                    Response(200, json.dumps(page1).encode()),
                    Response(200, fixture_bytes("kalshi_markets.json")),
                ],
            ),
        ]
    )
    plan = kalshi.run(make_recorder(http))
    book_calls = [c for c in http.calls if "orderbooks" in c[1]]
    assert len(book_calls) == 3  # 6 tickers across two pages, batches of 2
    assert ("cursor", "abc") in http.calls[1][2]
    assert "6 open markets" in plan[0]
    sources = {r["source"] for r in manifest_rows(tmp_path)}
    assert sources == {"kalshi"}
    assert len(list((tmp_path / "raw/kalshi").rglob("*.json"))) == 5


def test_polymarket_books_only_for_props_in_window(tmp_path, make_recorder):
    http = FakeHttp(
        [
            ("/events/keyset", Response(200, fixture_bytes("polymarket_events.json"))),
            ("/books", Response(200, fixture_bytes("polymarket_books.json"))),
        ]
    )
    now = datetime(2026, 10, 24, 12, 0, tzinfo=UTC)
    polymarket.run(make_recorder(http), now, 24)
    posts = [c for c in http.calls if c[0] == "POST"]
    assert len(posts) == 1
    assert len(posts[0][2]) == 4  # 2 prop markets x 2 tokens; the spread market is excluded
    rows = manifest_rows(tmp_path)
    assert [r["row_count"] for r in rows] == ["1", "2"]


def test_polymarket_outside_window_fetches_no_books(make_recorder):
    http = FakeHttp([("/events/keyset", Response(200, fixture_bytes("polymarket_events.json")))])
    polymarket.run(make_recorder(http), datetime(2026, 10, 26, tzinfo=UTC), 24)
    assert all(c[0] == "GET" for c in http.calls)


def test_parse_game_start():
    assert polymarket.parse_game_start("2026-10-24 22:00:00+00") == datetime(
        2026, 10, 24, 22, tzinfo=UTC
    )
    assert polymarket.parse_game_start(None) is None
