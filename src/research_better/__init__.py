"""Check a research paper instead of rewriting it.

The public surface is deliberately narrow while the foundation lands. See
`research_better.cli` for the command line and `research_better.errors` for the
exception hierarchy every layer raises through.
"""

__version__ = "0.1.0"

from research_better.errors import (
    MissingExtraError,
    ResearchBetterError,
    UnsupportedFormatError,
)

__all__ = [
    "MissingExtraError",
    "ResearchBetterError",
    "UnsupportedFormatError",
    "__version__",
]
