# Passages that may read as machine-written

Causes, not a score. Nothing here was checked against a detection service,
and every fix below is a change that improves the paper on its own terms.
If a change would only make the text look less machine-written, it is not
offered. See docs/INTEGRITY.md.

**Flagged:** 6. **Looked at and left alone:** 1.

## Flagged

### Introduction, paragraph 1

> It is important to note that information retrieval has become a truly pivotal area of study in today's rapidly evolving landscape. As we all know, the realm of…

*fix: filler*

- **filler.** 12 deletable filler phrases: "It is important to note that", "truly", "pivotal", "in today's rapidly evolving landscape", and 8 more
  - Why this reads as generated: Filler is what fills a required length when there is nothing to say, which is the position a model is always in. A reader registers the padding before they register the argument.
  - What to do: Cut the phrases listed. Each is a deletion the sentence survives, and the fluff pass already carries them as an applicable patch.

Flagged on the content signals above. The texture, if any is listed, is recorded because it is there and is not a reason to change anything.

`par-95e2d6065c91`

### Introduction, paragraph 2

> Recent work may potentially suggest that adaptive expansion could possibly indicate a path forward, though the evidence seems to somewhat imply that the questi…

*fix: filler + hedge stack*

- **filler.** 4 deletable filler phrases: "It should be mentioned that", "performed an analysis of", "underscore", "crucial"
  - Why this reads as generated: Filler is what fills a required length when there is nothing to say, which is the position a model is always in. A reader registers the padding before they register the argument.
  - What to do: Cut the phrases listed. Each is a deletion the sentence survives, and the fluff pass already carries them as an applicable patch.
- **hedge stack.** 6 hedges in one sentence: Recent work may potentially suggest that adaptive expansion could possibly indicate a path forward, though th…
  - Why this reads as generated: Stacked hedges state a thing and withdraw it in the same breath. A model hedges because it cannot tell which claim it is entitled to. An author who knows what they measured hedges once, precisely.
  - What to do: Keep the one hedge you mean and delete the rest, or replace the lot with the actual limit: what you did not test, and on what.

Flagged on the content signals above. The texture, if any is listed, is recorded because it is there and is not a reason to change anything.

`par-57c1d505d727`

### Introduction, paragraph 3

> Our primary contribution is a formal proof that adaptive retrieval converges under bounded query drift. We also present a seamless framework that leverages thi…

*fix: ungrounded assertion + filler + uniform rhythm*

- **ungrounded assertion.** 2 sentence(s) with no citation and no number: "proof" in Our primary contribution is a formal proof that adaptive retrieval converges under bounded query dr…; "state-of-the-art" in We also present a seamless framework that leverages this result and delivers state-of-the-art perfo…
  - Why this reads as generated: Asserting confidently and citing nothing is what a model produces when it has nothing to cite, because the shape of the sentence is all it is reproducing. It is also the first sentence a reviewer attacks.
  - What to do: Add the measurement you took or the work that establishes it. If there is neither, this is not a sentence you can defend in review, so cut it.
- **filler.** 2 deletable filler phrases: "seamless", "leverages"
  - Why this reads as generated: Filler is what fills a required length when there is nothing to say, which is the position a model is always in. A reader registers the padding before they register the argument.
  - What to do: Cut the phrases listed. Each is a deletion the sentence survives, and the fluff pass already carries them as an applicable patch.
- **uniform rhythm.** 4 sentences varying by 1.5 words, against 6.3 across this paper
  - Why this reads as generated: Even sentence length is a texture a reader notices without being able to name it. It is also what a genuinely formulaic passage looks like, so it is never a reason to change anything on its own.
  - What to do: Nothing on its own. If the causes above are fixed the rhythm changes with them. Do not lengthen a sentence to break a pattern.

Flagged on the content signals above. The texture, if any is listed, is recorded because it is there and is not a reason to change anything.

`par-5d1f485fe515`

### Method, paragraph 2

> Moreover, our approach is efficient, scalable, and robust. Not only does it reduce latency, but it also improves recall. The design is simple, fast, and genera…

*fix: balanced clause + empty forward reference + tricolon*

- **balanced clause.** 2 in this paragraph: "Not only", "not only"
  - Why this reads as generated: A "not only, but also" frame used twice in a section is a template being filled. A reader hears the second one as a pattern and stops reading the content of it.
  - What to do: Say the two things in two sentences. If the second half was only there to balance the first, it goes.
- **empty forward reference.** 1 in this paragraph: "As will be discussed later"
  - Why this reads as generated: A forward reference that names no section, figure, or equation points at nothing. It is what a model writes because papers contain sentences of that shape, and it is what a reviewer follows and finds missing.
  - What to do: Name what it points at, or cut the sentence. If there is nothing later that discusses this, the promise was the whole content of the sentence.
- **tricolon.** 2 in this paragraph: "efficient, scalable, and robust", "simple, fast, and general"
  - Why this reads as generated: A three-item list repeated through a section is a cadence rather than an argument. Generated prose reaches for it because the shape is available whether or not there are three things to say.
  - What to do: Rewrite one of them as a plain sentence, or drop the item that is there to make the list a three. One tricolon is a choice and nobody notices it.

Flagged on the content signals above. The texture, if any is listed, is recorded because it is there and is not a reason to change anything.

`par-824720e39fee`

### Results, paragraph 1

> Additionally, our method significantly outperforms all prior approaches and delivers the best results reported to date. This is a novel finding that substantia…

*fix: ungrounded assertion*

- **ungrounded assertion.** 2 sentence(s) with no citation and no number: "best, outperforms, significantly" in Additionally, our method significantly outperforms all prior approaches and delivers the best resul…; "novel, substantially" in This is a novel finding that substantially advances the field.
  - Why this reads as generated: Asserting confidently and citing nothing is what a model produces when it has nothing to cite, because the shape of the sentence is all it is reproducing. It is also the first sentence a reviewer attacks.
  - What to do: Add the measurement you took or the work that establishes it. If there is neither, this is not a sentence you can defend in review, so cut it.

Flagged on the content signals above. The texture, if any is listed, is recorded because it is there and is not a reason to change anything.

`par-a3935a064e4e`

### Conclusion, paragraph 1

> We presented a unified framework for adaptive retrieval. The method indexes the corpus with BM25 and expands queries from a first-pass ranking. A unified frame…

*fix: section closing restatement*

- **section closing restatement.** 1 in this paragraph: "A unified framework for adaptive retrieval was presented."
  - Why this reads as generated: A closing sentence that introduces no word its section's opening did not already carry is filling a slot. Ending a section by restating it is a shape generated text produces reliably, because the shape is what it learned.
  - What to do: Cut it. Nothing in the section is lost, because nothing in it was only there.

Flagged on the content signals above. The texture, if any is listed, is recorded because it is there and is not a reason to change anything.

`par-056e211e5d81`

## Looked at, left alone

These tripped a texture signal and nothing else. A detector might dislike
them. That is not a reason to change writing that is doing its job.

### Method, paragraph 1

- 5 sentences varying by 1.4 words, against 6.3 across this paper

Likely a false positive, and worth leaving. This is a methods section, and methods prose is uniform because the method is a list of steps. This is the passage detectors get wrong most often on a technical paper, and mangling a correctly written method to break up its rhythm makes the paper worse.

## Not checked

- Nothing was skipped.