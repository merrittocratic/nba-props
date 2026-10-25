from conftest import FAKE_KEY, FakeHttp, fixture_bytes

from nbaprops import capture
from nbaprops.http import Response


def all_routes():
    return FakeHttp(
        [
            (
                "api.the-odds-api.com/v4/sports/basketball_nba/events/",
                Response(200, fixture_bytes("odds_event_odds.json"), {"x-requests-last": "10"}),
            ),
            (
                "api.the-odds-api.com",
                Response(
                    200,
                    fixture_bytes("odds_events.json"),
                    {"x-requests-last": "0", "x-requests-remaining": "19000"},
                ),
            ),
            ("/markets/orderbooks", Response(200, fixture_bytes("kalshi_orderbooks.json"))),
            ("kalshi.com", Response(200, fixture_bytes("kalshi_markets.json"))),
            ("/events/keyset", Response(200, fixture_bytes("polymarket_events.json"))),
            ("/books", Response(200, fixture_bytes("polymarket_books.json"))),
        ]
    )


def test_dry_run_writes_nothing_and_makes_no_paid_calls(tmp_path, monkeypatch, capsys, clock):
    monkeypatch.setenv("ODDS_API_KEY", FAKE_KEY)
    http = all_routes()
    code = capture.main(["--dry-run", "--data-dir", str(tmp_path)], http=http, clock=clock)
    out = capsys.readouterr().out
    assert code == 0
    assert list(tmp_path.iterdir()) == []
    assert not any(c[1].endswith("/odds") for c in http.calls)
    assert not any(c[0] == "POST" or "orderbooks" in c[1] for c in http.calls)
    assert "DRY RUN" in out
    assert "up to 24 for this run" in out  # 2 events x 6 markets x 2 regions
    assert FAKE_KEY not in out


def test_real_run_writes_every_source(tmp_path, monkeypatch, clock):
    monkeypatch.setenv("ODDS_API_KEY", FAKE_KEY)
    code = capture.main(["--data-dir", str(tmp_path)], http=all_routes(), clock=clock)
    assert code == 0
    assert {p.name for p in (tmp_path / "raw").iterdir()} == {"odds_api", "kalshi", "polymarket"}
    assert (tmp_path / "manifest.csv").exists()


def test_missing_key_skips_odds_but_runs_others(tmp_path, monkeypatch, clock):
    monkeypatch.delenv("ODDS_API_KEY", raising=False)
    code = capture.main(["--data-dir", str(tmp_path)], http=all_routes(), clock=clock)
    assert code == 1
    assert {p.name for p in (tmp_path / "raw").iterdir()} == {"kalshi", "polymarket"}
