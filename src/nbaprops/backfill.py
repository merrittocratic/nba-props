"""Entry point: python -m nbaprops.backfill [--start DATE] [--end DATE] [--dry-run]

Pulls the same three snapshots per game as the live capture (open, morning, close;
see snapshots.py) from the Odds API historical endpoints, newest day first.

Costs: each day's event listing is 1 credit; open is found by a binary search on a
15-minute grid using a cheap probe (player_points, region us: 10 credits when lines
exist, 0 when not); each full snapshot costs up to 10 x markets x regions = 120.
Spend is tracked under its own manifest source, so it never counts against the live
capture's daily cap, and it stops before the plan drops below --floor.

Resumable: snapshots already in the manifest are skipped. A dry run makes only the
listing calls (1 credit per day), writes nothing, and prints the planned spend.
Reads the key from ODDS_API_KEY only.
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

from nbaprops import snapshots
from nbaprops.budget import CreditBudget, header_int
from nbaprops.http import Http, Response, UrllibHttp
from nbaprops.odds_api import MARKETS, REGIONS, count_outcomes, iso_z
from nbaprops.recorder import Recorder, utcnow
from nbaprops.storage import Manifest, RawStore

log = logging.getLogger("nbaprops")

SOURCE = "odds_api_hist"
BASE = "https://api.the-odds-api.com/v4/historical/sports/basketball_nba"
FIRST_PROPS_DAY = date(2023, 5, 3)  # earliest historical player props
LISTING_HOUR = 15  # 15:00 UTC, before any NBA tip-off that day
GRID = timedelta(minutes=15)
FULL_COST = 10 * len(MARKETS) * len(REGIONS)
PROBE_COST = 10
MAX_FAILURES = 20


def parse_args(argv: list[str] | None) -> argparse.Namespace:
    yesterday = utcnow().date() - timedelta(days=1)
    p = argparse.ArgumentParser(prog="python -m nbaprops.backfill", description=__doc__)
    p.add_argument("--start", type=date.fromisoformat, default=FIRST_PROPS_DAY)
    p.add_argument("--end", type=date.fromisoformat, default=yesterday)
    p.add_argument("--dry-run", action="store_true", help="listing calls only; write nothing")
    p.add_argument("--data-dir", default="data", type=Path)
    p.add_argument("--daily-cap", default=500_000, type=int, help="backfill credits per UTC day")
    p.add_argument("--floor", default=50_000, type=int, help="stop above this many plan credits")
    return p.parse_args(argv)


def snapshot_data(resp: Response | None) -> dict:
    if resp is None or not resp.ok:
        return {}
    return resp.json().get("data") or {}


class Backfill:
    def __init__(self, rec: Recorder, api_key: str, budget: CreditBudget):
        self.rec = rec
        self.api_key = api_key
        self.budget = budget
        self.taken = snapshots.done(rec.manifest, SOURCE)
        self.stopped: str | None = None

    def get(
        self,
        request: str,
        path: str,
        params: list[tuple[str, str]],
        worst: int,
        count_rows=lambda body: count_outcomes(body.get("data") or {}),
        **kw,
    ):
        return self.rec.fetch(
            SOURCE,
            request,
            lambda: self.rec.http.get(
                f"{BASE}{path}", [("apiKey", self.api_key), ("dateFormat", "iso"), *params]
            ),
            count_rows=count_rows,
            cost=lambda r: header_int(r, "x-requests-last") or 0,
            precheck=lambda: self.budget.check(worst),
            on_response=self.budget.record,
            **kw,
        )

    def list_day(self, day: date) -> list[dict]:
        start = datetime(day.year, day.month, day.day, LISTING_HOUR, tzinfo=UTC)
        resp = self.get(
            f"GET historical /events date={iso_z(start)}",
            "/events",
            [
                ("date", iso_z(start)),
                ("commenceTimeFrom", iso_z(start)),
                ("commenceTimeTo", iso_z(start + timedelta(days=1))),
            ],
            1,
            count_rows=lambda body: len(body.get("data") or []),
        )
        return (resp.json().get("data") or []) if resp is not None and resp.ok else []

    def posted(self, ev: dict, at: datetime) -> bool:
        """Cheap check: any player_points lines at a US book in the snapshot at `at`."""
        resp = self.get(
            f"GET historical /events/{ev['id']}/odds probe date={iso_z(at)}",
            f"/events/{ev['id']}/odds",
            [("date", iso_z(at)), ("regions", "us"), ("markets", "player_points")],
            PROBE_COST,
            keep=lambda r: False,
        )
        return bool(snapshot_data(resp).get("bookmakers"))

    def find_open(self, ev: dict, tip: datetime) -> datetime | None:
        """First 15-minute grid point in the open window with lines posted, if any."""
        start, end = snapshots.window("open", tip)
        grid = []
        t = start
        while t < end:
            grid.append(t)
            t += GRID
        if not grid or not self.posted(ev, grid[-1]):
            return None
        lo, hi = -1, len(grid) - 1  # grid[lo] unposted (assumed), grid[hi] posted
        while hi - lo > 1:
            mid = (lo + hi) // 2
            if self.posted(ev, grid[mid]):
                hi = mid
            else:
                lo = mid
        return grid[hi]

    def fetch_snapshot(self, ev: dict, kind: str, at: datetime) -> None:
        label = f"{ev['away_team']} @ {ev['home_team']} {ev['commence_time']}"
        resp = self.get(
            f"GET historical {snapshots.label(ev['id'], kind)} date={iso_z(at)} ({label})",
            f"/events/{ev['id']}/odds",
            [
                ("date", iso_z(at)),
                ("regions", ",".join(REGIONS)),
                ("markets", ",".join(MARKETS)),
                ("oddsFormat", "american"),
            ],
            FULL_COST,
        )
        if resp is not None and resp.ok:
            self.taken.add((ev["id"], kind))

    def run_event(self, ev: dict) -> None:
        tip = snapshots.parse_tip(ev["commence_time"])
        for kind in snapshots.KINDS:
            if (ev["id"], kind) in self.taken or not snapshots.window(kind, tip):
                continue
            if reason := self.budget.check(FULL_COST + PROBE_COST * 8):
                self.stopped = reason
                return
            if kind == "open":
                at = self.find_open(ev, tip)
                if at is None:
                    log.info("[%s] %s: no lines before morning/close", SOURCE, ev["id"])
                    continue
            elif kind == "morning":
                at = snapshots.morning_at(tip)
            else:
                at = snapshots.close_at(tip)
            self.fetch_snapshot(ev, kind, at)


def main(argv: list[str] | None = None, http: Http | None = None, clock=utcnow) -> int:
    args = parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    api_key = os.environ.get("ODDS_API_KEY", "").strip()
    if not api_key:
        log.error("ODDS_API_KEY is not set")
        return 2
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
        spent_today=manifest.credits_spent_on(SOURCE, clock().date()),
        daily_cap=args.daily_cap,
        monthly_floor=args.floor,
    )
    bf = Backfill(rec, api_key, budget)

    days = events = todo = 0
    day, oldest = args.end, None
    while day >= args.start and not bf.stopped and rec.failures < MAX_FAILURES:
        if reason := budget.check(1):
            bf.stopped = reason
            break
        listed = bf.list_day(day)
        days, oldest = days + 1, day
        events += len(listed)
        for ev in listed:
            missing = [
                k
                for k in snapshots.KINDS
                if (ev["id"], k) not in bf.taken
                and snapshots.window(k, snapshots.parse_tip(ev["commence_time"]))
            ]
            todo += len(missing)
            if not args.dry_run and missing:
                bf.run_event(ev)
                if bf.stopped or rec.failures >= MAX_FAILURES:
                    break
        day -= timedelta(days=1)

    header = "DRY RUN - nothing written" if args.dry_run else f"manifest: {manifest.path}"
    print(f"\n=== backfill {header} ===")
    print(f"days listed: {days} ({args.end} back to {oldest})")
    print(f"games: {events}, snapshots not yet taken: {todo}")
    if args.dry_run:
        print(f"planned spend: up to {todo * FULL_COST + events * 8 * PROBE_COST} credits")
    print(f"spent today (backfill): {budget.spent_today}, remaining on plan: {budget.remaining}")
    if bf.stopped:
        print(f"stopped: {bf.stopped}")
    print(f"failures: {rec.failures}")
    return 1 if rec.failures else 0


if __name__ == "__main__":
    sys.exit(main())
