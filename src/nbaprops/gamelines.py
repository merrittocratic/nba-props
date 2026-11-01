"""Entry point: python -m nbaprops.gamelines [--start DATE] [--end DATE] [--dry-run]

Historical game lines (moneyline, spread, total) from US sportsbooks, for pace,
game-script and blowout features. One historical /odds call returns every game on
the board at that moment, so each day takes a few slate-wide snapshots, matching the
prop snapshots in snapshots.py:

- morning: 11:00 ET on game day (when it falls at least an hour before a close)
- close: one hour before each distinct tip-off time that day

Costs: each day's event listing is 1 credit; each snapshot is 10 x 3 markets x 1
region = 30 credits. Spend goes under its own manifest source, with its own cap and
the same floor as the other backfills. Resumable: snapshot times already saved are
skipped. A dry run lists days only (1 credit each) and prints the planned spend.
"""

from __future__ import annotations

import argparse
import logging
import os
import re
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

from nbaprops import snapshots
from nbaprops.backfill import FIRST_PROPS_DAY, MAX_FAILURES, Backfill
from nbaprops.budget import CreditBudget
from nbaprops.http import Http, UrllibHttp
from nbaprops.odds_api import iso_z
from nbaprops.recorder import Recorder, utcnow
from nbaprops.storage import Manifest, RawStore

log = logging.getLogger("nbaprops")

SOURCE = "odds_api_gamelines"
MARKETS = ("h2h", "spreads", "totals")
REGION = "us"
COST = 10 * len(MARKETS)

_DONE = re.compile(r"GET historical /odds \[(\w+)\] date=(\S+)")


def snapshot_times(events: list[dict]) -> list[tuple[str, datetime]]:
    """(kind, time) snapshots for one day's events, earliest first, without repeats."""
    times: dict[datetime, str] = {}
    for ev in events:
        tip = snapshots.parse_tip(ev["commence_time"])
        if morning := snapshots.morning_at(tip):
            times.setdefault(morning, "morning")
        times[snapshots.close_at(tip)] = "close"
    return sorted(((kind, at) for at, kind in times.items()), key=lambda x: x[1])


def count_games(body: dict) -> int:
    return len(body.get("data") or [])


class GameLines(Backfill):
    source = SOURCE

    def __init__(self, rec: Recorder, api_key: str, budget: CreditBudget):
        super().__init__(rec, api_key, budget)
        self.saved_at = {
            m.group(2)
            for row in rec.manifest.rows()
            if row["source"] == SOURCE and row["status"] == "200"
            if (m := _DONE.match(row["request"]))
        }

    def fetch(self, kind: str, at: datetime) -> bool:
        """Take one slate snapshot; returns False when the run must stop."""
        if iso_z(at) in self.saved_at:
            return True
        if reason := self.budget.check(COST):
            self.stopped = reason
            return False
        resp = self.get(
            f"GET historical /odds [{kind}] date={iso_z(at)}",
            "/odds",
            [
                ("date", iso_z(at)),
                ("regions", REGION),
                ("markets", ",".join(MARKETS)),
                ("oddsFormat", "american"),
            ],
            COST,
            count_rows=count_games,
        )
        if resp is not None and resp.ok:
            self.saved_at.add(iso_z(at))
        return self.rec.failures < MAX_FAILURES


def parse_args(argv: list[str] | None) -> argparse.Namespace:
    yesterday = utcnow().date() - timedelta(days=1)
    p = argparse.ArgumentParser(prog="python -m nbaprops.gamelines", description=__doc__)
    p.add_argument("--start", type=date.fromisoformat, default=FIRST_PROPS_DAY)
    p.add_argument("--end", type=date.fromisoformat, default=yesterday)
    p.add_argument("--dry-run", action="store_true", help="listing calls only; write nothing")
    p.add_argument("--data-dir", default="data", type=Path)
    p.add_argument("--daily-cap", default=200_000, type=int, help="credits per UTC day")
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
    gl = GameLines(rec, api_key, budget)

    days = games = planned = 0
    day, oldest = args.end, None
    while day >= args.start and not gl.stopped and rec.failures < MAX_FAILURES:
        if reason := budget.check(1):
            gl.stopped = reason
            break
        listed = gl.list_day(day)
        days, oldest, games = days + 1, day, games + len(listed)
        for kind, at in snapshot_times(listed):
            if iso_z(at) in gl.saved_at:
                continue
            planned += 1
            if not args.dry_run and not gl.fetch(kind, at):
                break
        day -= timedelta(days=1)

    header = "DRY RUN - nothing written" if args.dry_run else f"manifest: {manifest.path}"
    print(f"\n=== game-lines backfill {header} ===")
    print(f"days listed: {days} ({args.end} back to {oldest})")
    print(f"games: {games}, snapshots {'planned' if args.dry_run else 'attempted'}: {planned}")
    if args.dry_run:
        print(f"planned spend: up to {planned * COST:,} credits")
    print(f"spent today (game lines): {budget.spent_today}, remaining on plan: {budget.remaining}")
    if gl.stopped:
        print(f"stopped: {gl.stopped}")
    print(f"failures: {rec.failures}")
    return 1 if rec.failures else 0


if __name__ == "__main__":
    sys.exit(main())
