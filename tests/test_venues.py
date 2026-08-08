"""Venue profiles, and the discipline that keeps them from inventing advice."""

from __future__ import annotations

import pytest

from research_better.venues import (
    DEFAULT_VENUE,
    VenueError,
    for_venue,
    known_venues,
    parse_profiles,
    profiles_path,
)


def test_an_unknown_venue_falls_back_without_erroring() -> None:
    assert for_venue("a conference that does not exist").name == DEFAULT_VENUE
    assert for_venue(None).name == DEFAULT_VENUE
    assert for_venue("").name == DEFAULT_VENUE


def test_only_verified_venues_ship() -> None:
    # IEEE, ACM, Springer, and Elsevier are all wanted and none is present,
    # because their guidelines could not be reached to verify anything. A
    # profile written from memory is confident wrong advice.
    assert known_venues() == (DEFAULT_VENUE,)


def test_every_shipped_profile_records_where_it_came_from() -> None:
    for name in known_venues():
        profile = for_venue(name)
        assert profile.fields.get("source"), f"{name} does not say where it came from"
        assert profile.fields.get("checked"), f"{name} does not say when it was checked"


def test_unknown_is_not_treated_as_yes() -> None:
    profile = for_venue(DEFAULT_VENUE)
    # A question raised because the tool assumed a requirement is a question
    # the author cannot act on.
    assert profile.is_unknown("ablation_expected")
    assert not profile.expects("ablation_expected")


def test_a_profile_file_with_no_default_is_refused() -> None:
    with pytest.raises(VenueError, match="no \\[default\\] section"):
        parse_profiles("## ieee\nsource: x\nchecked: 2026-01-01\n")


def test_documentation_headings_are_not_venues() -> None:
    profiles = parse_profiles(
        "## How this file is parsed\n\nSome prose.\n\n"
        "## default\nsource: none\nchecked: 2026-01-01\n"
    )
    assert set(profiles) == {DEFAULT_VENUE}


def test_the_file_states_the_rule_for_adding_a_venue() -> None:
    text = profiles_path().read_bytes().decode("utf-8")
    assert "Do not add a section unless you have read" in text
    assert "checked" in text and "source" in text


def test_a_missing_file_says_where_it_looked(tmp_path) -> None:
    from research_better.venues import load_profiles

    with pytest.raises(VenueError, match="venue profiles not found"):
        load_profiles(tmp_path / "absent.md")
