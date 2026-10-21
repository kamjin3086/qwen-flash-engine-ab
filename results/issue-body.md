## What this is

One machine, one model, two engines, measured one at a time. Kyojin was raised from the container's defaults to the configuration Halogen actually runs (full context, vision on, the same reply budget), so these numbers describe Kyojin as a daily driver, not at stock settings.

- Halogen: `ghcr.io/peonist-ai/halogen-flash-server@sha256:2e98dc53ed4a43b5600b11a80852eedfa573f4ffc3f10c64da01245f2a3217fc`
- Kyojin: `ghcr.io/yamz-labs/kyojin-qwen@sha256:a0c48fea49a605da3e5eaeee4fcd82aa5a8591063976bbbbbca7c2c4f9c20b51`
- Machine: AZW GTR Pro (Beelink GTR9 Pro), Ryzen AI Max+ 395, 128 GB unified (gfx1151), Fedora 44, kernel 7.2.9.

## Numbers

| Measurement | Condition | Halogen | Kyojin | Phase (H / K) |
|---|---|---|---|---|
| Prefill | bench.py method | 1,601 | 1,251 | halogen / kyojin-s1 |
| Prefill | prompt ~32K | 1,851 | 1,350 | halogen / kyojin-s1 |
| Prefill | prompt ~128K | 1,796 | 1,309 | halogen / kyojin-s1 |
| Prefill | prompt ~262K | 1,707 | 1,259 | halogen / kyojin-s1 |
| Prompt tokens | bench.py method | 2,737 | 3,110 | halogen / kyojin-s1 |
| Prompt tokens | prompt ~32K | 30,790 | 31,209 | halogen / kyojin-s1 |
| Prompt tokens | prompt ~128K | 122,456 | 124,817 | halogen / kyojin-s1 |
| Prompt tokens | prompt ~262K | 250,549 | 255,600 | halogen / kyojin-s1 |
| Decode | decode chat | 53.6 | 50.9 | halogen / kyojin-s1 |
| Decode | decode code | 60.8 | 56.8 | halogen / kyojin-s1 |
| Decode | decode prose | 49.5 | 53.4 | halogen / kyojin-s1 |
| Time to first token | prompt ~32K | 16.7 | 23.3 | halogen / kyojin-s1 |
| Time to first token | prompt ~128K | 68.5 | 95.8 | halogen / kyojin-s1 |
| Time to first token | prompt ~262K | 148 | 204 | halogen / kyojin-s1 |
| Fact retrieved at depth | fact at 40% of 250K | yes | yes | halogen / kyojin-s1 |
| Fact retrieved at depth | fact at 85% of 250K | yes | yes | halogen / kyojin-s1 |
| Tool call emitted | single tool call | yes | yes | halogen / kyojin-s1 |
| Tool call carries arguments | single tool call | yes | yes | halogen / kyojin-s1 |
| Image input understood | generated PNG | yes | yes | halogen / kyojin-s1 |
| Thinking tokens at xhigh | effort xhigh | 60 | 170 | halogen / kyojin-s1 |
| Aggregate decode, all requests | N=1 | 35.1 | 28.4 | halogen / kyojin-s4 |
| Aggregate decode, all requests | N=2 | 38.2 | 31.0 | halogen-extra / kyojin-extra |
| Aggregate decode, all requests | N=4 | 42.4 | 31.6 | halogen / kyojin-s4 |
| Decode per request (median) | N=1 | 60.8 | 53.4 | halogen / kyojin-s4 |
| Decode per request (median) | N=2 | 31.2 | 31.4 | halogen-extra / kyojin-extra |
| Decode per request (median) | N=4 | 16.6 | 16.3 | halogen / kyojin-s4 |
| First token, median across requests | N=1 | 4.27 | 5.76 | halogen / kyojin-s4 |
| First token, median across requests | N=2 | 6.82 | 11.5 | halogen-extra / kyojin-extra |
| First token, median across requests | N=4 | 11.6 | 23.0 | halogen / kyojin-s4 |
| First token, 95th percentile | N=1 | 4.27 | 5.76 | halogen / kyojin-s4 |
| First token, 95th percentile | N=2 | 9.24 | 11.5 | halogen-extra / kyojin-extra |
| First token, 95th percentile | N=4 | 19.1 | 23.0 | halogen / kyojin-s4 |
| Requests actually in flight | N=1 | 1 | _not run_ | halogen / kyojin-s4 |
| Requests actually in flight | N=2 | 2 | _not run_ | halogen-extra / kyojin-extra |
| Requests actually in flight | N=4 | 4 | _not run_ | halogen / kyojin-s4 |
| Prompt tokens served from cache | same prefix again | 95,680 | 94,208 | halogen-extra / kyojin-extra |
| First token, repeated prefix | same prefix again | 0.58 | 2.96 | halogen-extra / kyojin-extra |
| First token, cold prefix | cold control | 53.5 | 74.9 | halogen-extra / kyojin-extra |
| Time to a usable server | first start | 37 | 561 | halogen / kyojin-s1 |
| Time to a usable server | warm start | 16 | 43 | halogen / kyojin-s4 |
| Pagoda output tokens | pagoda one-shot | 4,785 | 5,216 | halogen / kyojin-s1 |
| Pagoda output truncated | pagoda one-shot | no | no | halogen / kyojin-s1 |
| Pagoda output is complete HTML | pagoda one-shot | yes | no | halogen / kyojin-s1 |
| Script-checkable case | c-csv-line | yes | yes | halogen-quality / kyojin-quality |
| Script-checkable case | c-iso-duration | yes | yes | halogen-quality / kyojin-quality |
| Script-checkable case | c-rle-roundtrip | no | no | halogen-quality / kyojin-quality |
| Script-checkable case | d-bullets-haiku | yes | yes | halogen-quality / kyojin-quality |
| Script-checkable case | d-json-shape | no | no | halogen-quality / kyojin-quality |
| Script-checkable case | r-arrival-time | yes | yes | halogen-quality / kyojin-quality |
| Script-checkable case | r-bat-ball | yes | no | halogen-quality / kyojin-quality |
| Script-checkable case | r-geometric | yes | no | halogen-quality / kyojin-quality |
| Script-checkable case | r-painted-cube | yes | no | halogen-quality / kyojin-quality |
| Script-checkable case | r-sum-not-div3 | yes | yes | halogen-quality / kyojin-quality |
| Script-checkable case | r-three-items | yes | yes | halogen-quality / kyojin-quality |
| Script-checkable case | r-trailing-zeros | yes | yes | halogen-quality / kyojin-quality |
| Script-checkable case | r-widgets | yes | yes | halogen-quality / kyojin-quality |
| Script-checkable cases passed | all 13 cases | 85% | 62% | halogen-quality / kyojin-quality |

_Kyojin's /health answers, but publishes no in-flight or queued counters, so request occupancy cannot be observed on that engine._

## Repetitions

| Measurement | Condition | Engine | n | Median | Range |
|---|---|---|---:|---:|---:|
| Prefill | bench.py method | Halogen | 3 | 1,601 | 1,563–1,663 |
| Prefill | bench.py method | Kyojin | 3 | 1,251 | 1,226–1,309 |
| Decode | decode chat | Halogen | 3 | 53.6 | 51.1–54.7 |
| Decode | decode chat | Kyojin | 3 | 50.9 | 50.3–51.9 |
| Decode | decode code | Halogen | 3 | 60.8 | 60.5–61.6 |
| Decode | decode code | Kyojin | 3 | 56.8 | 53–57.8 |
| Decode | decode prose | Halogen | 3 | 49.5 | 47.4–49.6 |
| Decode | decode prose | Kyojin | 3 | 53.4 | 52.6–54.6 |

- Halogen, pagoda: https://github.com/kamjin3086/qwen-flash-engine-ab/blob/main/docs/artifacts/halogen-pagoda.html (`sha256:7e2e0cae24db`)
- Halogen, hexagon: https://github.com/kamjin3086/qwen-flash-engine-ab/blob/main/docs/artifacts/halogen-hexagon.html (`sha256:ba64ac847a1c`)
- Kyojin, pagoda: https://github.com/kamjin3086/qwen-flash-engine-ab/blob/main/docs/artifacts/kyojin-pagoda.html (`sha256:f8cfbfff99b2`)
- Kyojin, hexagon: https://github.com/kamjin3086/qwen-flash-engine-ab/blob/main/docs/artifacts/kyojin-hexagon.html (`sha256:e5b933595f9f`)

## What the numbers say

# What the numbers say

**One sentence:** on this machine, with these two packs, Kyojin is not slower at decoding
than the engine I already run — but it is 28–37 % slower at prefill, 2.7× slower to come
back after a reboot, and it produced an incomplete page on the task the comparison was
originally about. If the question is "should I switch my daily driver", the answer here
is no; if the question is "is the EXL3 route competitive", the decode numbers say yes.

Everything below is a value from the tables above. Nothing here is a judgement of the
model, only of what came out of each engine.

**How many times each number was measured.** Prefill and decode at the author's sizes are
the median of three runs. Everything else is one observation: the 32K / 128K / 262K prefill
and first-token figures, both retrieval depths, the tool call, the concurrency rows, the two
prefix requests, the two starts, and the artifacts were each measured once. One observation
on one machine is enough to say *this is how it behaved here*; it is not a distribution. The
prefill ratio is quoted because it holds across four prompt sizes, not because it was
repeated.

## Where the two engines actually differ

**Prefill is the real gap, and it is uniform.** Halogen is faster at every context length
I measured, and the ratio barely moves (1.28× at ~2.7K, 1.36–1.37× from 32K to 262K). Both
engines lose about the same share of their speed as the prompt grows (−7.7 % and −6.8 %
from 32K to 262K), so this is not a long-context effect: it is a constant factor on
forward pass throughput.

**Decode is a tie.** 49.5 / 53.6 / 60.8 tok/s against 53.4 / 50.9 / 56.8 across prose,
chat and code. The two engines trade the lead per prompt class and the spread between
classes inside one engine is larger than the spread between engines. Anyone quoting a
single decode number from this comparison is quoting noise.

The three runs behind each prefill and decode figure are in the *Repetitions* table on the
page, and they make that statement precise: the prefill ranges do not overlap, so the gap
there is not noise; the decode ranges overlap on chat and separate on prose and code, in
opposite directions. The ordering depends on the prompt class more than on the engine.

**Time to first token at 250K** follows the prefill gap: 148 s against 204 s.

**Startup is the largest single difference in the whole comparison.** 37 s against 561 s
on a first start after clearing caches, and 16 s against 43 s on a warm start. The first
number is what a new user meets; the second is what an existing user meets every reboot.

## Parallel requests buy latency isolation, not throughput

Four 8K-prompt, 512-token requests released at once:

| | wall | aggregate | per request | first token (median) |
|---|---:|---:|---:|---:|
| Halogen, 1 request | 10.1 s | 35.1 tok/s | 60.8 tok/s | 4.3 s |
| Halogen, 4 requests | 33.4 s | 42.4 tok/s | 16.6 tok/s | 11.6 s |
| Kyojin, 1 request | 12.3 s | 28.5 tok/s | 53.4 tok/s | 5.8 s |
| Kyojin, 4 requests | 45.6 s | 31.6 tok/s | 16.3 tok/s | 23.0 s |

Quadrupling the requests buys 21 % more aggregate throughput on Halogen and 11 % on
Kyojin, while per-request speed falls by two thirds. Both engines are limited by the same
thing at that point. The difference that matters for a user running four agents is not
throughput but **how long the fourth request waits for its first token**: 11.6 s against
23.0 s.

Kyojin's own startup log names the reason its parallel mode is not free, and it is right
to warn: at four sessions its decode attention kernel splits differently and its output
is no longer guaranteed to equal a solo run.

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
image. On this evidence there is no capability gap in the paths an agent uses.

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
  (`AbC123!` decodes to `AbC!!!!…` on both engines) and a vowel count that both report as
  16 where the sentence has 17. These are properties of the pack, not of the engine.
- **3 differ, all three wrong on Kyojin**: a bat-and-ball problem answered 0.10 instead of
  0.05, a painted-cube count answered 4 instead of 12, and a geometric sequence answered
  with the 11th term instead of the 10th.

With two packs of different precision, that split — identical on most, divergent on
arithmetic — is the shape you would expect from quantization loss, and it is far more
informative than a single "quality score".

## Container experience

The parts a user meets before any number matters:

- **Cold then warm start works as documented**: 561 s once, 43 s afterwards, as long as the
  cache volume survives. The cache is the difference between a usable and an unusable
  everyday engine.
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
  built without disturbing the running engine, so it is recorded as not run rather than
  guessed at.

## Pick this if

- **Long prompts, retrieval, big contexts, restarting often** → Halogen. It is 36 % faster to
  prefill at 256K, 27 % quicker to first token there, and comes back from a reboot in 16 s
  instead of 43 s.
- **Many short turns with a repeated prefix** → either; both make reuse nearly free, and
  Halogen's is faster in absolute terms but neither is the bottleneck.
- **Four agents at once** → Halogen, on latency: the fourth request sees its first token in
  11.6 s against 23.0 s. Throughput at that point differs by only 34 %.
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

## Everything else

Method, raw JSON, logs, the exact compose files and the artifact pages: https://github.com/kamjin3086/qwen-flash-engine-ab

_The two packs are different quantizations of the same model, so speed figures describe engine and quantization together. The output checks decide usability, not quality._
