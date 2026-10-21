# 0002 — Two Kyojin runs: deterministic numbers at `--sessions 1`, concurrency at `--sessions 4`

## Status

Accepted.

## Context

Kyojin starts with `--sessions 1`, documented as "one request at a time, in order".
Raising it enables parallel decoding but is not behaviour-preserving: the server
warns that the decode attention kernel splits differently with a batch, so greedy
output at N > 1 is not guaranteed to equal the same request run alone, and that
`sessions × (ndt + 1) > 8` costs decode throughput. The N = 1 reference for
concurrency is therefore not obtainable from a process started with `--sessions 4`,
and the deterministic measurements cannot be obtained from one started with
`--sessions 4` either, because reproducibility is exactly what the user is relying
on when comparing two engines' answers to the same prompt.

Halogen has no such tension: it keeps four slots open permanently and a single
request simply occupies one of them.

## Decision

Kyojin is measured twice: once at `--sessions 1` for every deterministic number and
for the artifact runs, once at `--sessions 4` for the concurrency arm. The cost is
one extra warm start (about 82 s in the author's measurements) plus a second load
of the pack.

## Consequences

- Both the reproducibility of the deterministic numbers and a real N = 4 throughput
  figure are available, from one machine, without retracting either claim.
- The asymmetry between the two engines becomes visible in the method itself:
  Halogen needs one process to answer both questions and Kyojin needs two. That is
  reported as an observation rather than smoothed away by measuring Halogen twice
  as well.
- Anyone reproducing this needs the two compose invocations, not one. They are
  recorded in `bench.sh` and in the issue's server-command field.
