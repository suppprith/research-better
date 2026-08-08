# Fluff lexicon

The single source of truth for the lexical fluff rules. Adding, removing, or
reweighting a term is an edit to this file and nothing else. No Python change.

The skill layer reads this same file to explain a finding, so the notes here are
user-facing text, not developer comments.

## How this file is parsed

A `##` heading whose text reads like an identifier, lowercase letters, digits,
and underscores, starts a rule section. Any other `##` heading is documentation
and is skipped, which is how this section exists without becoming a rule.

Lines of the form `key: value` before the first list item set the section's
defaults. Each `- item` is a term. An item written `- pattern -> replacement`
carries its own replacement and is reported as `replace_with`.

Recognised keys:

* `family` names the matcher that handles the section. Defaults to the section
  id. Several sections can share a matcher and differ only in severity.
* `severity` is `high`, `medium`, or `low`. Only `high` is auto-actionable.
* `suggestion` is `delete`, `delete_clause`, `replace_with`, or `review`.
* `note` is the one-line explanation shown to the user.

Everything else, including this prose, is ignored by the parser.

## filler_openers

family: filler_opener
severity: high
suggestion: delete_clause
note: This opener announces that a sentence is coming instead of making a claim. The sentence reads the same without it.

- It is important to note that
- It is worth noting that
- It should be mentioned that
- It should be noted that
- It is interesting to note that
- It is worth mentioning that
- Needless to say
- As we all know
- As is well known
- In today's rapidly evolving landscape
- In today's world
- In the modern era
- In recent years, there has been growing interest in
- It goes without saying that
- One might argue that
- At the end of the day
- When it comes to
- This paper aims to shed light on
- Let us now turn our attention to

## empty_intensifiers

family: empty_intensifier
severity: medium
suggestion: delete
note: An intensifier in front of an unmeasured adjective adds emphasis, not information. Report the number instead, or drop the word.

- very
- extremely
- highly
- incredibly
- truly
- quite
- rather
- particularly
- remarkably
- exceptionally
- vastly
- immensely
- tremendously
- profoundly

## hedge_adverbs

family: hedge_stack
severity: high
suggestion: delete
note: One hedge is normal in academic writing and often correct. Two in one clause cancel each other out and leave the reader unsure what is being claimed. This one can come out on its own, leaving the hedge you wrote first.

- potentially
- possibly
- perhaps
- somewhat
- arguably
- presumably
- conceivably
- relatively
- fairly
- to some extent
- in some cases
- more or less
- in general
- for the most part

## hedge_verbs

family: hedge_stack
severity: medium
suggestion: review
note: A second hedging verb in the same clause. Deleting a verb would leave the sentence ungrammatical, so decide which hedge you meant and drop the other.

- may
- might
- could
- would appear
- seems
- seem
- appears
- appear
- suggests
- suggest
- indicates
- indicate
- tends to
- tend to

## model_vocabulary

family: model_vocabulary
severity: low
suggestion: review
note: This word appears far more often in generated text than in accepted papers. That is not proof of anything, and some of these words are correct in context, so this is raised for a human rather than acted on.

- delve
- delves
- delving
- tapestry
- underscore
- underscores
- underscoring
- pivotal
- realm
- landscape
- testament
- harness
- harnesses
- harnessing
- leverage
- leverages
- leveraging
- meticulous
- meticulously
- intricate
- intricacies
- crucial
- seamless
- seamlessly
- multifaceted
- paradigm shift
- game changer
- unlock the potential
- navigate the complexities
- ever-evolving
- cutting-edge
- robust and scalable

## nominalizations

family: nominalization
severity: medium
suggestion: replace_with
note: The verb is buried in a noun. Using the verb directly is shorter and says the same thing.

- performs an analysis of -> analyses
- performed an analysis of -> analysed
- perform an analysis of -> analyse
- makes a contribution to -> contributes to
- make a contribution to -> contribute to
- made a contribution to -> contributed to
- provides an explanation of -> explains
- provide an explanation of -> explain
- carries out an evaluation of -> evaluates
- carry out an evaluation of -> evaluate
- conducted an investigation of -> investigated
- conduct an investigation of -> investigate
- gives consideration to -> considers
- give consideration to -> consider
- is indicative of -> indicates
- are indicative of -> indicate
- has the ability to -> can
- have the ability to -> can
- in the event that -> if
- for the purpose of -> to
- with the exception of -> except
- a large number of -> many
- due to the fact that -> because
- in spite of the fact that -> although

## unsupported_superlative_adverbs

family: citation_free_superlative
severity: high
suggestion: delete
note: This adverb claims a magnitude with no number and no citation behind it. Deleting it costs the sentence nothing and removes a claim you cannot defend.

- significantly
- substantially
- dramatically
- markedly
- considerably
- vastly
- greatly

## unsupported_superlative_claims

family: citation_free_superlative
severity: medium
suggestion: review
note: A reviewer will ask what this is measured against. Either cite the comparison or drop the claim. Deleting the word alone would leave the sentence broken, so this one goes to you.

- state-of-the-art
- the best
- the first
- the only
- novel
- unprecedented
- groundbreaking
- superior to all
- outperforms all

## balanced_clause_templates

family: balanced_clause
severity: low
suggestion: review
note: A balanced two-part template. One is a stylistic choice. Several in one section is a cadence rather than an argument, and it is one of the patterns that makes text read as generated.

- not only
- on the one hand
- on the other hand
- it is not merely
- rather than simply
- both a
- at once a

## forward_reference_phrases

family: empty_forward_reference
severity: low
suggestion: review
note: This promises a discussion later in the paper and names no target, so no reader and no reviewer can check the promise was kept. Point at a section, or drop the sentence.

- as will be discussed later
- as will be shown later
- as we will see
- as we shall see
- we will show later
- later in this paper
- as discussed below
- in what follows
- more on this later

## throat_clearing_transitions

family: throat_clearing
severity: medium
suggestion: delete
note: Three or more paragraphs in a row opening this way reads as a list of additions rather than an argument. One of them is fine. A run of them is a pattern.

- Moreover
- Furthermore
- Additionally
- In addition
- Consequently
- Notably
- Importantly
