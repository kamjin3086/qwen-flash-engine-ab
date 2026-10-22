# What the numbers say

**One sentence:** on this machine, with these two packs, Kyojin's decode is a tie overall —
the lead trades per prompt class — but it needs 28–37 % more time to prefill (1.28–1.37× lower
throughput), its observed warm container restart took 2.7× as long, and it produced
an incomplete page on the task the comparison was originally about. If the question is "should I switch my daily driver", the answer here
is no; if the question is "is the EXL3 route competitive", the decode numbers say yes.

Everything below is a value from the tables, the artifact cards, or the raw files they
link. Nothing here is a judgement of the model, only of what came out of each engine.

**How many times each number was measured.** Prefill and decode at the author's sizes are
the median of three runs. Everything else is one observation: both retrieval depths, the tool call, the concurrency
rows, the two prefix requests, the two starts, and the artifacts were each measured once. The
32K / 128K / 262K prefill and first-token points were repeated after the run; they are in the
Variance table, not in this sentence. One observation
on one machine is enough to say *this is how it behaved here*; it is not a distribution. The
prefill ratio is quoted because it holds across four prompt sizes, not because it was
repeated.

The repetitions added after the run cover prefill and first-token latency at 32K / 128K /
262K, three times each in one start per engine. The N=4 row was repeated too, but the
repeated runs hit the prompt cache on all four requests while the original run had none, so
they are not like-for-like and are not shown as variance. Startup is still a single
observation per engine: a cold Kyojin start is about nine minutes, and repeating it was not
worth the machine time.

## AI assistance

This comparison was carried out with AI assistance across test planning, scripting,
execution troubleshooting, analysis, and writing. AI assistance is not independent
validation: the published raw records and reproducible report are the basis for checking
the claims. The author is responsible for what is published; this disclosure does not
imply that every record has been independently checked by a human.

## Where the two engines actually differ

**Prefill is the real gap, and it is uniform.** Halogen is faster at every context length
I measured, and the ratio barely moves (1.28× at the author's size, 1.36–1.37× from 32K to
262K; 1.36–1.39× across those points and their repetitions). The author's-size ratio compares
2,737 tokens against 3,110, because the two tokenizers disagree on the same text. Both
engines lose about the same share of their speed as the prompt grows (−7.8 % and −6.8 %
from 32K to 262K), so this is not a long-context effect: it is a constant factor on
forward pass throughput.

**Decode is a tie per request.** 49.5 / 53.6 / 60.8 tok/s against 53.4 / 50.9 / 56.8 across
prose, chat and code. Aggregate *output* throughput, which includes prompt processing, is
another matter: Halogen serves 23–34 % more tokens per second across N=1, 2 and 4 because its
prefill is faster. The two engines trade the lead per prompt class and the spread between
classes inside one engine is larger than the spread between engines. Anyone quoting a
single decode number from this comparison is describing one prompt class, not an engine.

The three runs behind each prefill and decode figure are in the *Repetitions* table on the
page, and they make that statement precise: the prefill ranges do not overlap, so the gap
there is not noise; the decode ranges overlap on chat and separate on prose and code, in
opposite directions. The ordering depends on the prompt class more than on the engine.

**Time to first token at 262K** follows the prefill gap: 148 s against 204 s.

**Startup is the largest single difference in the whole comparison.** 37 s against 561 s
on a first start with empty compile caches and a dropped OS page cache, and
16 s against 43 s on a warm container restart. The warm measurements retained compile caches and did
not clear the OS page cache; each is one observation. These are not host-reboot timings
and do not establish how long a new installation or a machine reboot will take.

## Parallel requests buy latency isolation, not throughput

Four 8K-prompt requests released at once with `max_tokens=512`; the replies came back at
about 350 tokens each, which is what the wall and aggregate columns reconcile to. *Aggregate*
is all output tokens over the whole wall time, prompt processing included; *per request* is
decode only, measured from the first token. They are not expected to match.

| | wall | aggregate | per request | first token (median) |
|---|---:|---:|---:|---:|
| Halogen, 1 request | 10.1 s | 35.1 tok/s | 60.8 tok/s | 4.3 s |
| Halogen, 4 requests | 33.4 s | 42.4 tok/s | 16.6 tok/s | 11.6 s |
| Kyojin, 1 request | 12.3 s | 28.4 tok/s | 53.4 tok/s | 5.8 s |
| Kyojin, 4 requests | 45.6 s | 31.6 tok/s | 16.3 tok/s | 23.0 s |

Quadrupling the requests buys 21 % more output throughput on Halogen and 11 % on Kyojin,
while per-request decode speed falls by about 70 %. Both engines are limited by the same
thing at that point. The difference that matters for a user running four agents is not
throughput but **how long a request waits for its first token**: a median of 11.6 s against
23.0 s, and the 95th percentile — the maximum at four requests — 19.1 s against 23.0 s. Those rows are one observation:
when the run was repeated, every request in the repeat hit the prompt cache, so the repeat
measures a different thing and is not quoted as a range.

Kyojin's own startup log names the reason its parallel mode is not free: at four sessions
its decode attention kernel splits differently and its output is no longer guaranteed to
equal a solo run.

## What an agent turn actually costs

An agent re-sends its whole history every turn, so the number that shapes daily feel is
the second one:

| | cold prefix (97K) | same prefix again | cached tokens |
|---|---:|---:|---:|
| Halogen | 53.5 s | **0.58 s** | 95,680 of 95,728 |
| Kyojin | 74.9 s | **2.96 s** | 94,208 of 97,538 |

Both engines make a repeated prefix almost free. Halogen's reuse path is about five times
faster in absolute terms, and its cache covered a larger share of the prompt.

## Capabilities

Both engines retrieved a fact planted at 40 % and at 85 % of a 250K prompt, both emitted
a correctly-formed tool call with arguments, and both identified the colour in a generated
image. On these three probes there is no capability gap in the paths an agent uses.

At `xhigh` thinking effort on the same prompt, Halogen spent 60 reasoning tokens and
Kyojin 170. That is a difference in how much the template asks for, not a quality measure.

## The artifact the comparison started from

One request, no tools, no retry, the maintainer's own prompt, 16,384 output tokens allowed:

- **Halogen** wrote a complete document (4,785 tokens, `finish_reason: stop`), after a short
  prose preamble and inside a Markdown code fence. It loads three.js from two CDNs.
- **Kyojin** wrote 5,216 tokens, reported `finish_reason: stop`, and **stopped in the middle
  of a JavaScript function** with no closing tags. The page renders as a loading screen
  that never finishes. Its screenshot in `docs/shots/` is that loading screen.

An engine that reports a clean stop while the document is incomplete is worth reporting
regardless of whose engine it is: a caller cannot tell the difference between "done" and
"cut off" from the response alone.

On the bounded agent task (same harness, 8 turns / 600 s cap, the gallery's hexagon
prompt) both engines finished in 2 tool calls and both produced self-contained pages with
no external references — 41 s and 8.4 KB for Halogen, 70 s and 12.1 KB for Kyojin.

## Output checks

Thirteen cases whose answers a script decides: 11 passed on Halogen, 8 on Kyojin.

- **8 pass on both**, five of them with byte-identical output.
- **2 fail on both, identically**: a run-length encoder that cannot round-trip digits
  (`AbC123!` decodes to `AbC!!!!…` on both engines), and the JSON-shape case, where both
  report 16 vowels for a sentence that has 17 (`d-json-shape`). That is consistent with the
  pack, but it is a hypothesis from one run, not a measurement of the cause.
- **3 differ, all three wrong on Kyojin**: a bat-and-ball problem answered 0.10 instead of
  0.05, a painted-cube count answered 4 instead of 12, and a geometric sequence answered
  with the 11th term instead of the 10th.

With two packs of different precision, that split — identical on most, divergent on
arithmetic — is consistent with quantization loss, though one run cannot separate cause from
correlation; it is more informative than a single "quality score".

## Container experience

The parts a user meets before any number matters:

- **One cold start and one warm container restart were observed**: Kyojin took 561 s
  with an empty compile cache and a dropped OS page cache, then 43 s with the compile
  cache retained and the OS page cache not cleared. Each was measured once; these are
  not host-reboot timings or a guarantee of later startup times.
- **A missing `.env` produces a good error**: `required variable RENDER_GID is missing a
  value: Set RENDER_GID in .env`, exit 1. Nothing to improve.
- **The 32.6 GB n-gram/PLE table is the one real hazard.** Left to its automatic choice, the
  engine put that table in system RAM while the 89 GB pack was still loading, when
  `MemAvailable` did not yet include the weights. Weights plus table plus KV do not fit in
  128 GB together, and the host froze hard enough to need a reboot. `EXL3_NGRAM_STREAM=1`
  fixes it by forcing the table to stay file-backed, which is what the project's own
  reference loader does. Anyone running this image on 128 GB should set it explicitly
  rather than trust the inference.
- **Server arguments must be passed as environment variables.** The entrypoint does append
  its command line to the server invocation, but a `command:` that never reaches the
  container leaves the server on its defaults (65,536 tokens, vision off) and the only
  signal is one line in the log. Everything in this run goes through `CONTEXT` and
  `KYOJIN_EXTRA_ARGS` for that reason.
- Not tested: what happens when the published port is already taken. The probe could not be
  built without disturbing the running engine, so it is left untested rather than guessed
  at; it is not one of the three `not run` rows, which are Kyojin's in-flight counters.

## Pick this if

- **Long prompts, retrieval, big contexts, restarting often** → Halogen. It is 36 % faster to
  prefill throughput at 262K, returns the first token 27 % sooner there, and completes the observed warm container restart in 16 s
  instead of 43 s.
- **Many short turns with a repeated prefix** → either; both make reuse nearly free, and
  Halogen's is faster in absolute terms but neither is the bottleneck.
- **Four agents at once** → Halogen, on latency: the median request sees its first token in
  11.6 s against 23.0 s, and the 95th percentile (the maximum at four requests) is 19.1 s
  against 23.0 s. Output throughput at that point differs by only 34 %.
- **Decode speed in isolation** → neither, on this evidence.
- **A single-purpose server that also serves GLM and MiMo, with the option of an EXL3 pack
  and an uncensored mode** → Kyojin. That is not a speed argument, and this comparison does
  not test those models.

## What this comparison does not say

The two packs are different quantizations of the same model, so every speed number
describes engine *and* precision together. Kyojin was measured at the configuration
Halogen actually runs, not at its own defaults, which is unfair to Kyojin in one direction
(it pays for 262,144 positions and a vision tower it would not otherwise load) and
generous in another (it is judged as a daily driver, which is the only question I had).
No part of this is a statement that one engine is worse software.
