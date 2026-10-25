"""Append-only raw storage and the capture manifest."""

from __future__ import annotations

import csv
import itertools
from datetime import date, datetime
from pathlib import Path

MANIFEST_FIELDS = ["source", "fetched_at", "status", "row_count", "request_cost", "request", "path"]


class RawStore:
    """Writes response bodies byte-for-byte to <root>/raw/<source>/<date>/<UTC timestamp>.json."""

    def __init__(self, root: Path):
        self.root = Path(root)

    def write(self, source: str, body: bytes, fetched_at: datetime) -> Path:
        day_dir = self.root / "raw" / source / fetched_at.strftime("%Y-%m-%d")
        day_dir.mkdir(parents=True, exist_ok=True)
        stem = fetched_at.strftime("%Y%m%dT%H%M%S.%fZ")
        for n in itertools.count():
            path = day_dir / (f"{stem}.json" if n == 0 else f"{stem}-{n}.json")
            try:
                # "x" mode fails if the file exists, so nothing is ever overwritten
                with open(path, "xb") as f:
                    f.write(body)
                return path
            except FileExistsError:
                continue
        raise AssertionError("unreachable")


class Manifest:
    def __init__(self, root: Path):
        self.path = Path(root) / "manifest.csv"

    def append(self, row: dict) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        new = not self.path.exists()
        with open(self.path, "a", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=MANIFEST_FIELDS)
            if new:
                writer.writeheader()
            writer.writerow({k: row.get(k, "") for k in MANIFEST_FIELDS})

    def rows(self) -> list[dict]:
        if not self.path.exists():
            return []
        with open(self.path, newline="") as f:
            return list(csv.DictReader(f))

    def credits_spent_on(self, source: str, day: date) -> int:
        total = 0
        for row in self.rows():
            if row["source"] == source and row["fetched_at"].startswith(day.isoformat()):
                total += int(float(row["request_cost"] or 0))
        return total
