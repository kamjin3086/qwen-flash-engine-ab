# 0001 — One arm, with Halogen's daily configuration as the yardstick

## Status

Accepted.

## Context

Two engines (Halogen, Kyojin) serve the same model (Qwen3.8-Flash-Next) from
different packs, and both cannot be resident on the host at once. The question the
comparison has to answer is not "which engine is faster in the abstract" but "can
Kyojin replace the engine I already run every day". That question only has an answer
if Kyojin is measured at the configuration the daily engine actually runs.

The two configurations differ substantially out of the box: Halogen runs 262144
positions of context with vision, speculative decoding, prompt cache and a local chat
template; the Kyojin container's published defaults are 65536 positions and vision
off. A comparison at published defaults would measure the difference between two
unrelated setups.

## Decision

There is exactly one arm. Halogen keeps its daily configuration untouched and is the
yardstick; Kyojin is raised to that configuration (full context, vision on, same
generation parameters) before anything is measured. Halogen's defaults are not
treated as a variable and no "stock vs stock" arm is run.

The pack difference is not correctable and is disclosed rather than neutralised:
Halogen loads a 62.1 GiB `.hgn` checkpoint, Kyojin an EXL3 4.0 bpw pack. Speed
figures therefore describe engine plus quantization together, and output-quality
impressions are labelled as impressions.

## Consequences

- Any result answers a question the reader actually has ("does it fit my setup"),
  at the cost of being unfair-looking to an engine measured away from its own
  defaults. The writeup has to state the direction of that bias explicitly.
- Raising Kyojin's context increases its resident footprint substantially, so the
  memory cost of matching the daily configuration becomes a finding in itself
  rather than a setup detail.
- Adding a second, stock-default arm later is cheap (it is the same script against
  a different compose file); removing the framing after publication is not. That
  asymmetry is the reason this decision is recorded.
