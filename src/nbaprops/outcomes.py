"""Entry point: python -m nbaprops.outcomes [--start DATE] [--end DATE] [--dry-run]

Pulls actual results from ESPN's public site API (no key, plain requests):
one scoreboard per US date, then the game summary (box score and play-by-play)
for each final game. Raw responses go to <data-dir>/raw/espn/ like every other
source; nbaprops.tidy turns them into tables.

Resumable: scoreboards and summaries already in the manifest are not fetched
again. A dry run fetches the scoreboards only and writes nothing.
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import sys
from datetime import date, timedelta
from pathlib import Path

from nbaprops.backfill import FIRST_PROPS_DAY
from nbaprops.http import Http, UrllibHttp
from nbaprops.recorder import Recorder, utcnow
from nbaprops.snapshots import ET
from nbaprops.storage import Manifest, RawStore

log = logging.getLogger("nbaprops")

SOURCE = "espn"
BASE = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba"
PAUSE = 0.3  # seconds between requests; ESPN's API is unofficial, so go easy
MAX_FAILURES = 20

_SCOREBOARD = re.compile(r"GET scoreboard dates=(\d{8})")
_SUMMARY = re.compile(r"GET summary event=(\d+)")


def parse_args(argv: list[str] | None) -> argparse.Namespace:
    yesterday = utcnow().astimezone(ET).date() - timedelta(days=1)
    p = argparse.ArgumentParser(prog="python -m nbaprops.outcomes", description=__doc__)
    p.add_argument("--start", type=date.fromisoformat, default=FIRST_PROPS_DAY)
    p.add_argument("--end", type=date.fromisoformat, default=yesterday)
    p.add_argument("--dry-run", action="store_true", help="scoreboards only; write nothing")
    p.add_argument("--data-dir", default="data", type=Path)
    return p.parse_args(argv)


def captured(manifest: Manifest) -> tuple[dict[str, str], set[str]]:
    """Scoreboard paths by YYYYMMDD, and summary event ids, already saved with a 200."""
    days, summaries = {}, set()
    for row in manifest.rows():
        if row["source"] != SOURCE or row["status"] != "200":
            continue
        if m := _SCOREBOARD.match(row["request"]):
            days[m.group(1)] = row["path"]
        elif m := _SUMMARY.match(row["request"]):
            summaries.add(m.group(1))
    return days, summaries


def final_events(scoreboard: dict) -> list[dict]:
    return [
        e for e in scoreboard.get("events", []) if e["status"]["type"]["name"] == "STATUS_FINAL"
    ]


def count_box_rows(summary: dict) -> int:
    return sum(
        len(g.get("athletes", []))
        for team in summary.get("boxscore", {}).get("players", [])
        for g in team.get("statistics", [])
    )


def main(argv: list[str] | None = None, http: Http | None = None, clock=utcnow) -> int:
    args = parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    manifest = Manifest(args.data_dir)
    rec = Recorder(
        http or UrllibHttp(), RawStore(args.data_dir), manifest, dry_run=args.dry_run, clock=clock
    )
    days_done, summaries_done = captured(manifest)

    days = finals = fetched = 0
    day = args.end
    while day >= args.start and rec.failures < MAX_FAILURES:
        key = day.strftime("%Y%m%d")
        if key in days_done:
            board = json.loads(Path(days_done[key]).read_bytes())
        else:
            resp = rec.fetch(
                SOURCE,
                f"GET scoreboard dates={key}",
                lambda key=key: rec.http.get(
                    f"{BASE}/scoreboard", [("dates", key), ("limit", "50")]
                ),
                count_rows=lambda body: len(body.get("events", [])),
            )
            rec.sleep(PAUSE)
            board = resp.json() if resp is not None and resp.ok else {}
        days += 1
        for ev in final_events(board):
            finals += 1
            if args.dry_run or ev["id"] in summaries_done:
                continue
            resp = rec.fetch(
                SOURCE,
                f"GET summary event={ev['id']} ({ev.get('shortName', '')} {ev.get('date', '')})",
                lambda ev=ev: rec.http.get(f"{BASE}/summary", [("event", ev["id"])]),
                count_rows=count_box_rows,
            )
            rec.sleep(PAUSE)
            if resp is not None and resp.ok:
                summaries_done.add(ev["id"])
                fetched += 1
        day -= timedelta(days=1)

    header = "DRY RUN - nothing written" if args.dry_run else f"manifest: {manifest.path}"
    print(f"\n=== outcomes {header} ===")
    print(f"days: {days} ({args.end} back to {day + timedelta(days=1)})")
    print(f"final games: {finals}, summaries fetched this run: {fetched}")
    print(f"failures: {rec.failures}")
    return 1 if rec.failures else 0


if __name__ == "__main__":
    sys.exit(main())
