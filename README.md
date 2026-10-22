# Halogen vs Kyojin, one model, one machine

Two engines serving Qwen3.8-Flash-Next on a single AMD Strix Halo mini PC, measured
one at a time because they cannot both be resident. The question is narrow:

> The engine I run every day is Halogen. Can Kyojin replace it?

Everything below exists to answer that, and only that.

## Status

Original matrix complete, 2026-10-21: 111 measurements, 3 not run, 0 aborted, preserved at
tag [`snapshot-2026-10-21-v8`](https://github.com/kamjin3086/qwen-flash-engine-ab/tree/snapshot-2026-10-21-v8).
A separate **2026-10-22 pagoda follow-up** adds 12 bare outputs and one clean Pi SDK case
per engine, preserved at tag
[`snapshot-2026-10-22`](https://github.com/kamjin3086/qwen-flash-engine-ab/tree/snapshot-2026-10-22).
It does not replace or change those matrix rows. The comparison remains open-ended;
these observations are not a final migration decision.

- The report: [`docs/index.html`](docs/index.html) — one self-contained file, open it from
  disk, or read it live at <https://kamjin3086.github.io/qwen-flash-engine-ab/>.
- The analysis: [`results/findings.md`](results/findings.md) — what the numbers say, and
  what they do not.
- The summary everything else reads: [`results/summary.json`](results/summary.json), and the
  same rows flattened as [`results/measurements.csv`](results/measurements.csv).
- The generated Markdown report summary: [`results/issue-body.md`](results/issue-body.md).
- The pagoda follow-up: [`docs/pagoda-followup.html`](docs/pagoda-followup.html) — all bare
  samples, failures and agent finals, with static screenshots rather than live frames;
  [`results/pagoda-followup/protocol.md`](results/pagoda-followup/protocol.md) explains the
  method and exclusions, and its manifest verifies the curated requests, SSE and transcripts.

Reproduce the report from the raw records with `python3 report/build.py`. If it leaves the
tree unchanged — `git diff --exit-code` is empty — then every published surface still agrees
with the records it was built from. The tests that guard the generator ship with it:
`python3 -m unittest discover -s tests`. Three of them assert on the working repository's
private constants and are skipped here by design; the rest run against this tree.

## What the pagoda follow-up changes

The old incomplete Kyojin answer reproduced byte-for-byte with answer-phase loop-guard
metadata. It remains a real observation, not a general quality verdict. Both complete
setups produced viewable pages in a separate Pi SDK workflow. Bare output, repaired agent
output and agent termination are distinct outcomes; all samples are shown rather than a
best-of pair. Different packs/templates remain a limitation. Earlier follow-up timings
were affected by animated browser CPU load; only the labelled clean agent cases passed
per-request CPU gates, and their one-case costs are not an engine-speed ranking.

## What this is not

- **Not an engine shootout at stock defaults.** Kyojin's container ships 65536
  positions of context and no vision; measuring it there would say nothing about
  whether it can replace a server that runs 262144 with vision.
- **Not a model quality verdict.** The two engines load different quantizations of
  the same model. Output impressions are labelled as impressions.
- **Not a packaging review of Kyojin for everyone.** It is one user's daily
  workflow, on one machine, reported so the maintainer can act on it.

## Machine and versions

| | |
|---|---|
| Machine | AZW GTR Pro (Ryzen AI Max+ 395, 128 GB unified, gfx1151) — [firmware, memory and GPU as reported](docs/machine.md) |
| Kernel | 7.2.9-201.fc44.x86_64 |
| Halogen | `ghcr.io/peonist-ai/halogen-flash-server@sha256:2e98dc53…` (0.18.13) |
| Kyojin | `ghcr.io/yamz-labs/kyojin-qwen:1.6` `@sha256:a0c48fea…` (repo commit recorded in `runs/*/env.txt`) |

`AZW` is the DMI vendor string and `GTR Pro` the product string; every `runs/*/env.txt`
records the product as `machine GTR Pro`. The machine is sold as the **Beelink GTR9 Pro**;
the firmware strings are used here because they do not change with the marketing name.

## The reference configuration

Halogen's daily configuration is the yardstick and is not varied. Kyojin is raised
to meet it. The exact invocations, as executed, are in [`docs/commands.md`](docs/commands.md). See `docs/adr/0001-single-arm-halogen-as-yardstick.md` for why there is
no "fair" second arm.

| Dimension | Halogen (reference) | Kyojin (raised to meet it) |
|---|---|---|
| Context | `HALOGEN_CTX=262144` | `-c 262144` |
| Parallel requests | `HALOGEN_KV_SLOTS=4` over one 262144 pool | `--sessions 4` over one `-c` pool; `--sessions 1` for deterministic runs |
| Reply budget | `HALOGEN_MAX_TOK=16384` | `--default-max-tokens 16384` |
| Vision | on | on (no `--no-vision`) |
| Speculative decoding | MTP drafter, default | `--draft-policy mix`, `--ndt 7`, default |
| Prompt cache | on, 2.7 GiB of RAM | engine default |
| Sampling | greedy at temperature 0 | greedy at temperature 0 |
| Thinking, speed runs | `enable_thinking: false` | `enable_thinking: false` |
| Thinking, one sample | `--reasoning_effort xhigh` | `--default-reasoning-effort xhigh` |

### Variables that cannot be aligned, and are disclosed instead

- **Pack.** Halogen loads a 62.1 GiB `.hgn` checkpoint whose lookup table is read
  from disk; Kyojin loads an EXL3 4.0 bpw pack (89 GiB on disk, vision and MTP
  towers at 6 bits). Speed figures therefore describe engine **and** quantization.
- **Chat template.** Halogen runs a local custom template; Kyojin runs the template
  shipped in its image. Both are greedy, so this affects the shape of the answer,
  not its sampling.
- **Concurrency cost.** Kyojin's `--sessions N` is not free: above one session the
  decode attention kernel splits differently, and the server itself warns that
  greedy output is no longer guaranteed to match a solo run, and that
  `sessions × (ndt + 1) > 8` costs decode throughput. Halogen runs four slots and
  its MTP drafter at the same time. That difference is a finding, not a setting.

## Measurement matrix

| # | Measurement | How | Both engines |
|---|---|---|---|
| 1 | Cold start and warm start to `/v1/models` | `bench.sh` wall clock | yes |
| 2 | Prefill and decode at the author's sizes | upstream `bench.py`, same corpus | yes |
| 3 | Prefill and TTFT at 32K / 128K / 262144 | `kbench.py ctx` | yes |
| 4 | Two facts at 40 % and 85 % of ~250K | `kbench.py needle` | yes |
| 5 | One tool call | `kbench.py tool` | yes |
| 6 | N-way concurrency, 8K prompt, 512 out, N = 1 and 4 | `kbench.py conc` | yes, see caveat below |
| 7 | One thinking-on sample at `xhigh` | one request | yes |
| 8 | One-shot artifact: the gallery's voxel-pagoda prompt, one HTML file, no tools | manual, rendered and screenshotted | yes |
| 9 | Bounded agent run: the gallery's hexagon prompt, 8 turns / 600 s cap, `tools/agentrun.py` | `bench.sh` + manual | yes |
| 10 | Container experience: cache survives restart, missing `.env` error text, port already in use | manual | Kyojin only |

For measurement 6, N is the number of simultaneous client requests, not the server's
session capacity. Kyojin's N = 1 and N = 4 concurrency measurements both come from the
`--sessions 4` phase (`runs/kyojin-s4/conc1.json` and `conc4.json`). The deterministic
measurements use a separate `--sessions 1` phase. Halogen needs no such split.

## Run order

To do this on another machine, start with [`docs/replicate.md`](docs/replicate.md).

1. `./bench.sh preflight` — record environment, digests, GTT, availability.
2. `./bench.sh smoke` — tooling check at tiny sizes against the engine that is up.
3. `./bench.sh halogen --clear-cache "$HALOGEN_DIR/cache"` — phase A, explicitly
   authorize clearing the reference engine's compile-cache contents for first-start timing;
   see the cache safety requirements in [`docs/replicate.md`](docs/replicate.md).
4. `./bench.sh kyojin-s1` — phase B: stop Halogen, Kyojin cold start, deterministic
   matrix, artifacts 8 and 9.
5. `./bench.sh kyojin-s4` — phase C: warm restart with `--sessions 4`, measurement 6.
6. `./bench.sh variance <label>` — repeat the numbers the verdict leans on, while that
   engine is up: three passes of prefill/TTFT at 32K/128K/262K and three N=4 runs. This is
   what the Variance table is built from; use the same session count as the phase being
   repeated.
7. `./bench.sh restore` — phase D: stop Kyojin, bring Halogen back, verify it answers.

## What the run required, and why

Four things were not obvious from the Kyojin container guide and cost time to find. They
are recorded here because the next person measuring this image will hit them too.

- **The n-gram/PLE table must be forced to disk.** `EXL3_NGRAM_STREAM=1`. Left unset, the
  engine decides by comparing available memory against table size plus 48 GiB, but it
  decides *while the 89 GB pack is still loading*, when `MemAvailable` does not yet
  include the weights. It chose RAM, and the host froze hard enough that it had to be
  rebooted. See `runs/_incident-freeze/`.
- **Server settings go through environment variables**, not a compose `command:`. The
  entrypoint does append its command line to the server invocation, but a `command:` that
  never reaches the container leaves the server on its defaults (65,536 tokens, vision
  off) and the only signal is one line in the log.
- **Pins belong on digests, not tags.** The compose file this work started from asked for
  `1.5.2`, which the registry never published. The newest published image is `1.6.0`,
  also tagged `latest` and `1.6`.
- **A cold start means a cold page cache.** `sync` + `drop_caches` before timing, or the
  "cold" start is served from RAM. Both engines are timed that way here.

## Abort rules

- **A1** Halogen not healthy within 15 minutes of the restore: stop everything,
  report, do not keep trying.
- **A2** GTT not released after stopping Halogen (more than 2 GiB still held): do
  **not** start Kyojin. Report. A reboot is the only known remedy and is not
  authorised.
- **A3** Kyojin out of memory at 262144: drop to 131072 once, record the drop as a
  finding, do not retry further.
- **A4** Any OOM kill that reaches a service outside the two engines: abort and
  restore Halogen immediately.

Never: `docker compose down -v`, deleting models, deleting cache directories, or editing
an existing compose file. The only cache-content deletion permitted by the runner is an
explicitly authorized Halogen first-start measurement using `--clear-cache` with the exact
absolute project/cache path. The runner checks both the resolved Compose mount and the
existing container's actual mount, requires the container to be stopped before deletion,
and aborts on cleanup failure. Without that option it refuses before touching the service.
OS page-cache dropping is a separate step. Kyojin overrides go in a separate override file.

## Publication

- A **generated public export** (`qwen-flash-engine-ab`), produced from the private
  working repository by an allowlist copy with a path, account and container-name check —
  never a history mirror. See
  `docs/adr/0003-private-work-public-export.md`. Contents: scripts, scrubbed raw
  JSON, logs, screenshots, method, and the two licenses below.
- One `benchmark_report` issue in the Kyojin repository: the numbers, the machine,
  the exact server command, and the notes the template asks for.
- Separate `bug_report` issues, only for defects found by measurement 10.
- A short reply in the Reddit thread linking both.

The task prompts for measurement 8 and 9 are the ones published in the author's
gallery, quoted verbatim in `docs/artifacts.md`.

## AI assistance

This comparison was carried out with AI assistance across test planning, scripting,
execution troubleshooting, analysis, and writing. AI assistance is not independent
validation: the published raw records and reproducible report are the basis for checking
the claims. The author is responsible for what is published; this disclosure does not
imply that every record has been independently checked by a human.

## License

- Code — `bench.sh`, `report/`, `tools/` — is MIT: [`LICENSE`](LICENSE).
- Measurements, prose and the artifact pages are CC-BY-4.0:
  [`LICENSE-CC-BY-4.0`](LICENSE-CC-BY-4.0).

Neither engine image is redistributed here; each carries its own license.
