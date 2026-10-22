# Pagoda follow-up protocol — 2026-10-22

## Prompt

Design and create a very creative, elaborate, and detailed voxel art scene of a pagoda in a beautiful garden with trees, including some cherry blossoms. Make the scene impressive and varied and use colorful voxels. Use whatever libraries to get this done but make sure I can paste it all into a single HTML file.

## Bare

One original greedy repeat and five stochastic no-tools samples per engine; temperature 0.7, top_p 0.8, top_k 20, min_p 0, seeds 4101-4105, thinking off, max_tokens 16384.

## Agent

One real Pi SDK trial per engine, read/write/unique-edit/inspect tools, seed 5101, same stochastic sampling, 65536 output tokens total, 16384 per request, 1200 seconds, 12 assistant responses, 3 inspections.

## Browser

1280x900, observe after a 10-second window, save screenshot and current-route errors. No human repair hints. Close each owned browser before inference; sample CPU before every model request.

## Limits

Different packs/templates remain. No aesthetic score or population success-rate estimate. Interactions not exhaustively tested. Blank/loading/error/timeout outcomes are distinct.

## Privacy

Text records have host paths and operator identifiers scrubbed; request workspace paths become <workspace>. PNG bytes are unchanged. Manifest hashes describe these published bytes, not unsanitized private records.

## Interpretation and exclusions

Both final agent pages are inspectable; a cap stop is separate from page usability. The earlier failing greedy Kyojin answer was reproduced byte-for-byte with loop-guard metadata. No guard-disabling experiment or aesthetic ranking was performed. Bare/pilot timings are not clean comparative measurements.

- SDK tool-activation preflight errors: not engine failures.
- 32K/10-minute pilot: no local editing, unequal browser delays.
- 64K Halogen v2: animated test browser CPU contention; no matched Kyojin request.
- Bare Kyojin seed 4104: first collection interrupted by the parent command limit; one same-seed technical recapture, not a quality retry.
- Preliminary 1280x633 screenshots excluded; comparison frames are 1280x900.

## Rebuild versus repeat

The report rebuild verifies this evidence manifest; it does not contact a model or run generated pages. Archived harness sources are in harness/*.txt: local SDK installation paths are redacted, so they are source records, not turnkey executable scripts. Repeating live agent trials requires a compatible Pi SDK installation, a native browser feedback adapter and safe engine scheduling. Actual model HTTP requests, SSE responses, tool transcripts, file versions, timing and CPU gates are retained so the workflow can be inspected without assuming an unpublished daily-agent setup.
