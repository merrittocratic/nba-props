"""Entry point: python -m nbaprops.inplay [--start DATE] [--end DATE] [--workers N] [--dry-run]

Historical in-game player_points lines from US sportsbooks: a snapshot every 5 minutes
from tip-off until the books stop posting (at most 3.5 hours), newest day first.
Each snapshot costs 10 credits; one with no lines costs nothing and isn't saved.
Snapshots are labeled [inplay_MMM] by minutes after tip-off, so nbaprops.tidy
picks them up like any other kind.

Several games run at once (--workers). Spend is tracked under its own manifest
source with its own cap and the same floor as the pregame backfill. Resumable:
snapshots already saved are skipped (empty ones are re-checked, which is free).
A dry run lists days only (1 credit each) and prints the planned spend.
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta
from pathlib import Path

from nbaprops import snapshots
from nbaprops.backfill import FIRST_PROPS_DAY, Backfill, snapshot_data
from nbaprops.budget import CreditBudget
from nbaprops.http import Http, UrllibHttp
from nbaprops.odds_api import iso_z
from nbaprops.recorder import Recorder, utcnow
from nbaprops.storage import Manifest, RawStore

log = logging.getLogger("nbaprops")

SOURCE = "odds_api_inplay"
MARKET = "player_points"
REGION = "us"
COST = 10
STEP_MINUTES = 5
MAX_MINUTES = 210
# Lines can blink out mid-game (timeouts, reviews); only stop late, after two empties.
QUIET_AFTER_MINUTES = 90
QUIET_STOP = 2
MAX_FAILURES = 50


def kind(minute: int) -> str:
    return f"inplay_{minute:03d}"


class InPlay(Backfill):
    source = SOURCE

    def __init__(self, rec: Recorder, api_key: str, budget: CreditBudget):
        super().__init__(rec, api_key, budget)
        self.taken_lock = threading.Lock()

    def has_lines(self, resp) -> bool:
        return bool(snapshot_data(resp).get("bookmakers"))

    def run_event(self, ev: dict) -> int:
        """Snapshots for one game; returns how many were saved. Never raises."""
        try:
            return self._run_event(ev)
        except Exception as e:  # one bad game must not stop the other workers
            self.rec.failures += 1
            log.exception("[%s] %s crashed: %s", SOURCE, ev.get("id"), self.rec.clean(str(e)))
            return 0

    def _run_event(self, ev: dict) -> int:
        tip = snapshots.parse_tip(ev["commence_time"])
        label = f"{ev['away_team']} @ {ev['home_team']} {ev['commence_time']}"
        saved = quiet = 0
        for minute in range(0, MAX_MINUTES + 1, STEP_MINUTES):
            if self.stopped or self.rec.failures >= MAX_FAILURES:
                return saved
            k = kind(minute)
            with self.taken_lock:
                done = (ev["id"], k) in self.taken
            if done:
                quiet = 0
                continue
            if reason := self.budget.check(COST):
                self.stopped = reason
                return saved
            at = tip + timedelta(minutes=minute)
            resp = self.get(
                f"GET historical {snapshots.label(ev['id'], k)} date={iso_z(at)} ({label})",
                f"/events/{ev['id']}/odds",
                [
                    ("date", iso_z(at)),
                    ("regions", REGION),
                    ("markets", MARKET),
                    ("oddsFormat", "american"),
                ],
                COST,
                # 404: the event has left the feed (game over); free, like an empty snapshot.
                keep=lambda r: r.status != 404 and (not r.ok or self.has_lines(r)),
            )
            if resp is not None and resp.ok and self.has_lines(resp):
                with self.taken_lock:
                    self.taken.add((ev["id"], k))
                saved += 1
                quiet = 0
            else:
                quiet += 1
            if minute >= QUIET_AFTER_MINUTES and quiet >= QUIET_STOP:
                break
        return saved


def parse_args(argv: list[str] | None) -> argparse.Namespace:
    yesterday = utcnow().date() - timedelta(days=1)
    p = argparse.ArgumentParser(prog="python -m nbaprops.inplay", description=__doc__)
    p.add_argument("--start", type=date.fromisoformat, default=FIRST_PROPS_DAY)
    p.add_argument("--end", type=date.fromisoformat, default=yesterday)
    p.add_argument("--workers", default=6, type=int, help="games fetched at once")
    p.add_argument("--dry-run", action="store_true", help="listing calls only; write nothing")
    p.add_argument("--data-dir", default="data", type=Path)
    p.add_argument("--daily-cap", default=2_000_000, type=int, help="credits per UTC day")
    p.add_argument("--floor", default=50_000, type=int, help="stop above this many plan credits")
    return p.parse_args(argv)


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
    ip = InPlay(rec, api_key, budget)

    days = games = 0
    oldest = None
    futures = []
    with ThreadPoolExecutor(max_workers=max(1, args.workers)) as pool:
        day = args.end
        while day >= args.start and not ip.stopped and rec.failures < MAX_FAILURES:
            if reason := budget.check(1):
                ip.stopped = reason
                break
            listed = ip.list_day(day)
            days, oldest, games = days + 1, day, games + len(listed)
            if not args.dry_run:
                futures += [pool.submit(ip.run_event, ev) for ev in listed]
            day -= timedelta(days=1)
        saved = sum(f.result() for f in futures)

    header = "DRY RUN - nothing written" if args.dry_run else f"manifest: {manifest.path}"
    print(f"\n=== in-play backfill {header} ===")
    print(f"days listed: {days} ({args.end} back to {oldest})")
    print(f"games: {games}")
    if args.dry_run:
        per_game = (MAX_MINUTES // STEP_MINUTES + 1) * COST
        print(f"planned spend: about {games * 30 * COST:,} credits (at most {games * per_game:,})")
    else:
        print(f"snapshots saved this run: {saved}")
    print(f"spent today (in-play): {budget.spent_today}, remaining on plan: {budget.remaining}")
    if ip.stopped:
        print(f"stopped: {ip.stopped}")
    print(f"failures: {rec.failures}")
    return 1 if rec.failures else 0


if __name__ == "__main__":
    sys.exit(main())
