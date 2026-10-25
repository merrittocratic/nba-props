"""Odds API credit guard: a daily cap and a floor on the plan's remaining credits."""

from __future__ import annotations

from dataclasses import dataclass

from nbaprops.http import Response

DAILY_CREDIT_CAP = 150
MONTHLY_FLOOR = 3000


def header_int(resp: Response | None, name: str) -> int | None:
    if resp is None:
        return None
    value = resp.headers.get(name)
    if value in (None, ""):
        return None
    return int(float(value))


@dataclass
class CreditBudget:
    spent_today: int
    daily_cap: int = DAILY_CREDIT_CAP
    monthly_floor: int = MONTHLY_FLOOR
    remaining: int | None = None

    def check(self, worst_case: int) -> str | None:
        """Return a reason to stop if a request costing up to `worst_case` could cross a limit."""
        if self.spent_today + worst_case > self.daily_cap:
            return (
                f"daily cap: spent {self.spent_today} today + up to {worst_case} "
                f"would exceed {self.daily_cap}"
            )
        if self.remaining is not None and self.remaining - worst_case < self.monthly_floor:
            return (
                f"monthly floor: {self.remaining} remaining - up to {worst_case} "
                f"would drop below {self.monthly_floor}"
            )
        return None

    def record(self, resp: Response) -> None:
        self.spent_today += header_int(resp, "x-requests-last") or 0
        remaining = header_int(resp, "x-requests-remaining")
        if remaining is not None:
            self.remaining = remaining
