from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from nbaprops.http import Response
from nbaprops.recorder import Recorder
from nbaprops.storage import Manifest, RawStore

FIXTURES = Path(__file__).parent / "fixtures"
FAKE_KEY = "test-key-0123456789abcdef"


def fixture_bytes(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


def fixture_json(name: str):
    return json.loads(fixture_bytes(name))


class FakeHttp:
    """Routes requests by URL substring to canned responses and records every call."""

    def __init__(self, routes: list[tuple[str, Response | list[Response]]]):
        self.routes = routes
        self.calls: list[tuple[str, str, object]] = []

    def _match(self, url: str) -> Response:
        for needle, resp in self.routes:
            if needle in url:
                if isinstance(resp, list):
                    return resp.pop(0) if len(resp) > 1 else resp[0]
                return resp
        raise AssertionError(f"no fake route for {url}")

    def get(self, url, params=None):
        self.calls.append(("GET", url, params))
        return self._match(url)

    def post_json(self, url, payload):
        self.calls.append(("POST", url, payload))
        return self._match(url)


class Clock:
    """Deterministic clock that ticks 1 ms per call so file names stay distinct."""

    def __init__(self, start: datetime):
        self.t = start

    def __call__(self) -> datetime:
        self.t += timedelta(milliseconds=1)
        return self.t


@pytest.fixture
def clock():
    return Clock(datetime(2025, 1, 15, 22, 0, tzinfo=UTC))


@pytest.fixture
def make_recorder(tmp_path, clock):
    def _make(http, dry_run=False):
        return Recorder(
            http,
            RawStore(tmp_path),
            Manifest(tmp_path),
            dry_run=dry_run,
            clock=clock,
            sleep=lambda s: None,
            redact=(FAKE_KEY,),
        )

    return _make
