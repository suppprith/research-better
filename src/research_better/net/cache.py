"""On-disk HTTP cache, which doubles as the test replay layer.

One mechanism rather than two. A separate record-and-replay harness for tests
would mean the suite exercises a transport the user never runs, and the first
bug that only appears in production would be in the seam between them. So the
tests point the real cache at a directory of recorded responses and run the
client in offline mode: an unrecorded request raises, which is exactly what a
replay layer is supposed to do.

Entries are one JSON file each, named by a hash of the normalized request. They
are readable on purpose. When a verdict looks wrong, the first question is what
the API actually returned, and the answer should be a file somebody can open.
"""

from __future__ import annotations

import base64
import hashlib
import json
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlencode, urlsplit

SECONDS_PER_DAY = 86400


def normalize_request(method: str, url: str, params: dict[str, str] | None = None) -> str:
    """A stable string for a request, so the same query hits the same entry.

    Query parameters are sorted and the host is lowercased, because
    `?a=1&b=2` and `?b=2&a=1` are the same request and caching them separately
    doubles the load on somebody else's server for nothing.
    """
    split = urlsplit(url)
    merged: dict[str, str] = {}
    if split.query:
        for pair in split.query.split("&"):
            if not pair:
                continue
            key, _, value = pair.partition("=")
            merged[key] = value
    merged.update({key: str(value) for key, value in (params or {}).items()})
    query = urlencode(sorted(merged.items()))
    return f"{method.upper()} {split.scheme}://{split.netloc.lower()}{split.path}?{query}"


def cache_key(method: str, url: str, params: dict[str, str] | None = None) -> str:
    return hashlib.sha256(normalize_request(method, url, params).encode("utf-8")).hexdigest()[:32]


@dataclass(frozen=True, slots=True)
class CacheEntry:
    key: str
    request: str
    status: int
    headers: dict[str, str]
    body: bytes
    stored_at: float
    source: str

    @property
    def text(self) -> str:
        return self.body.decode("utf-8", errors="replace")

    def age_seconds(self, now: float | None = None) -> float:
        return (now if now is not None else time.time()) - self.stored_at

    def is_fresh(self, ttl_seconds: float, now: float | None = None) -> bool:
        return self.age_seconds(now) < ttl_seconds

    def to_json(self) -> dict[str, object]:
        # Text bodies stay readable. Only genuinely binary payloads, which means
        # PDFs, get base64, and they are the rare case.
        try:
            body = self.body.decode("utf-8")
            encoding = "utf-8"
        except UnicodeDecodeError:
            body = base64.b64encode(self.body).decode("ascii")
            encoding = "base64"
        return {
            "request": self.request,
            "source": self.source,
            "status": self.status,
            "headers": self.headers,
            "body_encoding": encoding,
            "body": body,
            "stored_at": self.stored_at,
            "stored_at_readable": datetime.fromtimestamp(self.stored_at, UTC).isoformat(
                timespec="seconds"
            ),
        }

    @classmethod
    def from_json(cls, key: str, raw: dict[str, Any]) -> CacheEntry:
        body = str(raw.get("body", ""))
        decoded = (
            base64.b64decode(body) if raw.get("body_encoding") == "base64" else body.encode("utf-8")
        )
        headers = raw.get("headers") or {}
        return cls(
            key=key,
            request=str(raw.get("request", "")),
            status=int(raw.get("status", 0)),
            headers={str(k): str(v) for k, v in dict(headers).items()},
            body=decoded,
            stored_at=float(raw.get("stored_at", 0.0)),
            source=str(raw.get("source", "unknown")),
        )


class HttpCache:
    """Responses on disk, grouped by source so a directory is inspectable."""

    def __init__(self, root: Path, ignore_ttl: bool = False) -> None:
        self.root = Path(root)
        self.ignore_ttl = ignore_ttl
        """Set for recorded test fixtures, which must not expire in six months
        and turn a green suite red for reasons that have nothing to do with the
        code."""

    def path_for(self, source: str, key: str) -> Path:
        return self.root / source / f"{key}.json"

    def read(self, source: str, key: str, ttl_seconds: float) -> CacheEntry | None:
        target = self.path_for(source, key)
        if not target.is_file():
            return None
        try:
            raw = json.loads(target.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return None
        entry = CacheEntry.from_json(key, raw)
        if self.ignore_ttl or entry.is_fresh(ttl_seconds):
            return entry
        return None

    def write(self, entry: CacheEntry) -> Path:
        target = self.path_for(entry.source, entry.key)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            json.dumps(entry.to_json(), ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
            newline="\n",
        )
        return target

    def contains(self, source: str, key: str) -> bool:
        return self.path_for(source, key).is_file()

    def entries(self) -> list[Path]:
        return sorted(self.root.rglob("*.json")) if self.root.is_dir() else []
