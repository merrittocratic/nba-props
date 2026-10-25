"""Polymarket Gamma (listings) and CLOB (order books) public read APIs (no auth, free).

NBA player props exist on Polymarket (2026-10-24): markets such as
"Giannis Antetokounmpo: Points O/U 28.5" with sportsMarketType points/rebounds/
assists/threes. The raw event pages also carry the game-level markets.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta

from nbaprops.recorder import Recorder

SOURCE = "polymarket"
GAMMA = "https://gamma-api.polymarket.com"
CLOB = "https://clob.polymarket.com"
PROP_TYPES = ("points", "rebounds", "assists", "threes")
PAGE_LIMIT = 100  # documented max for /events/keyset
BOOK_BATCH = 100
MAX_PAGES = 50


def parse_game_start(value: str | None) -> datetime | None:
    # Gamma returns e.g. "2026-10-24 22:00:00+00"
    if not value:
        return None
    text = value.replace(" ", "T")
    if text.endswith(("+00", "-00")):
        text += ":00"
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return None


def prop_tokens(events: list[dict], now: datetime, hours_ahead: int) -> list[str]:
    """CLOB token ids for open player-prop markets whose game starts in the window."""
    end = now + timedelta(hours=hours_ahead)
    tokens = []
    for event in events:
        for m in event.get("markets", []):
            if m.get("sportsMarketType") not in PROP_TYPES:
                continue
            if m.get("closed") or not m.get("enableOrderBook"):
                continue
            start = parse_game_start(m.get("gameStartTime"))
            if start is None or not (now <= start <= end):
                continue
            tokens.extend(json.loads(m.get("clobTokenIds") or "[]"))
    return tokens


def run(rec: Recorder, now: datetime, hours_ahead: int) -> list[str]:
    events: list[dict] = []
    cursor = ""
    for page in range(1, MAX_PAGES + 1):
        params = [("tag_slug", "nba"), ("closed", "false"), ("limit", str(PAGE_LIMIT))]
        if cursor:
            params.append(("after_cursor", cursor))
        resp = rec.fetch(
            SOURCE,
            f"GET gamma /events/keyset tag_slug=nba closed=false page={page}",
            lambda params=params: rec.http.get(f"{GAMMA}/events/keyset", params),
            count_rows=lambda j: len(j["events"]),
        )
        if resp is None:
            break
        body = resp.json()
        events.extend(body.get("events", []))
        cursor = body.get("next_cursor") or ""
        if not cursor or not body.get("events"):
            break

    tokens = prop_tokens(events, now, hours_ahead)
    batches = [tokens[i : i + BOOK_BATCH] for i in range(0, len(tokens), BOOK_BATCH)]
    plan = [
        f"polymarket: {len(events)} open NBA events",
        f"polymarket: order books for {len(tokens)} player-prop tokens in the next "
        f"{hours_ahead}h, in {len(batches)} requests (free)",
    ]
    if rec.dry_run:
        return plan
    for i, batch in enumerate(batches, 1):
        rec.fetch(
            SOURCE,
            f"POST clob /books batch={i}/{len(batches)} n={len(batch)}",
            lambda batch=batch: rec.http.post_json(
                f"{CLOB}/books", [{"token_id": t} for t in batch]
            ),
            count_rows=len,
        )
    return plan
