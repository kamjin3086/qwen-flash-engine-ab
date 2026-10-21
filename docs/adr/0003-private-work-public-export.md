# 0003 — Two repositories: a private working repo and a generated public export

## Status

Accepted.

## Context

The comparison needs a public surface: the maintainer has to be able to read the
numbers and open the artifact pages, and a Reddit reply has to link somewhere. The
work that produces that surface, however, is not fit to publish, and not only for
taste reasons:

- `runs/**` holds server logs, resolved compose files and environment captures. They
  contain absolute host paths, the host's product name, and the names of unrelated
  services running on the same machine.
- The repository also holds drafts written for a specific reader — how the reply in
  the thread is shaped, what the maintainer is likely to act on. Those are working
  notes about a conversation, not part of the measurement.
- The history itself records wrong turns: an arithmetic error about memory that was
  corrected, an abandoned framing. A public benchmark post whose commit log contains
  "actually I was wrong about this" invites the reader to distrust the final numbers
  even when the final numbers are right.

GitHub's visibility switch publishes the entire history of a repository, and it is
effectively one-way: forks, clones and caches survive a reversal. So "keep it private
for now and flip it later" is not available.

## Decision

Two repositories, one-way.

- **The working repository** — private, permanently. Every ADR, spec, ticket,
  branch, pull request, code review and raw log lives here. This is where the work
  happens and where its history is allowed to be messy.
- **The published repository** (`qwen-flash-engine-ab`) — public, holds only what a reader needs: the method,
  the summary, the scrubbed raw JSON, the artifact pages and screenshots, the
  generated report, and the ADRs that explain the method. Its first commit is a
  curated snapshot, not a mirror of any history.

The public repository is **produced by a generator**, not assembled by hand and not
pushed from the private remote. The generator copies an allowlist of paths, refuses
to write output containing an absolute host path or the operator's username, and
records what it copied. Its output is idempotent.

Consequence for links: anything a third party reads — the `benchmark_report` issue
in the maintainer's tracker, the Reddit reply — points at the public repository. The
private one is never referenced from a public surface.

## Consequences

- The public tree can be regenerated after any re-run, and the same privacy assertion
  that guards the report guards the export, because they are one check in one place.
- The private repository's issues and pull requests can never be linked publicly,
  which means the spec and tickets are working documents and the *public* record of
  what was decided has to be the ADRs and the method section. That duplication is
  deliberate: it is the price of a clean public history.
- Deleting the public repository is cheap and re-exporting is cheap; neither is true
  of unpublishing history, which is the asymmetry this decision buys.
- The export adds a step between "results exist" and "results are published". If that
  step is skipped in a hurry and the tree is assembled by hand, the anti-drift
  guarantee that ADR-0001 relies on for the report is lost at the last moment.
