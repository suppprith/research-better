# Venue profiles

What a given venue expects, so findings and reviewer questions are weighted for
where the paper is actually going. An ablation that a conference treats as
optional is often required by a journal, and asking for one in the wrong place
wastes the author's attention.

## The rule for adding a venue

**Do not add a section unless you have read that venue's own author guidelines
and are recording what they say.** Not what you remember, not what is
conventional in the field, not what another tool asserts. Venue requirements
change, and stale or invented guidance here is worse than no guidance, because
the author has no reason to doubt it and every reason to act on it.

Each venue section carries a `source` line linking the guidelines and a
`checked` line with the date they were read. A section without both is
incomplete and must be deleted rather than shipped.

## Current state

Only `default` is present. IEEE, ACM, Springer LNCS, and Elsevier are all
wanted, and none has been added, because the machine that built this could not
reach their author guidelines to verify anything: IEEE's author center returns a
Cloudflare challenge to a scripted client and ACM's site refused the connection.

Writing an IEEE section from general knowledge would have produced exactly the
confident wrong advice this file exists to prevent.

To add one: open the venue's author guidelines in a browser, copy what they
actually say into a new section below, and fill in `source` and `checked`.

## How this file is parsed

A `##` heading whose text reads like an identifier starts a venue section.
`key: value` lines set its fields. Any other `##` heading is documentation.
An unknown venue falls back to `default`.

## default

source: none. These are conservative defaults applied when no venue is named.
checked: 2026-08-08
ablation_expected: unknown
reproducibility_statement: encouraged
abstract_may_cite: unknown
page_limit: unknown
reference_limit: unknown
note: No venue was given, so nothing venue-specific is assumed. Reviewer questions are weighted by how universally they apply rather than by any venue's rules. Where a question depends on venue policy, it is raised as minor and says that it depends on the venue.
