"""Derive the distributional thresholds from a corpus of accepted papers.

Two of the structural rules make a claim about how humans write: that
sentence-length variance below some point, or a run of same-shaped paragraphs,
is unusual. A number invented for those rules would flag whatever the author of
the rule happened to dislike, and nobody could argue with it. So they ship
disabled until this script has been run and has written real values into
`rhythm-thresholds.toml`.

Usage:

    python scripts/calibrate_rhythm.py CORPUS_DIR [--percentile 5] [--write]

CORPUS_DIR holds accepted open-access papers as `.md` or `.tex`. Use papers
that were accepted at the venues this tool targets. A corpus of preprints, or
of one group's papers, calibrates to that group rather than to the field.

Without `--write` it prints what it would do and changes nothing.

The threshold is a low percentile of the observed distribution, so the rule
fires on paragraphs flatter than all but that fraction of real accepted
writing. Report the percentile and the corpus size in the paper if you ever
publish a claim about this, because the number means nothing without them.
"""

from __future__ import annotations

import argparse
import itertools
import statistics
import sys
from collections import defaultdict
from datetime import date
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))

from research_better.ingest import load  # noqa: E402
from research_better.model import Document  # noqa: E402

THRESHOLDS = REPO / "src" / "research_better" / "references" / "rhythm-thresholds.toml"

MINIMUM_CORPUS = 20
"""Below this many papers the percentile is noise. The script refuses rather
than writing a number that looks derived and is not."""


def paragraph_spreads(document: Document, minimum_sentences: int) -> list[float]:
    grouped: dict[str, list[int]] = defaultdict(list)
    for sentence in document.sentences:
        grouped[sentence.paragraph_id].append(len(sentence.text.split()))
    return [
        statistics.pstdev(lengths)
        for lengths in grouped.values()
        if len(lengths) >= minimum_sentences
    ]


def paragraph_runs(document: Document, tolerance: int) -> list[int]:
    """Lengths of runs of consecutive paragraphs with similar sentence counts."""
    counts: dict[str, int] = defaultdict(int)
    for sentence in document.sentences:
        counts[sentence.paragraph_id] += 1
    ordered = [counts[p.id] for p in document.paragraphs if counts.get(p.id)]

    runs: list[int] = []
    current = 1
    for previous, count in itertools.pairwise(ordered):
        if abs(count - previous) <= tolerance:
            current += 1
        else:
            runs.append(current)
            current = 1
    runs.append(current)
    return runs


def collect(corpus: Path, minimum_sentences: int, tolerance: int) -> tuple[list[float], list[int]]:
    spreads: list[float] = []
    runs: list[int] = []
    papers = 0

    for path in sorted(corpus.rglob("*")):
        if path.suffix.lower() not in {".md", ".markdown", ".tex"}:
            continue
        try:
            document = load(path)
        except Exception as error:
            print(f"  skipped {path.name}: {error}", file=sys.stderr)
            continue
        papers += 1
        spreads.extend(paragraph_spreads(document, minimum_sentences))
        runs.extend(paragraph_runs(document, tolerance))

    if papers < MINIMUM_CORPUS:
        raise SystemExit(
            f"Only {papers} paper(s) read from {corpus}. Below {MINIMUM_CORPUS} the "
            f"percentile is noise, and a number that looks derived but is not is "
            f"worse than an honestly disabled rule."
        )
    print(f"Read {papers} papers, {len(spreads)} paragraphs with enough sentences to measure.")
    return spreads, runs


def rewrite(spreads: list[float], runs: list[int], percentile: float, papers_note: str) -> str:
    text = THRESHOLDS.read_text(encoding="utf-8")
    min_stdev = statistics.quantiles(spreads, n=100)[int(percentile) - 1]
    minimum_run = int(statistics.quantiles(runs, n=100)[int(100 - percentile) - 1])

    text = _set(text, "sentence_length_variance", "enabled", "true")
    text = _set(text, "sentence_length_variance", "source", f'"{papers_note}"')
    text = _set(text, "sentence_length_variance", "min_stdev_words", f"{min_stdev:.2f}")
    text = _set(text, "paragraph_shape_uniformity", "enabled", "true")
    text = _set(text, "paragraph_shape_uniformity", "source", f'"{papers_note}"')
    text = _set(text, "paragraph_shape_uniformity", "minimum_run", str(max(3, minimum_run)))
    return text


def _set(text: str, section: str, key: str, value: str) -> str:
    lines = text.splitlines(keepends=True)
    inside = False
    for index, line in enumerate(lines):
        if line.startswith("["):
            inside = line.strip() == f"[{section}]"
            continue
        if inside and line.split("=")[0].strip() == key:
            lines[index] = f"{key} = {value}\n"
            return "".join(lines)
    raise SystemExit(f"could not find {key!r} in section [{section}] of {THRESHOLDS.name}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("corpus", type=Path, help="directory of accepted open-access papers")
    parser.add_argument("--percentile", type=float, default=5.0)
    parser.add_argument("--minimum-sentences", type=int, default=4)
    parser.add_argument("--tolerance", type=int, default=1)
    parser.add_argument("--write", action="store_true", help="update the threshold file")
    args = parser.parse_args()

    if not args.corpus.is_dir():
        raise SystemExit(f"{args.corpus} is not a directory")

    spreads, runs = collect(args.corpus, args.minimum_sentences, args.tolerance)
    note = (
        f"percentile {args.percentile:g} of {len(spreads)} paragraphs from "
        f"{args.corpus.name}, calibrated {date.today().isoformat()}"
    )
    updated = rewrite(spreads, runs, args.percentile, note)

    if not args.write:
        print("\nWould write:\n")
        print("\n".join(line for line in updated.splitlines() if "=" in line))
        print("\nRerun with --write to apply.")
        return 0

    THRESHOLDS.write_text(updated, encoding="utf-8", newline="\n")
    print(f"\nWrote {THRESHOLDS}. Commit it with the corpus named in the message.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
