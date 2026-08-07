"""The scaffold holds: version reporting, exit codes, and extras errors."""

from __future__ import annotations

import pytest

import research_better
from research_better.cli import EXIT_OK, main
from research_better.errors import MissingExtraError, UnsupportedFormatError
from research_better.extras import available, require


def test_version_is_importable() -> None:
    assert research_better.__version__.count(".") == 2


def test_version_flag_prints_version(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exit_info:
        main(["--version"])
    assert exit_info.value.code == EXIT_OK
    assert research_better.__version__ in capsys.readouterr().out


def test_no_command_prints_help(capsys: pytest.CaptureFixture[str]) -> None:
    assert main([]) == EXIT_OK
    assert "usage: research-better" in capsys.readouterr().out


def test_missing_extra_names_the_install_command() -> None:
    with pytest.raises(MissingExtraError) as error_info:
        require("research_better_absent_dependency", "latex", "LaTeX ingest")

    message = str(error_info.value)
    assert 'pip install "research-better[latex]"' in message
    assert "LaTeX ingest" in message
    assert error_info.value.extra == "latex"


def test_require_returns_the_module_when_present() -> None:
    assert require("json", "latex", "LaTeX ingest").__name__ == "json"


def test_available_does_not_raise_on_missing() -> None:
    assert available("json") is True
    assert available("research_better_absent_dependency") is False


def test_unsupported_format_lists_what_is_supported() -> None:
    message = str(UnsupportedFormatError(".rtf", [".md", ".tex"]))
    assert ".rtf" in message
    assert ".md, .tex" in message
