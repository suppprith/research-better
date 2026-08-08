"""Per-source rate limits, loaded from `references/source-limits.toml`.

The numbers live in a config file for the same reason the fluff terms do: when
a source changes its policy, the fix should be an edit to a documented file
rather than a hunt through code.
"""

from __future__ import annotations

import threading
import time
import tomllib
from dataclasses import dataclass, field
from functools import lru_cache
from importlib.resources import files
from pathlib import Path

from research_better.errors import ResearchBetterError

DEFAULT_LIMITS = "source-limits.toml"


class LimitsError(ResearchBetterError):
    """The source limits file is missing or unusable."""


@dataclass(frozen=True, slots=True)
class SourceLimit:
    name: str
    base_url: str
    requests_per_second: float
    burst: int
    documented: str
    polite_parameter: str | None = None


@dataclass(frozen=True, slots=True)
class Limits:
    sources: dict[str, SourceLimit]
    record_ttl_days: float
    search_ttl_days: float
    fulltext_ttl_days: float
    maximum_in_flight: int

    def for_source(self, name: str) -> SourceLimit:
        try:
            return self.sources[name]
        except KeyError:
            raise LimitsError(
                f"no limits configured for source {name!r}. Add a [{name}] section "
                f"to source-limits.toml with the rate that source documents."
            ) from None

    @property
    def record_ttl_seconds(self) -> float:
        return self.record_ttl_days * 86400

    @property
    def search_ttl_seconds(self) -> float:
        return self.search_ttl_days * 86400

    @property
    def fulltext_ttl_seconds(self) -> float:
        return self.fulltext_ttl_days * 86400


def limits_path() -> Path:
    return Path(str(files("research_better").joinpath("references", DEFAULT_LIMITS)))


def parse_limits(data: dict[str, object]) -> Limits:
    sources: dict[str, SourceLimit] = {}
    for name, section in data.items():
        if name in {"cache", "concurrency"} or not isinstance(section, dict):
            continue
        if "base_url" not in section:
            continue
        sources[name] = SourceLimit(
            name=name,
            base_url=str(section["base_url"]),
            requests_per_second=float(section.get("requests_per_second", 1.0)),
            burst=int(section.get("burst", 1)),
            documented=str(section.get("documented", "")),
            polite_parameter=(
                str(section["polite_parameter"]) if section.get("polite_parameter") else None
            ),
        )
    if not sources:
        raise LimitsError("source limits file lists no sources")

    cache = data.get("cache", {}) if isinstance(data.get("cache"), dict) else {}
    concurrency = data.get("concurrency", {}) if isinstance(data.get("concurrency"), dict) else {}
    return Limits(
        sources=sources,
        record_ttl_days=float(cache.get("record_ttl_days", 365)),
        search_ttl_days=float(cache.get("search_ttl_days", 7)),
        fulltext_ttl_days=float(cache.get("fulltext_ttl_days", 365)),
        maximum_in_flight=int(concurrency.get("maximum_in_flight", 4)),
    )


@lru_cache(maxsize=4)
def load_limits(path: Path | None = None) -> Limits:
    target = path or limits_path()
    if not target.is_file():
        raise LimitsError(f"source limits file not found at {target}")
    return parse_limits(tomllib.loads(target.read_bytes().decode("utf-8")))


@dataclass
class TokenBucket:
    """Spreads requests out instead of letting them arrive in a clump.

    A burst of four followed by a wait is friendlier to a shared API than four
    requests in the same millisecond, and it is what the polite pools are
    asking for when they publish a per-second number.
    """

    rate: float
    capacity: int
    tokens: float = field(init=False)
    updated_at: float = field(init=False, default_factory=time.monotonic)
    _lock: threading.Lock = field(init=False, default_factory=threading.Lock, repr=False)

    def __post_init__(self) -> None:
        self.tokens = float(self.capacity)

    def acquire(self, sleep: object = None) -> float:
        """Block until a token is free. Returns how long it waited."""
        waited = 0.0
        pause = time.sleep if sleep is None else sleep
        while True:
            with self._lock:
                now = time.monotonic()
                self.tokens = min(
                    float(self.capacity), self.tokens + (now - self.updated_at) * self.rate
                )
                self.updated_at = now
                if self.tokens >= 1.0:
                    self.tokens -= 1.0
                    return waited
                shortfall = (1.0 - self.tokens) / self.rate
            pause(shortfall)  # type: ignore[operator]
            waited += shortfall


class BucketRegistry:
    """One bucket per source, shared across every thread in the process."""

    def __init__(self, limits: Limits) -> None:
        self.limits = limits
        self._buckets: dict[str, TokenBucket] = {}
        self._lock = threading.Lock()

    def for_source(self, name: str) -> TokenBucket:
        with self._lock:
            if name not in self._buckets:
                limit = self.limits.for_source(name)
                self._buckets[name] = TokenBucket(
                    rate=limit.requests_per_second, capacity=limit.burst
                )
            return self._buckets[name]
