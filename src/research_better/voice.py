"""A statistical fingerprint of how the author actually writes.

The edit pass uses this to constrain anything it produces, so that a change
reads like the author rather than like a model. Most of the profile is texture:
sentence length, hedging rate, which connectives they reach for, whether they
write "we" or nothing at all.

The terminology set is not texture. It is the load-bearing part.

The loudest tell of a machine edit is a synonym the author never used. A draft
that says "model" forty times and suddenly says "framework" once reads wrong to
a human before they can say why, and it reads wrong to a reviewer who knows the
author's other papers. So the terminology set records exact surface forms, not
lemmas. If the author writes "self-attention" and never "self attention", that
distinction is the whole point, and lemmatizing would erase it. The edit pass
treats this set as a whitelist.

Papers have several authors with different voices, so one global profile can be
a blend that matches nobody. Sections that carry enough text get their own
profile and the rest fall back to global.
"""

from __future__ import annotations

import itertools
import re
import statistics
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path

from research_better.lexicon import load_lexicon
from research_better.model import Document, Sentence

NAME = "voice"

MINIMUM_SECTION_WORDS = 150
"""Below this, a section gets no profile of its own and falls back to global.

This is a sample-size floor, not a claim about writing. A mean and a standard
deviation computed over five or six sentences move more with one long sentence
than with anything about the author, and a profile that noisy would constrain
the edit pass toward noise.
"""

MINIMUM_TERM_COUNT = 2
"""How often an ordinary word must appear before it counts as the author's
term rather than a passing choice. Hyphenated compounds and acronyms are exempt:
one use of "self-attention" already fixes the form that must not drift."""

WORD = re.compile(r"[A-Za-z][A-Za-z0-9'’-]*")
HYPHENATED = re.compile(r"^[A-Za-z]+(?:-[A-Za-z0-9]+)+$")
ACRONYM = re.compile(r"^[A-Z][A-Z0-9]{1,}$")

CONNECTIVES = (
    "however",
    "therefore",
    "thus",
    "hence",
    "while",
    "whereas",
    "although",
    "moreover",
    "furthermore",
    "nevertheless",
    "consequently",
)

FIRST_PERSON_PLURAL = re.compile(r"\b(?:we|our|ours|us)\b", re.IGNORECASE)
FIRST_PERSON_SINGULAR = re.compile(r"\b(?:I|my|mine|me)\b")

BE_VERBS = r"(?:is|are|was|were|be|been|being|becomes|became)"
# Past participles the -ed and -en pattern below cannot reach.
IRREGULAR_PARTICIPLES = """
    given taken seen shown known found made done written drawn held built kept left told
    brought thought sought caught taught chosen driven grown proven put set cut let read
    run become begun
    """.split()
PASSIVE = re.compile(
    rf"\b{BE_VERBS}\s+(?:\w+ly\s+)?"
    rf"(?:\w+(?:ed|en)\b|(?:{'|'.join(IRREGULAR_PARTICIPLES)})\b)",
    re.IGNORECASE,
)

OXFORD_COMMA = re.compile(r"\b[\w-]+,\s+[\w-]+,\s+(?:and|or)\s+[\w-]+\b")
NO_OXFORD_COMMA = re.compile(r"\b[\w-]+,\s+[\w-]+\s+(?:and|or)\s+[\w-]+\b")

# Spelling pairs, British form first. A short list on purpose: these are the
# ones that show up in CS papers and that a careless edit flips.
SPELLING_PAIRS = (
    ("analyse", "analyze"),
    ("analysed", "analyzed"),
    ("behaviour", "behavior"),
    ("centre", "center"),
    ("characterise", "characterize"),
    ("colour", "color"),
    ("generalise", "generalize"),
    ("labelled", "labeled"),
    ("modelling", "modeling"),
    ("normalise", "normalize"),
    ("optimise", "optimize"),
    ("organise", "organize"),
    ("parameterise", "parameterize"),
    ("recognise", "recognize"),
    ("summarise", "summarize"),
    ("utilise", "utilize"),
)

STOPWORDS = frozenset(
    """
    a about above after again against all also am an and any are as at be because been
    before being below between both but by can cannot could did do does doing down
    during each few for from further had has have having he her here hers him his how i
    if in into is it its itself just me more most my no nor not now of off on once only
    or other our ours out over own same she should so some such t than that the their
    theirs them then there these they this those through to too under until up us very
    was we were what when where which while who whom why will with would you your yours
    """.split()
)


@dataclass(frozen=True, slots=True)
class SentenceLengths:
    count: int
    mean: float
    stdev: float
    p10: float
    p90: float

    @classmethod
    def of(cls, lengths: list[int]) -> SentenceLengths:
        if not lengths:
            return cls(0, 0.0, 0.0, 0.0, 0.0)
        ordered = sorted(lengths)
        return cls(
            count=len(lengths),
            mean=round(statistics.fmean(lengths), 2),
            stdev=round(statistics.pstdev(lengths), 2) if len(lengths) > 1 else 0.0,
            p10=float(_percentile(ordered, 10)),
            p90=float(_percentile(ordered, 90)),
        )

    def to_json(self) -> dict[str, float]:
        return {
            "count": self.count,
            "mean": self.mean,
            "stdev": self.stdev,
            "p10": self.p10,
            "p90": self.p90,
        }


def _percentile(ordered: list[int], percent: float) -> int:
    if not ordered:
        return 0
    position = max(0, min(len(ordered) - 1, round((percent / 100) * (len(ordered) - 1))))
    return ordered[position]


@dataclass(frozen=True, slots=True)
class VoiceProfile:
    scope: str
    label: str
    word_count: int
    sentence_lengths: SentenceLengths
    hedges_per_hundred_words: float
    connectives: tuple[tuple[str, int], ...]
    passive_ratio: float
    person: str
    terminology: tuple[tuple[str, int], ...]
    hyphenation: tuple[tuple[str, str], ...]
    citations_per_paragraph: float
    oxford_comma: str
    spelling: str

    def uses(self, surface_form: str) -> bool:
        """Whether the author actually wrote this exact form.

        The check the edit pass makes before it is allowed to use a word.
        """
        return any(term == surface_form for term, _ in self.terminology)

    def to_json(self) -> dict[str, object]:
        return {
            "scope": self.scope,
            "label": self.label,
            "word_count": self.word_count,
            "sentence_lengths": self.sentence_lengths.to_json(),
            "hedges_per_hundred_words": self.hedges_per_hundred_words,
            "connectives": [list(pair) for pair in self.connectives],
            "passive_ratio": self.passive_ratio,
            "person": self.person,
            "terminology": [list(pair) for pair in self.terminology],
            "hyphenation": [list(pair) for pair in self.hyphenation],
            "citations_per_paragraph": self.citations_per_paragraph,
            "oxford_comma": self.oxford_comma,
            "spelling": self.spelling,
        }


@dataclass(frozen=True, slots=True)
class VoiceReport:
    whole_paper: VoiceProfile
    sections: tuple[VoiceProfile, ...]
    minimum_section_words: int = MINIMUM_SECTION_WORDS

    def for_section(self, section_id: str | None) -> VoiceProfile:
        """The profile the edit pass should honour for text in this section.

        Falls back to the global profile when the section is too short to
        measure. A blended profile beats a profile fitted to four sentences.
        """
        for profile in self.sections:
            if profile.scope == section_id:
                return profile
        return self.whole_paper

    def to_json(self) -> dict[str, object]:
        return {
            "minimum_section_words": self.minimum_section_words,
            "whole_paper": self.whole_paper.to_json(),
            "sections": [profile.to_json() for profile in self.sections],
        }


# Measurement --------------------------------------------------------------


def _hedge_terms(lexicon_file: Path | None) -> tuple[str, ...]:
    """Hedges come from the lexicon so the two passes cannot drift apart."""
    lexicon = load_lexicon(lexicon_file)
    return tuple(
        term.phrase.lower() for section in lexicon.family("hedge_stack") for term in section.terms
    )


def _words(text: str) -> list[str]:
    return WORD.findall(text)


def _terminology(
    sentences: list[Sentence],
) -> tuple[tuple[tuple[str, int], ...], tuple[tuple[str, str], ...]]:
    """Exact surface forms the author uses, with counts.

    Never lemmatized. "models" and "model" are two entries, because an edit
    that swaps one for the other is an edit the author did not make.
    """
    surface: Counter[str] = Counter()
    for sentence in sentences:
        tokens = _words(sentence.text)
        for token in tokens:
            surface[token] += 1
        for first, second in itertools.pairwise(tokens):
            if first.lower() not in STOPWORDS and second.lower() not in STOPWORDS:
                surface[f"{first} {second}"] += 1

    # The count floor is decided case-insensitively and the entry is recorded
    # case-sensitively. A word the author writes mid-sentence twice and once at
    # the start of a sentence is one term used three times, not two terms below
    # the floor, and both surface forms belong in the whitelist.
    grouped: Counter[str] = Counter()
    for form, count in surface.items():
        grouped[form.lower()] += count

    terms: list[tuple[str, int]] = []
    for form, count in surface.items():
        if form.lower() in STOPWORDS:
            continue
        exempt = bool(HYPHENATED.match(form) or ACRONYM.match(form))
        if grouped[form.lower()] >= MINIMUM_TERM_COUNT or exempt:
            terms.append((form, count))
    terms.sort(key=lambda pair: (-pair[1], pair[0]))

    return tuple(terms), _hyphenation(surface)


def _hyphenation(surface: Counter[str]) -> tuple[tuple[str, str], ...]:
    """Which spelling of a compound the author settled on.

    "self-attention", "self attention", and "selfattention" collapse to one key,
    and the profile records the form they actually wrote most often.
    """

    def key_of(form: str) -> str:
        return form.lower().replace("-", "").replace(" ", "")

    # Only compounds the author actually hyphenates somewhere are tracked.
    # Without this, the bigram "delivers state-of-the-art" would register as a
    # compound in its own right and the profile would fill with noise.
    hyphenated_keys = {key_of(form) for form in surface if HYPHENATED.match(form)}

    variants: dict[str, Counter[str]] = defaultdict(Counter)
    for form, count in surface.items():
        key = key_of(form)
        if key in hyphenated_keys:
            variants[key][form] += count

    preferences: list[tuple[str, str]] = []
    for key, forms in sorted(variants.items()):
        winner = max(forms.items(), key=lambda pair: (pair[1], pair[0]))[0]
        preferences.append((key, winner))
    return tuple(preferences)


def _person(text: str) -> str:
    plural = len(FIRST_PERSON_PLURAL.findall(text))
    singular = len(FIRST_PERSON_SINGULAR.findall(text))
    if plural == 0 and singular == 0:
        return "impersonal"
    return "we" if plural >= singular else "i"


def _oxford_comma(text: str) -> str:
    # The two patterns do not overlap: the comma after the second item stops
    # NO_OXFORD_COMMA from matching a serial list, so the counts are disjoint.
    with_comma = len(OXFORD_COMMA.findall(text))
    without = len(NO_OXFORD_COMMA.findall(text))
    if with_comma == 0 and without == 0:
        return "unknown"
    if without == 0:
        return "always"
    if with_comma == 0:
        return "never"
    return "mixed"


def _spelling(words: list[str]) -> str:
    lowered = Counter(word.lower() for word in words)
    british = sum(lowered[pair[0]] for pair in SPELLING_PAIRS)
    american = sum(lowered[pair[1]] for pair in SPELLING_PAIRS)
    if british == 0 and american == 0:
        return "unknown"
    if american == 0:
        return "british"
    if british == 0:
        return "american"
    return "mixed"


def _passive_ratio(sentences: list[Sentence]) -> float:
    """Share of sentences carrying a passive construction.

    Approximated by a be-verb followed by a past participle, with no part of
    speech tagging. It over-counts adjectival uses such as "is based" and
    under-counts participles this pattern does not know. It is a texture
    measurement, not evidence, and nothing is ever flagged on it alone.
    """
    if not sentences:
        return 0.0
    passive = sum(1 for sentence in sentences if PASSIVE.search(sentence.text))
    return round(passive / len(sentences), 3)


def _build_profile(
    scope: str,
    label: str,
    sentences: list[Sentence],
    paragraph_count: int,
    citation_count: int,
    hedges: tuple[str, ...],
) -> VoiceProfile:
    text = " ".join(sentence.text for sentence in sentences)
    words = _words(text)
    lengths = [len(sentence.text.split()) for sentence in sentences]
    lowered = text.lower()

    hedge_hits = sum(len(re.findall(rf"\b{re.escape(hedge)}\b", lowered)) for hedge in hedges)
    connective_counts = [(word, len(re.findall(rf"\b{word}\b", lowered))) for word in CONNECTIVES]
    ranked = tuple(
        sorted(
            ((word, count) for word, count in connective_counts if count),
            key=lambda pair: (-pair[1], pair[0]),
        )
    )

    terminology, hyphenation = _terminology(sentences)

    return VoiceProfile(
        scope=scope,
        label=label,
        word_count=len(words),
        sentence_lengths=SentenceLengths.of(lengths),
        hedges_per_hundred_words=round(100 * hedge_hits / len(words), 2) if words else 0.0,
        connectives=ranked,
        passive_ratio=_passive_ratio(sentences),
        person=_person(text),
        terminology=terminology,
        hyphenation=hyphenation,
        citations_per_paragraph=(
            round(citation_count / paragraph_count, 2) if paragraph_count else 0.0
        ),
        oxford_comma=_oxford_comma(text),
        spelling=_spelling(words),
    )


def extract(document: Document, lexicon_file: Path | None = None) -> VoiceReport:
    """Build the global profile and a profile for each section long enough."""
    hedges = _hedge_terms(lexicon_file)

    used_citations = [c for c in document.citations if not c.in_bibliography]
    whole = _build_profile(
        scope="whole_paper",
        label="(whole paper)",
        sentences=list(document.sentences),
        paragraph_count=len(document.paragraphs),
        citation_count=len(used_citations),
        hedges=hedges,
    )

    by_section: dict[str, list[Sentence]] = defaultdict(list)
    for sentence in document.sentences:
        if sentence.section_id:
            by_section[sentence.section_id].append(sentence)

    profiles: list[VoiceProfile] = []
    for section in document.sections:
        sentences = by_section.get(section.id, [])
        if not sentences:
            continue
        words = sum(len(sentence.text.split()) for sentence in sentences)
        if words < MINIMUM_SECTION_WORDS:
            continue
        paragraphs = {sentence.paragraph_id for sentence in sentences}
        citations = sum(
            1
            for citation in used_citations
            if citation.sentence_id
            and any(sentence.id == citation.sentence_id for sentence in sentences)
        )
        profiles.append(
            _build_profile(
                scope=section.id,
                label=section.title,
                sentences=sentences,
                paragraph_count=len(paragraphs),
                citation_count=citations,
                hedges=hedges,
            )
        )

    return VoiceReport(whole_paper=whole, sections=tuple(profiles))
