"""Packaging, completions, and the release gate.

None of this runs a release. What it pins down is the set of mistakes a release
cannot take back, because PyPI does not let a version be replaced: a tag that
disagrees with the version, a missing changelog section, a completion script
offering commands that no longer exist, and a long-lived upload token sitting
in the repository.
"""

from __future__ import annotations

import importlib.util
import sys
import tomllib
from pathlib import Path

import pytest

import research_better
from research_better.passes import PASSES

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts"
COMPLETIONS = ROOT / "completions"
WORKFLOW = ROOT / ".github" / "workflows" / "release.yml"
CHANGELOG = ROOT / "CHANGELOG.md"


def load_script(name: str):
    """Import a file from scripts/, which is not a package.

    Registered in `sys.modules` before it is executed, because a dataclass
    defined inside it resolves its own annotations by looking its module up
    there and fails on a module that is not registered yet.
    """
    if name in sys.modules:
        return sys.modules[name]

    sys.path.insert(0, str(SCRIPTS))
    try:
        spec = importlib.util.spec_from_file_location(name, SCRIPTS / f"{name}.py")
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)
        return module
    finally:
        sys.path.remove(str(SCRIPTS))


@pytest.fixture(scope="module")
def pyproject() -> dict:
    return tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))


# One version, in one place ---------------------------------------------------


def test_the_version_is_dynamic_and_read_from_the_package(pyproject: dict) -> None:
    # Two places to write a version is one place to forget one.
    assert "version" in pyproject["project"]["dynamic"]
    assert pyproject["tool"]["hatch"]["version"]["path"] == "src/research_better/__init__.py"


def test_the_cli_reports_the_package_version(capsys: pytest.CaptureFixture[str]) -> None:
    from research_better.cli import main

    with pytest.raises(SystemExit):
        main(["--version"])
    assert research_better.__version__ in capsys.readouterr().out


def test_both_entry_points_exist(pyproject: dict) -> None:
    scripts = pyproject["project"]["scripts"]
    assert scripts["research-better"] == "research_better.cli:main"
    assert scripts["rb"] == "research_better.cli:main"


# Extras ----------------------------------------------------------------------


def test_the_base_install_pulls_in_no_parser(pyproject: dict) -> None:
    # Someone installing this to check citations should not be made to install
    # a PDF stack to do it.
    assert pyproject["project"]["dependencies"] == ["httpx>=0.27"]


def test_every_format_extra_is_published(pyproject: dict) -> None:
    extras = pyproject["project"]["optional-dependencies"]
    assert {"latex", "docx", "pdf", "all"} <= set(extras)


def test_the_all_extra_is_the_union_of_the_others(pyproject: dict) -> None:
    extras = pyproject["project"]["optional-dependencies"]
    union = set(extras["latex"]) | set(extras["docx"]) | set(extras["pdf"])
    assert set(extras["all"]) == union


# Completions -----------------------------------------------------------------


def test_the_completions_are_checked_in() -> None:
    for shell in ("bash", "zsh", "fish"):
        assert (COMPLETIONS / f"research-better.{shell}").is_file()


def test_the_completions_match_the_parser() -> None:
    """Regenerating changes nothing.

    A hand-edited completion rots the moment a pass is added, and the shell
    then teaches the user that the new command does not exist.
    """
    generator = load_script("generate_completions")
    for name, body in generator.render().items():
        current = (COMPLETIONS / name).read_text(encoding="utf-8")
        assert current == body, f"{name} is stale. Run scripts/generate_completions.py"


@pytest.mark.parametrize("shell", ["bash", "zsh", "fish"])
def test_every_command_is_offered(shell: str) -> None:
    body = (COMPLETIONS / f"research-better.{shell}").read_text(encoding="utf-8")
    for name in [*PASSES, "run", "revert"]:
        assert name in body, f"{shell} completion does not offer {name}"


@pytest.mark.parametrize("shell", ["bash", "zsh", "fish"])
def test_both_entry_points_are_completed(shell: str) -> None:
    body = (COMPLETIONS / f"research-better.{shell}").read_text(encoding="utf-8")
    assert "research-better" in body
    assert "rb" in body


# The release gate ------------------------------------------------------------


def test_a_matching_tag_passes() -> None:
    check = load_script("check_release")
    assert check.check(f"v{research_better.__version__}") == []


def test_a_tag_that_disagrees_with_the_version_is_refused() -> None:
    check = load_script("check_release")
    problems = check.check("v99.0.0")
    assert any("does not match" in problem for problem in problems)


def test_a_version_with_no_changelog_section_is_refused() -> None:
    check = load_script("check_release")
    problems = check.check("v99.0.0")
    assert any("changelog" in problem.lower() for problem in problems)


def test_the_changelog_has_a_section_for_the_current_version() -> None:
    check = load_script("check_release")
    assert check.notes_for(research_better.__version__)


def test_the_release_notes_come_from_the_same_parser() -> None:
    # Two parsers would eventually disagree about which section belongs to
    # which version, and a release would carry somebody else's notes.
    notes = load_script("release_notes")
    check = load_script("check_release")
    version = research_better.__version__
    assert notes.notes_for(version) == check.notes_for(version)


def test_the_changelog_keeps_an_unreleased_section() -> None:
    assert "## Unreleased" in CHANGELOG.read_text(encoding="utf-8")


def test_the_release_check_needs_nothing_installed() -> None:
    """It reads the version out of the file rather than importing the package.

    It runs first in the release workflow, before anything is installed, and
    that ordering is the point: these are the cheap checks and they have to run
    on a machine with nothing on it. Importing the package pulled in httpx and
    failed the first real release.
    """
    source = (SCRIPTS / "check_release.py").read_text(encoding="utf-8")
    assert "from research_better import" not in source

    check = load_script("check_release")
    assert check.package_version() == research_better.__version__


# The release workflow --------------------------------------------------------


@pytest.fixture(scope="module")
def workflow() -> str:
    return WORKFLOW.read_text(encoding="utf-8")


def test_the_release_is_tag_triggered(workflow: str) -> None:
    assert 'tags: ["v*"]' in workflow


def test_publishing_uses_trusted_publishing(workflow: str) -> None:
    assert "id-token: write" in workflow
    assert "pypa/gh-action-pypi-publish" in workflow


def test_no_long_lived_upload_token_is_referenced(workflow: str) -> None:
    # A token in repository secrets is one to leak, rotate, and forget about.
    # Trusted publishing mints a short-lived one at upload time instead.
    for forbidden in ("PYPI_API_TOKEN", "PYPI_TOKEN", "TWINE_PASSWORD", "password:"):
        assert forbidden not in workflow


def test_nothing_is_published_before_it_is_smoke_tested(workflow: str) -> None:
    assert "needs: [build, smoke]" in workflow
    assert "scripts/smoke_test.py" in workflow


def test_the_release_checks_itself_before_it_builds(workflow: str) -> None:
    assert "scripts/check_release.py" in workflow
    assert workflow.index("check_release.py") < workflow.index("python -m build")


def test_the_smoke_test_covers_every_supported_python(workflow: str) -> None:
    versions = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    classifiers = versions["project"]["classifiers"]
    for classifier in classifiers:
        if classifier.startswith("Programming Language :: Python :: 3."):
            release = classifier.rsplit(" ", 1)[-1]
            assert f'"{release}"' in workflow, f"Python {release} is claimed and not smoke tested"


# The smoke test itself -------------------------------------------------------


def test_the_smoke_test_installs_no_extras() -> None:
    body = (SCRIPTS / "smoke_test.py").read_text(encoding="utf-8")
    assert "[all]" not in body
    assert "[pdf]" not in body


def test_the_smoke_test_cuts_the_network_rather_than_trusting_it() -> None:
    body = (SCRIPTS / "smoke_test.py").read_text(encoding="utf-8")
    assert "HTTPS_PROXY" in body
    assert "127.0.0.1:9" in body
