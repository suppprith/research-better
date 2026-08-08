"""Shipping the skill: the manifests, and the preflight that stops it guessing.

The failure worth designing against is quiet. A skill whose scripts are not
installed does not crash: the model reads the paper and produces a confident
opinion with none of the checks behind it, under this tool's name. So the
preflight is a command that either runs or is not found, and the instruction on
not-found is to stop rather than to carry on by eye.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

import research_better
from research_better.cli import EXIT_CLEAN, main
from research_better.passes import PASSES

ROOT = Path(__file__).resolve().parent.parent
PLUGIN = ROOT / ".claude-plugin" / "plugin.json"
MARKETPLACE = ROOT / ".claude-plugin" / "marketplace.json"
SKILL = ROOT / "SKILL.md"


@pytest.fixture(scope="module")
def skill() -> str:
    return SKILL.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def manifest() -> dict:
    return json.loads(PLUGIN.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def marketplace() -> dict:
    return json.loads(MARKETPLACE.read_text(encoding="utf-8"))


# The manifests --------------------------------------------------------------


def test_the_plugin_manifest_names_the_skill(manifest: dict) -> None:
    assert manifest["name"] == "research-better"
    assert manifest["description"]


def test_the_plugin_version_tracks_the_package(manifest: dict) -> None:
    # A marketplace pins updates to this field. A stale one means nobody who
    # installed the skill ever receives another version of it.
    assert manifest["version"] == research_better.__version__


def test_the_marketplace_lists_the_plugin(marketplace: dict) -> None:
    entries = {plugin["name"]: plugin for plugin in marketplace["plugins"]}
    assert "research-better" in entries
    assert entries["research-better"]["source"] == "./"


def test_the_marketplace_has_an_owner(marketplace: dict) -> None:
    assert marketplace["owner"]["name"]


def test_the_marketplace_entry_says_the_package_is_needed(marketplace: dict) -> None:
    # Somebody installing from a plugin list has not read the README, and a
    # skill that cannot run its scripts is the failure this is guarding.
    entry = next(p for p in marketplace["plugins"] if p["name"] == "research-better")
    assert "pip install" in entry["description"]


def test_the_skill_sits_at_the_plugin_root(manifest: dict) -> None:
    # With no skills directory and no skills field, SKILL.md at the root is
    # loaded as the plugin's single skill, under its frontmatter name.
    assert "skills" not in manifest
    assert not (ROOT / "skills").exists()
    assert SKILL.is_file()


def test_the_skill_declares_its_own_name(skill: str) -> None:
    # Without it the invocation name falls back to the install directory, which
    # for a marketplace install is a version string that changes every update.
    assert re.search(r"^name:\s*research-better\s*$", skill, re.MULTILINE)


# The preflight --------------------------------------------------------------


def test_the_skill_checks_the_cli_before_anything_else(skill: str) -> None:
    preflight = skill.index("rb doctor --expect")
    first_pass = skill.index("rb ingest")
    assert preflight < first_pass


def test_the_expected_version_is_the_package_version(skill: str) -> None:
    found = re.search(r"rb doctor --expect (\S+)", skill)
    assert found is not None
    assert found.group(1) == research_better.__version__


def test_a_missing_cli_stops_the_skill(skill: str) -> None:
    section = skill[: skill.index("## Order")]
    assert "not found, stop" in section
    assert 'pip install "research-better[all]"' in section


def test_the_skill_says_why_improvising_is_the_failure(skill: str) -> None:
    # A skill that quietly reads the paper itself produces the unverified
    # opinion this tool exists to replace, wearing the tool's name.
    section = skill[: skill.index("## Order")]
    assert "reading the\npaper itself" in section or "reading the paper itself" in section


def test_the_skill_documents_what_it_writes(skill: str) -> None:
    assert ".research-better/" in skill
    assert "backs it up" in skill


def test_the_skill_lists_every_implemented_pass(skill: str) -> None:
    for name, entry in PASSES.items():
        if entry.implemented:
            assert f"rb {name} " in skill, f"the {name} pass has no step"


# The doctor command ---------------------------------------------------------


def test_doctor_needs_no_draft() -> None:
    assert main(["doctor", "--quiet"]) == EXIT_CLEAN


def test_doctor_reports_the_version(capsys: pytest.CaptureFixture[str]) -> None:
    main(["doctor"])
    assert research_better.__version__ in capsys.readouterr().out


def test_doctor_names_every_format(capsys: pytest.CaptureFixture[str]) -> None:
    main(["doctor"])
    printed = capsys.readouterr().out
    for suffix in (".md", ".tex", ".docx", ".pdf"):
        assert suffix in printed


def test_doctor_lists_the_passes_it_can_run(capsys: pytest.CaptureFixture[str]) -> None:
    main(["doctor"])
    printed = capsys.readouterr().out
    for name, entry in PASSES.items():
        if entry.implemented:
            assert name in printed


def test_a_matching_version_says_nothing(capsys: pytest.CaptureFixture[str]) -> None:
    main(["doctor", "--expect", research_better.__version__])
    assert "warning" not in capsys.readouterr().err


def test_a_mismatched_version_warns_and_does_not_fail(
    capsys: pytest.CaptureFixture[str],
) -> None:
    # A caller one patch ahead of the CLI is usually fine, and refusing to run
    # would block work over a difference that may not matter.
    assert main(["doctor", "--expect", "0.0.1"]) == EXIT_CLEAN
    captured = capsys.readouterr()
    assert "0.0.1" in captured.err
    assert "upgrade" in captured.err.lower()


def test_the_machine_readable_form_answers_the_same_questions(
    capsys: pytest.CaptureFixture[str],
) -> None:
    main(["doctor", "--json", "--quiet"])
    payload = json.loads(capsys.readouterr().out)
    assert payload["version"] == research_better.__version__
    assert "markdown" in payload["formats_ready"]
    assert payload["version_matches"] is True


def test_the_machine_readable_form_reports_a_mismatch(
    capsys: pytest.CaptureFixture[str],
) -> None:
    main(["doctor", "--json", "--quiet", "--expect", "0.0.1"])
    payload = json.loads(capsys.readouterr().out)
    assert payload["version_matches"] is False
    assert payload["expected_version"] == "0.0.1"


# The release gate covers the skill too --------------------------------------


def test_a_stale_plugin_version_would_fail_the_release(tmp_path: Path) -> None:
    from test_packaging import load_script

    check = load_script("check_release")
    problems = check._skill_problems("99.0.0")
    assert any("plugin.json" in problem for problem in problems)
    assert any("SKILL.md" in problem for problem in problems)


def test_the_skill_and_the_package_agree_right_now() -> None:
    from test_packaging import load_script

    assert load_script("check_release")._skill_problems(research_better.__version__) == []
