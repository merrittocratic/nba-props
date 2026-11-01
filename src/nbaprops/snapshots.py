"""The three Odds API snapshots per game, shared by the live capture and the backfill.

- open: the first snapshot with prop lines posted (books post the evening before)
- morning: 11:00 ET on game day, skipped when it falls within an hour of close
- close: one hour before tip-off

Each kind owns a window [start, end) before tip-off, and the windows don't overlap,
so at any moment at most one snapshot is due for a game.

On top of those, a points-only "intraday" snapshot every 2 hours between the open and
close (kinds pts_t28 .. pts_t02, the hours left before tip-off), so the line and price
can be followed through the day. See intraday_kind.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime, time, timedelta
from zoneinfo import ZoneInfo

from nbaprops.storage import Manifest

ET = ZoneInfo("America/New_York")
KINDS = ("open", "morning", "close")
MORNING_ET = time(11, 0)
CLOSE_LEAD = timedelta(hours=1)
MORNING_MIN_GAP = timedelta(hours=1)
# Events appear in the Odds API about a day before tip-off; look a little further back.
OPEN_LOOKBACK = timedelta(hours=30)

INTRADAY_STEP = timedelta(hours=2)

_LABEL = re.compile(r"/events/([0-9a-f]+)/odds \[(\w+)\]")


def parse_tip(commence_time: str) -> datetime:
    return datetime.fromisoformat(commence_time.replace("Z", "+00:00"))


def close_at(tip: datetime) -> datetime:
    return tip - CLOSE_LEAD


def morning_at(tip: datetime) -> datetime | None:
    """11:00 ET on the game's ET date (as UTC), or None when it would crowd close."""
    morning = datetime.combine(tip.astimezone(ET).date(), MORNING_ET, ET).astimezone(UTC)
    return morning if morning <= close_at(tip) - MORNING_MIN_GAP else None


def window(kind: str, tip: datetime) -> tuple[datetime, datetime] | None:
    morning = morning_at(tip)
    if kind == "open":
        return tip - OPEN_LOOKBACK, morning or close_at(tip)
    if kind == "morning":
        return (morning, close_at(tip)) if morning else None
    if kind == "close":
        return close_at(tip), tip
    raise ValueError(kind)


def due_kind(tip: datetime, now: datetime) -> str | None:
    for kind in KINDS:
        w = window(kind, tip)
        if w and w[0] <= now < w[1]:
            return kind
    return None


def intraday_kind(tip: datetime, now: datetime) -> str | None:
    """'pts_tHH' when now is HH to HH+2 hours before tip-off (HH even, 2..28), else None.

    The last 2 hours are left to the close snapshot.
    """
    left = tip - now
    if left < INTRADAY_STEP or left >= OPEN_LOOKBACK:
        return None
    return f"pts_t{int(left // INTRADAY_STEP) * 2:02d}"


def label(event_id: str, kind: str) -> str:
    """Manifest request label prefix; `done` parses it back."""
    return f"/events/{event_id}/odds [{kind}]"


def parse_label(request: str) -> tuple[str, str] | None:
    """(event_id, kind) from a manifest request label, or None."""
    m = _LABEL.search(request)
    return (m.group(1), m.group(2)) if m else None


def done(manifest: Manifest, source: str) -> set[tuple[str, str]]:
    """(event_id, kind) pairs already captured with a 200 for `source`."""
    pairs = set()
    for row in manifest.rows():
        if row["source"] == source and row["status"] == "200":
            if pair := parse_label(row["request"]):
                pairs.add(pair)
    return pairs
