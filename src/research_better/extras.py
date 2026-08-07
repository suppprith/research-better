"""Lazy loading for dependencies that live in optional extras.

Format adapters import their third-party parser through `require` rather than at
module top level. That keeps `import research_better` cheap and turns a missing
optional dependency into an error that names the install command.
"""

from __future__ import annotations

import importlib
from types import ModuleType

from research_better.errors import MissingExtraError


def require(module: str, extra: str, purpose: str) -> ModuleType:
    """Import `module`, or raise an error naming the extra that provides it.

    Args:
        module: Importable module name, for example `bibtexparser`.
        extra: Extra that installs it, for example `latex`.
        purpose: What the caller was trying to do, phrased as a sentence subject
            so it reads correctly in the message. For example "LaTeX ingest".
    """
    try:
        return importlib.import_module(module)
    except ImportError as exc:
        raise MissingExtraError(extra, purpose, missing_module=module) from exc


def available(module: str) -> bool:
    """Whether an optional dependency can be imported, without raising."""
    try:
        importlib.import_module(module)
    except ImportError:
        return False
    return True
