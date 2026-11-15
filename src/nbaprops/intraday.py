"""Entry point: python -m nbaprops.intraday [--start DATE] [--end DATE] [--workers N] [--dry-run]

Historical pregame player_points lines from US sportsbooks every 2 hours before tip-off,
the same slots the live capture takes (snapshots.intraday_kind): pts_t28 .. pts_t02,
labeled by the hours left. Each slot is fetched at its start (tip-off minus HH+2 hours),
which is when the 15-minute live capture would first take it. They're for following
how line and price move together through the day (EDA catalog A5).

Each snapshot with lines costs 10 credits; one with no lines (props not posted yet, or
the event not yet listed) costs nothing and isn't saved. About 10 per game have lines,
so ~100 credits a game, ~400K for the ~4,000 games since May 2023.

--near-tip takes the last 2 hours instead, which the 2-hourly slots leave to the close
snapshot: every 15 minutes from 2 hours to 15 minutes before tip-off (kinds pts_m120 ..
pts_m015, the minutes left), when injury and lineup news lands. Those go under their
own source, odds_api_neartip_hist. 8 slots, ~80 credits a game.

--near-tip --other-markets takes the same 8 slots for the five non-points markets
(rebounds, assists, threes, points+rebounds, points+rebounds+assists) in one request:
kinds oth_m120 .. oth_m015, source odds_api_neartip_oth_hist, up to 50 credits a
snapshot (10 per market with lines), so up to ~400 a game.

Several games run at once (--workers). Spend is tracked under its own manifest source
with its own cap and the same floor as the other backfills. Resumable: snapshots
already saved are skipped (empty ones are re-checked, which is free). A dry run lists
days only (1 credit each) and prints the planned spend.
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta
from pathlib import Path

from nbaprops import snapshots
from nbaprops.backfill import FIRST_PROPS_DAY, Backfill, snapshot_data
from nbaprops.budget import CreditBudget
from nbaprops.http import Http, UrllibHttp
from nbaprops.odds_api import INTRADAY_MARKETS, INTRADAY_REGIONS, MARKETS, iso_z
from nbaprops.recorder import Recorder, utcnow
from nbaprops.storage import Manifest, RawStore

log = logging.getLogger("nbaprops")

SOURCE = "odds_api_intraday_hist"
NEAR_SOURCE = "odds_api_neartip_hist"
NEAR_MINUTES = tuple(range(120, 0, -15))  # 120, 105, ..., 15
NEAR_OTHER_SOURCE = "odds_api_neartip_oth_hist"
OTHER_MARKETS = tuple(m for m in MARKETS if m not in INTRADAY_MARKETS)
COST = 10 * len(INTRADAY_MARKETS) * len(INTRADAY_REGIONS)
STEP = snapshots.INTRADAY_STEP
MAX_FAILURES = 50


# Fetch 5 minutes into each slot: the slot pts_tHH starts when fewer than HH+2 hours are
# left, and the historical feed has 5-minute resolution.
OFFSET = timedelta(minutes=5)


def slots(tip: datetime) -> list[tuple[str, datetime]]:
    """(kind, fetch time) for every 2-hour slot, earliest first."""
    out = []
    at = tip - snapshots.OPEN_LOOKBACK + OFFSET
    while at < tip - STEP:
        out.append((snapshots.intraday_kind(tip, at), at))
        at += STEP
    return out


def near_tip_slots(tip: datetime, prefix: str = "pts") -> list[tuple[str, datetime]]:
    """(kind, fetch time) every 15 minutes in the last 2 hours, earliest first."""
    return [(f"{prefix}_m{m:03d}", tip - timedelta(minutes=m)) for m in NEAR_MINUTES]


def near_tip_other_slots(tip: datetime) -> list[tuple[str, datetime]]:
    return near_tip_slots(tip, "oth")


class Intraday(Backfill):
    source = SOURCE

    def __init__(
        self,
        rec: Recorder,
        api_key: str,
        budget: CreditBudget,
        near_tip=False,
        other_markets=False,
    ):
        markets, source, self.slots = INTRADAY_MARKETS, SOURCE, slots
        if near_tip and other_markets:
            markets, source, self.slots = OTHER_MARKETS, NEAR_OTHER_SOURCE, near_tip_other_slots
        elif near_tip:
            source, self.slots = NEAR_SOURCE, near_tip_slots
        super().__init__(rec, api_key, budget, markets, INTRADAY_REGIONS, source)
        self.cost = self.full_cost
        self.taken_lock = threading.Lock()

    def has_lines(self, resp) -> bool:
        return bool(snapshot_data(resp).get("bookmakers"))

    def run_event(self, ev: dict) -> int:
        """Snapshots for one game; returns how many were saved. Never raises."""
        try:
            return self._run_event(ev)
        except Exception as e:  # one bad game must not stop the other workers
            self.rec.failures += 1
            log.exception("[%s] %s crashed: %s", self.source, ev.get("id"), self.rec.clean(str(e)))
            return 0

    def _run_event(self, ev: dict) -> int:
        tip = snapshots.parse_tip(ev["commence_time"])
        label = f"{ev['away_team']} @ {ev['home_team']} {ev['commence_time']}"
        saved = 0
        for k, at in self.slots(tip):
            if self.stopped or self.rec.failures >= MAX_FAILURES:
                return saved
            with self.taken_lock:
                if (ev["id"], k) in self.taken:
                    continue
            if reason := self.budget.check(self.cost):
                self.stopped = reason
                return saved
            resp = self.get(
                f"GET historical {snapshots.label(ev['id'], k)} date={iso_z(at)} ({label})",
                f"/events/{ev['id']}/odds",
                [
                    ("date", iso_z(at)),
                    ("regions", ",".join(INTRADAY_REGIONS)),
                    ("markets", ",".join(self.markets)),
                    ("oddsFormat", "american"),
                ],
                self.cost,
                # 404: not listed yet that far out; free, like an empty snapshot.
                keep=lambda r: r.status != 404 and (not r.ok or self.has_lines(r)),
            )
            if resp is not None and resp.ok and self.has_lines(resp):
                with self.taken_lock:
                    self.taken.add((ev["id"], k))
                saved += 1
        return saved


def parse_args(argv: list[str] | None) -> argparse.Namespace:
    yesterday = utcnow().date() - timedelta(days=1)
    p = argparse.ArgumentParser(prog="python -m nbaprops.intraday", description=__doc__)
    p.add_argument("--start", type=date.fromisoformat, default=FIRST_PROPS_DAY)
    p.add_argument("--end", type=date.fromisoformat, default=yesterday)
    p.add_argument("--workers", default=6, type=int, help="games fetched at once")
    p.add_argument("--dry-run", action="store_true", help="listing calls only; write nothing")
    p.add_argument(
        "--near-tip", action="store_true", help="every 15 min in the last 2 hours instead"
    )
    p.add_argument(
        "--other-markets",
        action="store_true",
        help=f"with --near-tip: the non-points markets instead, source {NEAR_OTHER_SOURCE}",
    )
    p.add_argument("--data-dir", default="data", type=Path)
    p.add_argument("--daily-cap", default=1_000_000, type=int, help="credits per UTC day")
    p.add_argument("--floor", default=50_000, type=int, help="stop above this many plan credits")
    args = p.parse_args(argv)
    if args.other_markets and not args.near_tip:
        p.error("--other-markets needs --near-tip")
    return args


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
    source = SOURCE
    if args.near_tip:
        source = NEAR_OTHER_SOURCE if args.other_markets else NEAR_SOURCE
    budget = CreditBudget(
        spent_today=manifest.credits_spent_on(source, clock().date()),
        daily_cap=args.daily_cap,
        monthly_floor=args.floor,
    )
    bf = Intraday(rec, api_key, budget, near_tip=args.near_tip, other_markets=args.other_markets)

    days = games = 0
    oldest = None
    futures = []
    with ThreadPoolExecutor(max_workers=max(1, args.workers)) as pool:
        day = args.end
        while day >= args.start and not bf.stopped and rec.failures < MAX_FAILURES:
            if reason := budget.check(1):
                bf.stopped = reason
                break
            listed = bf.list_day(day)
            days, oldest, games = days + 1, day, games + len(listed)
            if not args.dry_run:
                futures += [pool.submit(bf.run_event, ev) for ev in listed]
            day -= timedelta(days=1)
        saved = sum(f.result() for f in futures)

    header = "DRY RUN - nothing written" if args.dry_run else f"manifest: {manifest.path}"
    print(f"\n=== {'near-tip' if args.near_tip else 'intraday'} backfill {header} ===")
    print(f"days listed: {days} ({args.end} back to {oldest})")
    print(f"games: {games}")
    if args.dry_run:
        n_slots = len(bf.slots(utcnow()))
        typical = n_slots if args.near_tip else 10
        print(
            f"planned spend: about {games * typical * bf.cost:,} credits "
            f"(at most {games * n_slots * bf.cost:,})"
        )
    else:
        print(f"snapshots saved this run: {saved}")
    print(f"spent today ({source}): {budget.spent_today}, remaining on plan: {budget.remaining}")
    if bf.stopped:
        print(f"stopped: {bf.stopped}")
    print(f"failures: {rec.failures}")
    return 1 if rec.failures else 0


if __name__ == "__main__":
    sys.exit(main())
