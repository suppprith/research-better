"""Venue expectations, loaded from `references/venue-profiles.md`.

Only `default` ships. Every other venue is absent on purpose, because nobody
has verified its guidelines, and a venue profile written from memory produces
confident wrong advice that the author has no reason to doubt.

The loader therefore treats an unknown venue as an ordinary case rather than an
error: it falls back to `default` and says which profile it used, so a report
never implies venue-specific knowledge the tool does not have.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache
from importlib.resources import files
from pathlib import Path

from research_better.errors import ResearchBetterError

DEFAULT_PROFILES = "venue-profiles.md"
DEFAULT_VENUE = "default"

SECTION = re.compile(r"^##\s+(\S.*?)\s*$")
VENUE_ID = re.compile(r"^[a-z][a-z0-9_]*$")
KEY_VALUE = re.compile(r"^([a-z_]+):\s*(.*?)\s*$")

UNKNOWN = "unknown"


class VenueError(ResearchBetterError):
    """The venue profile file is missing or unusable."""


@dataclass(frozen=True, slots=True)
class VenueProfile:
    name: str
    fields: dict[str, str]

    @property
    def verified(self) -> bool:
        """Whether somebody read this venue's guidelines and recorded the date."""
        return bool(self.fields.get("checked")) and bool(self.fields.get("source"))

    def get(self, key: str) -> str:
        return self.fields.get(key, UNKNOWN)

    def expects(self, key: str) -> bool:
        """True only when the venue is on record as expecting it.

        `unknown` is not `yes`. A question raised because the tool assumed a
        requirement is a question the author cannot act on.
        """
        return self.get(key).lower() in {"yes", "required", "expected"}

    def is_unknown(self, key: str) -> bool:
        return self.get(key).lower() in {UNKNOWN, ""}


def parse_profiles(text: str) -> dict[str, VenueProfile]:
    profiles: dict[str, VenueProfile] = {}
    current: str | None = None
    fields: dict[str, str] = {}

    def close() -> None:
        if current is not None:
            profiles[current] = VenueProfile(current, dict(fields))

    for line in text.splitlines():
        heading = SECTION.match(line)
        if heading:
            close()
            title = heading.group(1)
            current = title if VENUE_ID.match(title) else None
            fields = {}
            continue
        if current is None:
            continue
        pair = KEY_VALUE.match(line)
        if pair:
            fields[pair.group(1)] = pair.group(2)

    close()

    if DEFAULT_VENUE not in profiles:
        raise VenueError(
            "venue-profiles.md has no [default] section, and every unknown venue falls back to it"
        )
    return profiles


def profiles_path() -> Path:
    return Path(str(files("research_better").joinpath("references", DEFAULT_PROFILES)))


@lru_cache(maxsize=4)
def load_profiles(path: Path | None = None) -> dict[str, VenueProfile]:
    target = path or profiles_path()
    if not target.is_file():
        raise VenueError(f"venue profiles not found at {target}")
    return parse_profiles(target.read_bytes().decode("utf-8"))


def for_venue(name: str | None, path: Path | None = None) -> VenueProfile:
    """The profile for a venue, falling back to default without complaint."""
    profiles = load_profiles(path)
    if not name:
        return profiles[DEFAULT_VENUE]
    return profiles.get(name.strip().lower().replace(" ", "_"), profiles[DEFAULT_VENUE])


def known_venues(path: Path | None = None) -> tuple[str, ...]:
    return tuple(sorted(load_profiles(path)))
