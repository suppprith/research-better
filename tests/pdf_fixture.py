"""Builds the PDF fixture by writing the file, rather than checking one in.

A PDF in the repository is a blob nobody can review, and a PDF produced by a
typesetting library is a blob whose layout nobody controls. Column detection is
the whole difficulty of reading a paper back out of a PDF, so the fixture puts
every line at an exact coordinate: two columns with a real gutter, a running
header, a page number in the footer, line numbers down the left margin of the
submitted version, and a word hyphenated across a line break.

The file is written as raw PDF operators. That is more code than calling a
library and it is the point: the test knows precisely where every line sits, so
a failure means the reader is wrong rather than that a library changed its
layout.
"""

from __future__ import annotations

from pathlib import Path

PAGE_WIDTH = 612
PAGE_HEIGHT = 792

LEFT_COLUMN = 60
RIGHT_COLUMN = 320
"""A gutter of about 200 points between the columns, which is what a two-column
conference template gives you."""

LINE_HEIGHT = 12
TOP = 720
FOOTER = 40
HEADER = 750

Line = tuple[float, float, str]


def _escape(text: str) -> str:
    return text.replace("\\", r"\\").replace("(", r"\(").replace(")", r"\)")


def _stream(lines: list[Line]) -> bytes:
    body = "\n".join(
        f"BT /F1 9 Tf 1 0 0 1 {x:.1f} {y:.1f} Tm ({_escape(text)}) Tj ET" for x, y, text in lines
    )
    return body.encode("latin-1")


def _column(x: float, top: float, rows: list[str]) -> list[Line]:
    return [(x, top - index * LINE_HEIGHT, row) for index, row in enumerate(rows)]


def _page_lines(
    left: list[str],
    right: list[str],
    page_number: int,
    line_numbers: bool = False,
) -> list[Line]:
    lines: list[Line] = [
        (LEFT_COLUMN, HEADER, "Sparse Retrieval at Equal Cost"),
        (PAGE_WIDTH / 2, FOOTER, str(page_number)),
    ]
    lines += _column(LEFT_COLUMN, TOP, left)
    lines += _column(RIGHT_COLUMN, TOP, right)
    if line_numbers:
        # A submitted manuscript carries these down the margin. They are not
        # prose and they are not part of any sentence.
        lines += [
            (28, TOP - index * LINE_HEIGHT, str(index + 1)) for index in range(max(len(left), 1))
        ]
    return lines


PAGE_ONE_LEFT = [
    "1  INTRODUCTION",
    "Dense encoders are reported to beat sparse base-",
    "lines on this benchmark. The comparisons behind",
    "that claim hold the index size constant rather than",
    "the budget.",
    "We present a comparison that holds the retrieval",
    "budget fixed rather than the index size, and we re-",
    "port recall at ten for every configuration.",
]

PAGE_ONE_RIGHT = [
    "2  METHOD",
    "The corpus is indexed with BM25 and queries are",
    "expanded with the top three terms from a first pass",
    "over the corpus [1].",
    "It is important to note that the expansion is applied",
    "before the second pass rather than after it.",
]

PAGE_TWO_LEFT = [
    "3  RESULTS",
    "Recall at ten rises from 0.62 to 0.71 with expansion",
    "enabled, and the cost is one third of the dense base-",
    "line over five thousand queries [2].",
    "Table 1: Systems compared.",
]

TABLE_ROWS = [
    ("System", "Recall", "Cost"),
    ("BM25+QE", "0.71", "1.0"),
    ("Dense", "0.69", "3.2"),
]
"""Laid out as real table cells, at column positions with wide gaps between
them. A tool that reads these as prose produces sentences the author never
wrote, so the reader has to see the gaps and skip the row."""

PAGE_TWO_RIGHT = [
    "REFERENCES",
    # Copied verbatim from bad-paper.md so the recorded HTTP responses in
    # tests/fixtures/http answer the same queries. Citation verification from
    # PDF input alone is the main reason to read the format at all, and a test
    # of it that cannot reach a source would prove nothing.
    "[1] Robertson, S. and Zaragoza, H. The Probabilistic",
    "    Relevance Framework: BM25 and Beyond. Foundations",
    "    and Trends in Information Retrieval, 2009.",
    "    https://doi.org/10.1561/1500000019",
    "[2] Manning, C. D., Raghavan, P., and Schutze, H.",
    "    Introduction to Information Retrieval. Cambridge",
    "    University Press, 2008.",
]


def build(target: Path, line_numbers: bool = False, body_pages: int = 1) -> Path:
    """Write a two-column paper and return its path.

    `body_pages` repeats the first page for a caller that needs a paper long
    enough to count as full text rather than a stub. Only the first page
    repeats, because the last one opens the reference section and a second
    REFERENCES heading would put the pages after it in the bibliography.
    """
    last = body_pages + 1
    second = _page_lines(PAGE_TWO_LEFT, PAGE_TWO_RIGHT, last, line_numbers)
    table_top = TOP - len(PAGE_TWO_LEFT) * LINE_HEIGHT - LINE_HEIGHT
    for row, cells in enumerate(TABLE_ROWS):
        for column, cell in enumerate(cells):
            second.append((LEFT_COLUMN + column * 80, table_top - row * LINE_HEIGHT, cell))

    streams = [
        _stream(_page_lines(PAGE_ONE_LEFT, PAGE_ONE_RIGHT, number, line_numbers))
        for number in range(1, last)
    ]
    streams.append(_stream(second))
    return _write(target, streams)


def build_scanned(target: Path) -> Path:
    """A page with almost no extractable text, as a scan produces."""
    return _write(target, [_stream([(LEFT_COLUMN, TOP, "1")])])


def build_single_column(target: Path) -> Path:
    lines: list[Line] = [(LEFT_COLUMN, HEADER, "A Single Column Paper")]
    lines += _column(
        LEFT_COLUMN,
        TOP,
        [
            "1  INTRODUCTION",
            "This paper is set in one column across the whole",
            "page, which is what a thesis or a report looks like",
            "and what the reader must not split into two.",
        ],
    )
    return _write(target, [_stream(lines)])


def _write(target: Path, streams: list[bytes]) -> Path:
    objects: list[bytes] = []

    def add(body: bytes) -> int:
        objects.append(body)
        return len(objects)

    font = add(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")
    pages_number = len(streams) * 2 + 2

    page_numbers: list[int] = []
    for stream in streams:
        content = add(b"<< /Length %d >>\nstream\n%s\nendstream" % (len(stream), stream))
        page_numbers.append(
            add(
                b"<< /Type /Page /Parent %d 0 R /MediaBox [0 0 %d %d] "
                b"/Resources << /Font << /F1 %d 0 R >> >> /Contents %d 0 R >>"
                % (pages_number, PAGE_WIDTH, PAGE_HEIGHT, font, content)
            )
        )

    kids = b" ".join(b"%d 0 R" % number for number in page_numbers)
    pages = add(b"<< /Type /Pages /Kids [%s] /Count %d >>" % (kids, len(page_numbers)))
    assert pages == pages_number
    catalog = add(b"<< /Type /Catalog /Pages %d 0 R >>" % pages)

    out = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for number, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += b"%d 0 obj\n%s\nendobj\n" % (number, body)

    start = len(out)
    out += b"xref\n0 %d\n" % (len(objects) + 1)
    out += b"0000000000 65535 f \n"
    for offset in offsets[1:]:
        out += b"%010d 00000 n \n" % offset
    out += b"trailer\n<< /Size %d /Root %d 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (
        len(objects) + 1,
        catalog,
        start,
    )

    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(bytes(out))
    return target
