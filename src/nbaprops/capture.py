"""Entry point: python -m nbaprops.capture [--dry-run]

Reads the Odds API key from the ODDS_API_KEY environment variable only.
Writes raw responses to <data-dir>/raw/<source>/<date>/<UTC timestamp>.json and
one row per request to <data-dir>/manifest.csv. A dry run makes only the free
listing calls, writes nothing, and prints what a real run would fetch and spend.
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path

from nbaprops import kalshi, odds_api, polymarket
from nbaprops.budget import CreditBudget
from nbaprops.http import Http, UrllibHttp
from nbaprops.recorder import Recorder, utcnow
from nbaprops.storage import Manifest, RawStore

log = logging.getLogger("nbaprops")

SOURCES = ("odds_api", "kalshi", "polymarket")


def parse_args(argv: list[str] | None) -> argparse.Namespace:
    p = argparse.ArgumentParser(prog="python -m nbaprops.capture", description=__doc__)
    p.add_argument("--dry-run", action="store_true", help="free listing calls only; write nothing")
    p.add_argument("--data-dir", default="data", type=Path)
    p.add_argument(
        "--hours-ahead", default=24, type=int, help="capture games tipping off within N hours"
    )
    p.add_argument(
        "--sources",
        default=",".join(SOURCES),
        help="comma-separated subset of " + ",".join(SOURCES),
    )
    return p.parse_args(argv)


def main(argv: list[str] | None = None, http: Http | None = None, clock=utcnow) -> int:
    args = parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    sources = [s.strip() for s in args.sources.split(",") if s.strip()]
    unknown = set(sources) - set(SOURCES)
    if unknown:
        log.error("unknown sources: %s", ", ".join(sorted(unknown)))
        return 2

    api_key = os.environ.get("ODDS_API_KEY", "").strip()
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

    plan: list[str] = []
    for source in sources:
        try:
            if source == "odds_api":
                if not api_key:
                    log.error("[odds_api] ODDS_API_KEY is not set; skipping")
                    rec.failures += 1
                    plan.append("odds_api: skipped, ODDS_API_KEY not set")
                    continue
                budget = CreditBudget(spent_today=manifest.credits_spent_on("odds_api", now.date()))
                plan += odds_api.run(rec, api_key, budget, now, args.hours_ahead)
            elif source == "kalshi":
                plan += kalshi.run(rec)
            elif source == "polymarket":
                plan += polymarket.run(rec, now, args.hours_ahead)
        except Exception as e:  # one source failing must not stop the others
            rec.failures += 1
            log.exception("[%s] crashed: %s", source, rec.clean(str(e)))

    header = (
        "DRY RUN - nothing written" if args.dry_run else f"run complete, manifest: {manifest.path}"
    )
    print(f"\n=== {header} ===")
    for line in plan:
        print(line)
    print(f"failures: {rec.failures}")
    return 1 if rec.failures else 0


if __name__ == "__main__":
    sys.exit(main())
