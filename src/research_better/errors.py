"""Exception hierarchy.

Every failure the tool raises at its own boundaries descends from
`ResearchBetterError`, so a caller embedding the library can catch one type.
"""

from __future__ import annotations

DISTRIBUTION = "research-better"


class ResearchBetterError(Exception):
    """Base class for every error this package raises deliberately."""


class UnsupportedFormatError(ResearchBetterError):
    """The file extension has no ingest adapter."""

    def __init__(self, suffix: str, supported: list[str]) -> None:
        self.suffix = suffix
        self.supported = supported
        listed = ", ".join(sorted(supported))
        super().__init__(f"No ingest adapter for '{suffix}'. Supported: {listed}.")


class IngestError(ResearchBetterError):
    """The source could not be read as the format it claims to be."""


class ProtectedRangeError(ResearchBetterError):
    """A patch overlapped text that must never be edited.

    Math mode, command names, environment delimiters, and label or reference
    arguments are protected. An edit inside any of them produces a document
    that does not compile, which is a worse outcome than the writing problem
    the edit was trying to fix. The edit pass refuses rather than tries.
    """

    def __init__(self, description: str, overlaps: str) -> None:
        self.description = description
        self.overlaps = overlaps
        super().__init__(
            f"Refusing to patch {description}: it overlaps protected source ({overlaps}). "
            f"Editing there would break the build."
        )


class MissingExtraError(ResearchBetterError):
    """A feature was used whose dependency lives in an optional extra.

    The base install carries one dependency on purpose. Someone installing this
    to check citations should not be made to install a PDF stack to do it. The
    cost of that choice is this error, so it has to name the exact command to
    run rather than surfacing a bare ImportError from three frames down.
    """

    def __init__(self, extra: str, purpose: str, missing_module: str | None = None) -> None:
        self.extra = extra
        self.purpose = purpose
        self.missing_module = missing_module
        self.install_command = f'pip install "{DISTRIBUTION}[{extra}]"'
        detail = f" (missing module: {missing_module})" if missing_module else ""
        super().__init__(
            f'{purpose} needs the "{extra}" extra{detail}. Install it with: {self.install_command}'
        )
