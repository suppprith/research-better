"""Turning a `Document` into `paper.json`.

Kept out of the model so the model stays a data structure and does not grow a
wire format it has to keep stable. This is the wire format, and it is allowed
to change with the artifact version.
"""

from __future__ import annotations

from typing import Any

from research_better.model import Document


def document_to_json(document: Document) -> dict[str, Any]:
    return {
        "path": str(document.path),
        "format": document.format,
        "source_hash": document.source_hash,
        "metadata": dict(document.metadata),
        "counts": {
            "sections": len(document.sections),
            "paragraphs": len(document.paragraphs),
            "sentences": len(document.sentences),
            "citations_used": sum(1 for c in document.citations if not c.in_bibliography),
            "citations_in_bibliography": sum(1 for c in document.citations if c.in_bibliography),
            "floats": len(document.floats),
            "protected_ranges": len(document.protected),
            "words_of_prose": document.word_count,
        },
        "sections": [
            {
                "id": section.id,
                "title": section.title,
                "level": section.level,
                "path": list(section.path),
                "parent_id": section.parent_id,
            }
            for section in document.sections
        ],
        "sentences": [
            {
                "id": sentence.id,
                "section_id": sentence.section_id,
                "paragraph_id": sentence.paragraph_id,
                "line": sentence.line,
                "char_range": [sentence.char_start, sentence.char_end],
                "text": sentence.text,
            }
            for sentence in document.sentences
        ],
        "citations": [
            {
                "id": citation.id,
                "key": citation.key,
                "raw": citation.raw,
                "sentence_id": citation.sentence_id,
                "in_bibliography": citation.in_bibliography,
                "resolved": _resolved(citation.resolved),
            }
            for citation in document.citations
        ],
        "floats": [
            {
                "id": item.id,
                "kind": str(item.kind),
                "label": item.label,
                "char_range": [item.span.char_start, item.span.char_end],
            }
            for item in document.floats
        ],
        "files": [
            {
                "file": segment.file,
                "global_range": [segment.global_start, segment.global_end],
                "local_start": segment.local_start,
            }
            for segment in document.file_segments
        ],
    }


def _resolved(work: Any) -> dict[str, Any] | None:
    if work is None:
        return None
    return {
        "doi": work.doi,
        "title": work.title,
        "year": work.year,
        "authors": list(work.authors),
        "venue": work.venue,
        "source": work.source,
        "url": work.url,
    }
