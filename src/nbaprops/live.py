"""Entry point: python -m nbaprops.live [--dry-run]

Live in-game player_points lines from US sportsbooks. Meant to run every 5 minutes:
each run lists games that tipped off in the last few hours (free) and takes one
snapshot per game in progress (1 credit), labeled [inplay_MMM] by minutes after
tip-off in 5-minute steps, the same labels as the historical nbaprops.inplay.

A game is followed until minute 210, or until two checks in a row past minute 90
find no lines. Empty snapshots are saved (they're tiny) because the next run reads
them from the manifest to know the game is over. Listings with no game in progress
aren't saved, so idle hours leave nothing behind.

Spend is tracked under its own manifest source with its own daily cap, apart from
the pregame capture. A dry run makes only the free listing call and writes nothing.
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path

from nbaprops import snapshots
from nbaprops.budget import CreditBudget, header_int
from nbaprops.http import Http, UrllibHttp
from nbaprops.inplay import (
    MARKET,
    MAX_MINUTES,
    QUIET_AFTER_MINUTES,
    QUIET_STOP,
    REGION,
    STEP_MINUTES,
    kind,
)
from nbaprops.odds_api import BASE, count_outcomes, iso_z
from nbaprops.recorder import Recorder, utcnow
from nbaprops.storage import Manifest, RawStore

log = logging.getLogger("nbaprops")

SOURCE = "odds_api_live"
COST = 1  # live odds cost markets x regions: one market, one region
DAILY_CAP = 800  # about 30 snapshots a game; 15 games x 43 snapshots at most is 645
LOOKBACK = timedelta(minutes=MAX_MINUTES + 30)


def history(manifest: Manifest) -> dict[str, dict[int, int]]:
    """event_id -> {minute after tip-off: lines in that snapshot} for snapshots saved."""
    seen: dict[str, dict[int, int]] = defaultdict(dict)
    for row in manifest.rows():
        if row["source"] != SOURCE or row["status"] != "200":
            continue
        pair = snapshots.parse_label(row["request"])
        if pair and pair[1].startswith("inplay_"):
            seen[pair[0]][int(pair[1].removeprefix("inplay_"))] = int(row["row_count"] or 0)
    return seen


def ended(game: dict[int, int]) -> bool:
    """Two empty snapshots in a row, the later one past QUIET_AFTER_MINUTES."""
    last = sorted(game)[-QUIET_STOP:]
    return (
        len(last) == QUIET_STOP
        and last[-1] >= QUIET_AFTER_MINUTES
        and all(game[m] == 0 for m in last)
    )


def minute_now(tip: datetime, now: datetime) -> int | None:
    """Minutes after tip-off, rounded down to the step, or None outside the game window."""
    minutes = (now - tip).total_seconds() // 60
    if minutes < 0 or minutes > MAX_MINUTES:
        return None
    return int(minutes) // STEP_MINUTES * STEP_MINUTES


def cost(resp) -> int:
    return header_int(resp, "x-requests-last") or 0


def parse_args(argv: list[str] | None) -> argparse.Namespace:
    p = argparse.ArgumentParser(prog="python -m nbaprops.live", description=__doc__)
    p.add_argument("--dry-run", action="store_true", help="free listing call only; write nothing")
    p.add_argument("--data-dir", default="data", type=Path)
    p.add_argument("--daily-cap", default=DAILY_CAP, type=int, help="credits per UTC day")
    return p.parse_args(argv)


def main(argv: list[str] | None = None, http: Http | None = None, clock=utcnow) -> int:
    args = parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    api_key = os.environ.get("ODDS_API_KEY", "").strip()
    if not api_key:
        log.error("ODDS_API_KEY is not set")
        return 2
    now = clock()
    manifest = Manifest(args.data_dir)
    rec = Recorder(
        http or UrllibHttp(),
        RawStore(args.data_dir),
        manifest,
        dry_run=args.dry_run,
        clock=clock,
        redact=(api_key,),
    )
    budget = CreditBudget(
        spent_today=manifest.credits_spent_on(SOURCE, now.date()), daily_cap=args.daily_cap
    )
    window = (iso_z(now - LOOKBACK), iso_z(now))
    resp = rec.fetch(
        SOURCE,
        f"GET /events commenceTimeFrom={window[0]} commenceTimeTo={window[1]}",
        lambda: rec.http.get(
            f"{BASE}/events",
            [
                ("apiKey", api_key),
                ("dateFormat", "iso"),
                ("commenceTimeFrom", window[0]),
                ("commenceTimeTo", window[1]),
            ],
        ),
        count_rows=len,
        cost=cost,
        precheck=lambda: budget.check(0),
        on_response=budget.record,
        keep=lambda r: not r.ok or bool(r.json()),  # an empty listing isn't worth a file
    )
    events = resp.json() if resp is not None and resp.ok else []

    seen = history(manifest)
    due = []
    for ev in events:
        minute = minute_now(snapshots.parse_tip(ev["commence_time"]), now)
        game = seen.get(ev["id"], {})
        if minute is not None and minute not in game and not ended(game):
            due.append((ev, minute))

    saved = 0
    for ev, minute in due:
        label = f"{ev['away_team']} @ {ev['home_team']} {ev['commence_time']}"
        if rec.dry_run:
            log.info("[%s] would fetch [%s] %s", SOURCE, kind(minute), label)
            continue
        resp = rec.fetch(
            SOURCE,
            f"GET {snapshots.label(ev['id'], kind(minute))} ({label})",
            lambda ev=ev: rec.http.get(
                f"{BASE}/events/{ev['id']}/odds",
                [
                    ("apiKey", api_key),
                    ("regions", REGION),
                    ("markets", MARKET),
                    ("oddsFormat", "american"),
                    ("dateFormat", "iso"),
                ],
            ),
            count_rows=count_outcomes,
            cost=cost,
            precheck=lambda: budget.check(COST),
            on_response=budget.record,
            # 404: the event has left the feed (game over); not a failure
            keep=lambda r: r.status != 404,
        )
        if resp is not None and resp.ok:
            saved += 1

    header = "DRY RUN - nothing written" if args.dry_run else f"manifest: {manifest.path}"
    print(f"\n=== live in-game {header} ===")
    print(f"games listed in the last {LOOKBACK}: {len(events)}, snapshots due: {len(due)}")
    if not args.dry_run:
        print(f"snapshots saved this run: {saved}")
    print(f"spent today (live in-game): {budget.spent_today}/{budget.daily_cap}")
    print(f"failures: {rec.failures}")
    return 1 if rec.failures else 0


if __name__ == "__main__":
    sys.exit(main())
