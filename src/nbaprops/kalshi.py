"""Kalshi public read API: NBA player prop markets and their order books (no auth, free)."""

from __future__ import annotations

from nbaprops.recorder import Recorder

SOURCE = "kalshi"
BASE = "https://external-api.kalshi.com/trade-api/v2"
# Found in GET /series?category=Sports on 2026-10-24. Points, rebounds and assists, plus
# threes and pts+reb+ast to match the Odds API markets. The two-stat combos (PR, PA, RA)
# had no open markets on 2026-10-25 but cost one free request each, so they are kept in
# case Kalshi lists them. Not captured: steals, blocks, double-doubles, KXNBAPTSPROT;
# see docs/decisions.md for why.
SERIES = (
    "KXNBAPTS",
    "KXNBAREB",
    "KXNBAAST",
    "KXNBA3PT",
    "KXNBAPRA",
    "KXNBAPR",
    "KXNBAPA",
    "KXNBARA",
)
PAGE_LIMIT = 1000
ORDERBOOK_BATCH = 100  # documented max tickers per GET /markets/orderbooks
MAX_PAGES = 20


def chunks(items: list, size: int) -> list[list]:
    return [items[i : i + size] for i in range(0, len(items), size)]


def run(rec: Recorder) -> list[str]:
    tickers: list[str] = []
    plan = []
    for series in SERIES:
        cursor = ""
        found = 0
        for page in range(1, MAX_PAGES + 1):
            params = [("series_ticker", series), ("status", "open"), ("limit", str(PAGE_LIMIT))]
            if cursor:
                params.append(("cursor", cursor))
            resp = rec.fetch(
                SOURCE,
                f"GET /markets series_ticker={series} page={page}",
                lambda params=params: rec.http.get(f"{BASE}/markets", params),
                count_rows=lambda j: len(j["markets"]),
            )
            if resp is None:
                break
            body = resp.json()
            page_tickers = [m["ticker"] for m in body.get("markets", [])]
            tickers.extend(page_tickers)
            found += len(page_tickers)
            cursor = body.get("cursor") or ""
            if not cursor or not page_tickers:
                break
        plan.append(f"kalshi: {series}: {found} open markets")

    batches = chunks(tickers, ORDERBOOK_BATCH)
    plan.append(f"kalshi: order books for {len(tickers)} markets in {len(batches)} requests (free)")
    if rec.dry_run:
        return plan
    for i, batch in enumerate(batches, 1):
        rec.fetch(
            SOURCE,
            f"GET /markets/orderbooks batch={i}/{len(batches)} n={len(batch)}",
            lambda batch=batch: rec.http.get(
                f"{BASE}/markets/orderbooks", [("tickers", t) for t in batch]
            ),
            count_rows=lambda j: len(j["orderbooks"]),
        )
    return plan
