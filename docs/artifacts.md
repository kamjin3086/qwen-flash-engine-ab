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

Same harness on both engines (pi), 10 minute wall-clock cap, same prompt, tools
enabled. Reported as: did the page get produced inside the cap, how many tool calls,
how long to the finished page. Not a quality judgement.

The author's own harness (Hermes) is not published, so this cannot be compared to
the gallery's 2.7 min / 9 tool calls for the same prompt.

```
Create an animation in JS with 10 balls bouncing inside a spinning hexagon.
```

## Reporting rule

Both artifacts are published as screenshots plus the HTML files. The writeup says
what they are: one engine's single-shot attempt and one bounded agent attempt, on a
different harness and a heavier quantization than the gallery runs.
