"""Everything that touches the network, and nothing else does.

Adapters ask this package for a URL and get a response. They never build a
client, never set a header, and never decide how long to wait, so politeness is
enforced in one place instead of being remembered in five.
"""

from __future__ import annotations

from research_better.net.cache import CacheEntry, HttpCache, cache_key, normalize_request
from research_better.net.client import (
    CONTACT_ENVIRONMENT_VARIABLE,
    OfflineCacheMissError,
    PoliteClient,
    Response,
    SourceUnavailableError,
    default_cache,
    resolve_contact,
    user_agent,
)
from research_better.net.limits import Limits, LimitsError, SourceLimit, TokenBucket, load_limits

__all__ = [
    "CONTACT_ENVIRONMENT_VARIABLE",
    "CacheEntry",
    "HttpCache",
    "Limits",
    "LimitsError",
    "OfflineCacheMissError",
    "PoliteClient",
    "Response",
    "SourceLimit",
    "SourceUnavailableError",
    "TokenBucket",
    "cache_key",
    "default_cache",
    "load_limits",
    "normalize_request",
    "resolve_contact",
    "user_agent",
]
