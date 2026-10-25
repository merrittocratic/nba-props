from datetime import UTC, date, datetime

from nbaprops.budget import CreditBudget
from nbaprops.http import Response
from nbaprops.storage import Manifest, RawStore


def test_raw_store_never_overwrites_and_keeps_bytes(tmp_path):
    store = RawStore(tmp_path)
    ts = datetime(2026, 10, 24, 23, 10, 0, 123456, tzinfo=UTC)
    first = store.write("kalshi", b'{"a": 1}', ts)
    second = store.write("kalshi", b'{"a":  2}', ts)
    assert first == tmp_path / "raw/kalshi/2026-10-24/20261024T231000.123456Z.json"
    assert second != first
    assert first.read_bytes() == b'{"a": 1}'
    assert second.read_bytes() == b'{"a":  2}'


def test_manifest_sums_odds_credits_for_one_day(tmp_path):
    m = Manifest(tmp_path)
    m.append({"source": "odds_api", "fetched_at": "2026-10-24T23:00:00+00:00", "request_cost": 10})
    m.append({"source": "odds_api", "fetched_at": "2026-10-24T23:05:00+00:00", "request_cost": 5})
    m.append({"source": "odds_api", "fetched_at": "2026-10-23T23:00:00+00:00", "request_cost": 99})
    m.append({"source": "kalshi", "fetched_at": "2026-10-24T23:00:00+00:00", "request_cost": 0})
    assert m.credits_spent_on("odds_api", date(2026, 10, 24)) == 15
    assert (
        m.path.read_text()
        .splitlines()[0]
        .startswith("source,fetched_at,status,row_count,request_cost")
    )


def test_budget_daily_cap():
    b = CreditBudget(spent_today=590, remaining=10_000)
    assert b.check(10) is None
    assert "daily cap" in b.check(11)


def test_budget_monthly_floor():
    b = CreditBudget(spent_today=0, remaining=3_005)
    assert b.check(5) is None
    assert "monthly floor" in b.check(10)


def test_budget_records_headers():
    b = CreditBudget(spent_today=0)
    b.record(Response(200, b"{}", {"x-requests-last": "10", "x-requests-remaining": "4999"}))
    assert (b.spent_today, b.remaining) == (10, 4999)
