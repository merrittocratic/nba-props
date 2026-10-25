"""One-off coverage probe: The Odds API historical endpoints for NBA player props.

Not a data pull. Spends at most CREDIT_CAP credits, saves raw JSON to
data/raw/probe/, and prints a coverage summary. The API key is never printed,
logged, or written to disk.
"""

import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import defaultdict
from datetime import UTC, datetime, timedelta
from pathlib import Path

BASE = "https://api.the-odds-api.com/v4/historical/sports/basketball_nba"
RAW_DIR = Path(__file__).resolve().parent.parent / "data" / "raw" / "probe"
CREDIT_CAP = 300
MARKETS = [
    "player_points",
    "player_rebounds",
    "player_assists",
    "player_threes",
    "player_points_rebounds_assists",
]
# us_dfs = Dabble, DraftKings Pick6, PrizePicks, Underdog (per bookmaker-apis docs)
EXTRA_REGIONS = ["us_dfs"]
GAMES = {
    "A_2023-24": "2023-11-15T12:00:00Z",
    "B_2024-25": "2025-01-15T12:00:00Z",
}

spent = 0
ledger = []  # (name, x-requests-last, x-requests-remaining)


class FatalAPIError(Exception):
    pass


def get_key():
    try:
        out = subprocess.run(
            ["op", "item", "get", "Odds API Key", "--fields", "credential", "--reveal"],
            capture_output=True,
            text=True,
            timeout=60,
        )
        if out.returncode == 0 and out.stdout.strip():
            return out.stdout.strip()
        print("1Password lookup failed; falling back to ODDS_API_KEY env var")
    except (OSError, subprocess.TimeoutExpired):
        print("1Password CLI unavailable; falling back to ODDS_API_KEY env var")
    key = os.environ.get("ODDS_API_KEY", "").strip()
    if not key:
        sys.exit("No API key found in 1Password or ODDS_API_KEY")
    return key


def iso(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_iso(s):
    return datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)


def call(key, name, path, params, worst_case):
    """GET with budget pre-check, header logging, one retry, raw save."""
    global spent
    if spent + worst_case > CREDIT_CAP:
        raise FatalAPIError(
            f"[{name}] skipped: spent {spent} + worst case {worst_case} would pass cap {CREDIT_CAP}"
        )
    query = urllib.parse.urlencode({**params, "apiKey": key})
    url = f"{BASE}{path}?{query}"
    safe_params = urllib.parse.urlencode(params)  # key-free, for display only
    for attempt in (1, 2):
        try:
            with urllib.request.urlopen(url, timeout=60) as resp:
                body = resp.read().decode()
                headers = resp.headers
                status = resp.status
        except urllib.error.HTTPError as e:
            body = e.read().decode(errors="replace")
            headers = e.headers
            status = e.code
        except urllib.error.URLError as e:
            msg = str(e.reason).replace(key, "***")
            print(f"[{name}] network error (attempt {attempt}): {msg}")
            if attempt == 2:
                raise FatalAPIError(f"[{name}] network error after retry") from None
            time.sleep(2)
            continue

        last = headers.get("x-requests-last")
        remaining = headers.get("x-requests-remaining")
        cost = int(float(last)) if last not in (None, "") else 0
        spent += cost
        ledger.append((name if attempt == 1 else f"{name} (retry)", last, remaining))
        print(f"[{name}] HTTP {status}  {safe_params}")
        print(f"    x-requests-last={last}  x-requests-remaining={remaining}  spent_total={spent}")

        if status == 200:
            data = json.loads(body)
            (RAW_DIR / f"{name}.json").write_text(json.dumps(data, indent=2))
            return data
        if status in (401, 403, 422):
            raise FatalAPIError(f"[{name}] HTTP {status}: {body.replace(key, '***')}")
        print(f"    error body: {body.replace(key, '***')[:500]}")
        if attempt == 2:
            raise FatalAPIError(f"[{name}] HTTP {status} after retry")
        if spent + worst_case > CREDIT_CAP:
            raise FatalAPIError(f"[{name}] retry skipped: would pass cap {CREDIT_CAP}")
        time.sleep(2)


def pick_game(key, label, date_str):
    snap = parse_iso(date_str)
    # US evening tip-offs on that calendar date land roughly 15:00Z same day to 08:00Z next day
    data = call(
        key,
        f"{label}_events",
        "/events",
        {
            "date": date_str,
            "commenceTimeFrom": iso(snap.replace(hour=15)),
            "commenceTimeTo": iso(snap.replace(hour=8) + timedelta(days=1)),
        },
        worst_case=1,
    )
    events = sorted(data.get("data", []), key=lambda e: e["commence_time"])
    print(
        f"    snapshot returned {data.get('timestamp')} (requested {date_str}); "
        f"{len(events)} events"
    )
    for e in events:
        print(f"      {e['commence_time']}  {e['away_team']} @ {e['home_team']}  id={e['id']}")
    if not events:
        raise FatalAPIError(f"[{label}] no events found")
    return events[0]


def summarize(label, region, requested, data):
    print(f"\n=== Game {label} | region={region} ===")
    print(f"Requested snapshot: {requested}   Returned snapshot: {data.get('timestamp')}")
    ev = data.get("data") or {}
    books = ev.get("bookmakers", [])
    if not books:
        print("No bookmakers returned.")
        return
    print(
        f"Event: {ev.get('away_team')} @ {ev.get('home_team')}  commence {ev.get('commence_time')}"
    )
    print("Bookmakers present: " + ", ".join(b["key"] for b in books))

    abbrev = {
        m: m.replace("player_", "").replace("points_rebounds_assists", "pra") for m in MARKETS
    }
    header = f"{'bookmaker':<18}" + "".join(f"{abbrev[m]:>10}" for m in MARKETS)
    print("\nDistinct players with a line:")
    print(header)
    ou_notes = []
    samples = []
    for b in books:
        counts = {}
        for m in b.get("markets", []):
            sides = defaultdict(set)
            for o in m.get("outcomes", []):
                sides[o.get("description")].add(o.get("name"))
            counts[m["key"]] = len(sides)
            both = sum(1 for s in sides.values() if {"Over", "Under"} <= s)
            ou_notes.append(
                f"{b['key']}/{abbrev.get(m['key'], m['key'])}: "
                f"{both}/{len(sides)} players have both Over and Under"
            )
        print(f"{b['key']:<18}" + "".join(f"{counts.get(m, 0):>10}" for m in MARKETS))

        mk = (
            next((m for m in b.get("markets", []) if m["key"] == "player_points"), None)
            or (b.get("markets") or [None])[0]
        )
        if mk and mk.get("outcomes"):
            player = mk["outcomes"][0].get("description")
            outs = [o for o in mk["outcomes"] if o.get("description") == player]
            parts = [f"{o.get('name')} {o.get('point')} @ {o.get('price')}" for o in outs]
            samples.append(
                f"{b['key']}: {mk['key']} {player}: "
                + " | ".join(parts)
                + f"  (last_update {mk.get('last_update')})"
            )
    print("\nOver/Under presence:")
    for n in ou_notes:
        print("  " + n)
    print("\nSample player per book:")
    for s in samples:
        print("  " + s)


def main():
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    key = get_key()
    results = []
    try:
        games = {label: pick_game(key, label, d) for label, d in GAMES.items()}
        for label, ev in games.items():
            snap = iso(parse_iso(ev["commence_time"]) - timedelta(hours=1))
            for region in ["us"] + EXTRA_REGIONS:
                data = call(
                    key,
                    f"{label}_odds_{region}",
                    f"/events/{ev['id']}/odds",
                    {
                        "date": snap,
                        "regions": region,
                        "markets": ",".join(MARKETS),
                        "oddsFormat": "american",
                        "dateFormat": "iso",
                    },
                    worst_case=10 * len(MARKETS),
                )
                results.append((label, region, snap, data))
    except FatalAPIError as e:
        print(f"\nSTOPPED: {e}")
    for r in results:
        summarize(*r)

    print("\n=== Credits ===")
    for name, last, remaining in ledger:
        print(f"  {name:<28} cost={last}  remaining={remaining}")
    print(f"  TOTAL spent: {spent}   remaining balance: {ledger[-1][2] if ledger else 'n/a'}")


if __name__ == "__main__":
    main()
