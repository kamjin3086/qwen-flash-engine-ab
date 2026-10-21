# 0004 — Output checks decide usability, never quality

## Status

Accepted.

## Context

The comparison needs to say something about what comes out of the two engines, and the
obvious move — a quality score — is not available. The two packs are different
quantizations of the same model, so any ranking of prose would be a ranking of
quantization choices dressed up as a ranking of engines. A human judge would also make
the result unreproducible, which is the one property this repository is built on.

At the same time, "does this engine produce something I can use" is a real question with
a real answer, and it is not the same question as "which output is prettier".

## Decision

Thirteen cases whose answers a script decides: arithmetic with one right number,
functions that must pass assertions we wrote rather than the ones the model wrote,
instructions with countable constraints, and a JSON shape. Pass or fail, with the failing
output kept. Plus two objective facts about each artifact page: does it form a complete
document, and does it depend on an external host.

No aesthetic judgement, no preference scoring, no "the output looks better".

## Consequences

- The result is reproducible and a reader can rerun it. The cost is that it says nothing
  about the qualities that make an answer pleasant to read, which the clickable artifact
  pages are there for.
- Failures split into two useful kinds: the same wrong answer from both engines (a
  property of the pack) and a wrong answer from one (where the engines diverge). That
  split turned out to be more informative than a score would have been — 8 cases behave
  identically, 2 fail identically, 3 diverge.
- A checker written wrong silently produces a false accusation. Every checker was
  self-tested against a known-good and a known-bad input before use, and one expected
  value was corrected after a hand count disagreed with it.
