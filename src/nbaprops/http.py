"""Minimal stdlib HTTP client. Swappable in tests via the `Http` protocol."""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from typing import Protocol

USER_AGENT = "nba-props-capture/0.1"


@dataclass
class Response:
    status: int
    body: bytes
    headers: dict[str, str] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return 200 <= self.status < 300

    def json(self):
        return json.loads(self.body)


class Http(Protocol):
    def get(self, url: str, params: list[tuple[str, str]] | None = None) -> Response: ...

    def post_json(self, url: str, payload: object) -> Response: ...


class UrllibHttp:
    def __init__(self, timeout: float = 60.0):
        self.timeout = timeout

    def get(self, url: str, params: list[tuple[str, str]] | None = None) -> Response:
        if params:
            url = f"{url}?{urllib.parse.urlencode(params)}"
        return self._send(urllib.request.Request(url, headers={"User-Agent": USER_AGENT}))

    def post_json(self, url: str, payload: object) -> Response:
        req = urllib.request.Request(
            url,
            data=json.dumps(payload).encode(),
            headers={"User-Agent": USER_AGENT, "Content-Type": "application/json"},
            method="POST",
        )
        return self._send(req)

    def _send(self, req: urllib.request.Request) -> Response:
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                return Response(
                    resp.status, resp.read(), {k.lower(): v for k, v in resp.headers.items()}
                )
        except urllib.error.HTTPError as e:
            return Response(e.code, e.read(), {k.lower(): v for k, v in e.headers.items()})
