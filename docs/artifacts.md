# Artifact prompts

Both prompts are the ones published in the author's gallery
(<https://yamz-labs.github.io/gallery/>), quoted verbatim. Gallery reference runs,
for context only — they were driven by the Hermes agent, which is not reproducible
here, so **our output is not comparable to those numbers**:

| Task | Engine 1.4, Qwen3.8-Flash-Next, server defaults |
|---|---|
| Pelican on a bicycle | 4.8 min · 5 tool calls |
| Balls in a spinning hexagon | 2.7 min · 9 tool calls |
| Voxel pagoda | 55 min · 64 tool calls |

## Measurement 8 — one-shot voxel pagoda

Conditions identical on both engines: one request, no tools, no retry,
`temperature 0`, `enable_thinking false`, one HTML file, saved as
`runs/<phase>/artifact-pagoda.html` and rendered in a browser for a screenshot.

```
Design and create a very creative, elaborate, and detailed voxel art scene of a pagoda in a beautiful garden with trees, including some cherry blossoms. Make the scene impressive and varied and use colorful voxels. Use whatever libraries to get this done but make sure I can paste it all into a single HTML file.
```

## Measurement 9 — bounded agent run, hexagon

The same two-tool scripted runner (`tools/agentrun.py`) on both engines, 10 minute
wall-clock cap, same prompt, tools enabled. This original hexagon run was not the Pi SDK
harness used in the later pagoda follow-up. Reported as: did the page get produced inside the cap, how many tool calls,
how long to the finished page. Not a quality judgement.

The author's own harness (Hermes) is not published, so this cannot be compared to
the gallery's 2.7 min / 9 tool calls for the same prompt.

```
Create an animation in JS with 10 balls bouncing inside a spinning hexagon.
```

## Pagoda follow-up — 2026-10-22

The original one-shot outputs are retained, including Kyojin's incomplete, loop-guard-stopped
answer. The [all-sample follow-up](pagoda-followup.html) shows an original-condition repeat
and five fixed stochastic bare samples per engine, plus a separate clean Pi SDK case each.
That SDK loop provides read/write/local-edit/browser-inspection tools; it is not the original
two-tool runner or the gallery author's Hermes setup.

Both final agent pages visibly present the requested scene, but the model stop differs:
Halogen reached a 12-response cap while continuing edits; Kyojin ended normally. A complete
HTML document, a rendered scene and normal agent completion are separate observations.
No aesthetic score or population success rate is claimed. The
[protocol and evidence](../results/pagoda-followup/protocol.md) disclose fixed budgets,
browser CPU contention in excluded timing runs, corrective clean runs and the technical
recapture of one interrupted bare collection.

Opening the report/gallery no longer runs generated animations in iframes. Static
screenshots are the default; opening individual pages may use external CDNs, fail or
consume substantial CPU. Close those pages when finished.

## Reporting rule

Both artifacts are published as screenshots plus the HTML files. The writeup says
what they are: one engine's single-shot attempt and one bounded agent attempt, on a
different harness and a heavier quantization than the gallery runs.
