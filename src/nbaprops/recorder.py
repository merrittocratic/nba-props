"""Fetch -> save raw -> manifest row, with one retry and failure logging."""

from __future__ import annotations

import logging
import time
import urllib.error
from collections.abc import Callable
from datetime import UTC, datetime

from nbaprops.http import Http, Response
from nbaprops.storage import Manifest, RawStore

log = logging.getLogger("nbaprops")

RETRY_STATUSES = {429, 500, 502, 503, 504}


def utcnow() -> datetime:
    return datetime.now(UTC)


class Recorder:
    def __init__(
        self,
        http: Http,
        store: RawStore,
        manifest: Manifest,
        dry_run: bool = False,
        clock: Callable[[], datetime] = utcnow,
        sleep: Callable[[float], None] = time.sleep,
        redact: tuple[str, ...] = (),
    ):
        self.http = http
        self.store = store
        self.manifest = manifest
        self.dry_run = dry_run
        self.clock = clock
        self.sleep = sleep
        self.redact = tuple(s for s in redact if s)
        self.failures = 0

    def clean(self, text: str) -> str:
        for secret in self.redact:
            text = text.replace(secret, "***")
        return text

    def skip(self, source: str, request: str, reason: str) -> None:
        log.warning("[%s] SKIPPED %s: %s", source, request, reason)
        if not self.dry_run:
            self.manifest.append(
                {
                    "source": source,
                    "fetched_at": self.clock().isoformat(),
                    "status": f"skipped: {reason}",
                    "row_count": 0,
                    "request_cost": 0,
                    "request": request,
                }
            )

    def fetch(
        self,
        source: str,
        request: str,
        send: Callable[[], Response],
        count_rows: Callable[[object], int],
        cost: Callable[[Response], int] = lambda r: 0,
        precheck: Callable[[], str | None] | None = None,
        on_response: Callable[[Response], None] | None = None,
        keep: Callable[[Response], bool] | None = None,
    ) -> Response | None:
        """Send a request; on success save the raw body and log a manifest row.

        `request` is a key-free label. `precheck` runs before every attempt and
        returns a reason string to stop. Retries once on network errors, 429 and 5xx.
        A non-retryable response that `keep` rejects is returned without saving the
        body or counting a failure; it gets a manifest row only if it cost credits.
        """
        for attempt in (1, 2):
            if precheck and (reason := precheck()):
                self.skip(source, request, reason)
                return None
            fetched_at = self.clock()
            try:
                resp = send()
            except (urllib.error.URLError, TimeoutError, OSError) as e:
                status, resp = f"error: {type(e).__name__}", None
                log.error(
                    "[%s] %s failed (attempt %d): %s", source, request, attempt, self.clean(str(e))
                )
            else:
                status = str(resp.status)
                if on_response:
                    on_response(resp)
            spent = cost(resp) if resp is not None else 0
            if keep and resp is not None and resp.status not in RETRY_STATUSES and not keep(resp):
                if spent and not self.dry_run:
                    self.manifest.append(
                        {
                            "source": source,
                            "fetched_at": fetched_at.isoformat(),
                            "status": f"{resp.status} discarded",
                            "row_count": 0,
                            "request_cost": spent,
                            "request": request,
                        }
                    )
                log.info("[%s] %s -> %s discarded cost=%s", source, request, status, spent)
                return resp

            row = {
                "source": source,
                "fetched_at": fetched_at.isoformat(),
                "status": status,
                "row_count": 0,
                "request_cost": spent,
                "request": request,
            }
            if resp is not None and resp.ok:
                try:
                    row["row_count"] = count_rows(resp.json())
                except (ValueError, KeyError, TypeError) as e:
                    row["status"] = f"{resp.status} unparsed: {type(e).__name__}"
                if not self.dry_run:
                    row["path"] = str(self.store.write(source, resp.body, fetched_at))
                    self.manifest.append(row)
                log.info(
                    "[%s] %s -> %s rows=%s cost=%s",
                    source,
                    request,
                    status,
                    row["row_count"],
                    spent,
                )
                return resp

            if resp is not None:
                snippet = self.clean(resp.body[:300].decode(errors="replace"))
                log.error("[%s] %s -> HTTP %s: %s", source, request, resp.status, snippet)
            if not self.dry_run:
                self.manifest.append(row)
            retryable = resp is None or resp.status in RETRY_STATUSES
            if attempt == 1 and retryable:
                self.sleep(2.0)
                continue
            self.failures += 1
            return None
        return None
