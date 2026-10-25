"""The Odds API: NBA player props per event.

Costs (v4 docs): GET /events is free; GET /events/{id}/odds costs
[unique markets returned] x [regions], so at most len(MARKETS) x len(REGIONS).
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta

from nbaprops.budget import CreditBudget, header_int
from nbaprops.recorder import Recorder

log = logging.getLogger("nbaprops")

SOURCE = "odds_api"
BASE = "https://api.the-odds-api.com/v4/sports/basketball_nba"
MARKETS = (
    "player_points",
    "player_rebounds",
    "player_assists",
    "player_threes",
    "player_points_rebounds_assists",
    "player_points_rebounds",
)
# us_dfs carries Underdog, PrizePicks, Pick6 and Dabble lines (prices are indicative only)
REGIONS = ("us", "us_dfs")


def worst_case_cost() -> int:
    return len(MARKETS) * len(REGIONS)


def iso_z(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def count_outcomes(event: dict) -> int:
    return sum(
        len(m.get("outcomes", []))
        for b in event.get("bookmakers", [])
        for m in b.get("markets", [])
    )


def run(
    rec: Recorder, api_key: str, budget: CreditBudget, now: datetime, hours_ahead: int
) -> list[str]:
    """Capture props for events tipping off in [now, now + hours_ahead]. Returns plan lines."""
    window = (iso_z(now), iso_z(now + timedelta(hours=hours_ahead)))

    def on_response(resp):
        budget.record(resp)

    events_resp = rec.fetch(
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
        cost=lambda r: header_int(r, "x-requests-last") or 0,
        precheck=lambda: budget.check(0),
        on_response=on_response,
    )
    if events_resp is None or not events_resp.ok:
        return [f"odds_api: could not list events (spent today {budget.spent_today})"]
    events = events_resp.json()
    worst = worst_case_cost()
    plan = [
        f"odds_api: {len(events)} events tipping off {window[0]} .. {window[1]}",
        f"odds_api: markets={','.join(MARKETS)} regions={','.join(REGIONS)}",
        f"odds_api: up to {worst} credits per event, up to {worst * len(events)} for this run",
        f"odds_api: spent today {budget.spent_today}/{budget.daily_cap}, "
        f"remaining on plan {budget.remaining} (floor {budget.monthly_floor})",
    ]
    for ev in events:
        label = f"{ev['away_team']} @ {ev['home_team']} {ev['commence_time']}"
        if rec.dry_run:
            plan.append(f"  would fetch {label} (up to {worst} credits)")
            continue
        rec.fetch(
            SOURCE,
            f"GET /events/{ev['id']}/odds ({label})",
            lambda ev=ev: rec.http.get(
                f"{BASE}/events/{ev['id']}/odds",
                [
                    ("apiKey", api_key),
                    ("regions", ",".join(REGIONS)),
                    ("markets", ",".join(MARKETS)),
                    ("oddsFormat", "american"),
                    ("dateFormat", "iso"),
                ],
            ),
            count_rows=count_outcomes,
            cost=lambda r: header_int(r, "x-requests-last") or 0,
            precheck=lambda: budget.check(worst),
            on_response=on_response,
        )
    if rec.dry_run:
        blocked = budget.check(worst * len(events))
        plan.append(f"odds_api: budget check for full run: {blocked or 'ok'}")
    return plan
