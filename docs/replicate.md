# Replicating this on another machine

The shortest honest path from a similar box to a table you can compare with this one. It is
written for someone who has never opened this repository.

## What you need

- **One machine that can hold either pack, one engine at a time, at 262144 positions.**
  This run used 124 GiB of unified memory and a 1.8 TB SSD; both packs together do not fit
  (89 GB of EXL3 weights, a 62.1 GiB `.hgn` checkpoint, and a ~30 GiB lookup table).
- **Docker with ROCm device passthrough** (`/dev/kfd`, `/dev/dri`) and enough disk for both
  packs plus caches.
- **A compose project per engine.** `bench.sh` expects two directories in environment
  variables — `HALOGEN_DIR` and `KYOJIN_DIR` — each with its own compose file; Kyojin needs
  the `--sessions 1` and `--sessions 4` overlays as well. The two invocations, as executed,
  are in [`commands.md`](commands.md); the host paths in the resolved files are this author's.
- **Time.** About two hours of engine time end to end (first start to restore), plus the
  failed attempts, plus a reboot if the lookup table is allowed into system RAM. Budget
  three hours and do not plan to use the machine meanwhile.

## Cache safety before first-start timing

Set `HALOGEN_DIR` to the absolute Compose project directory. The Halogen first-start
command below **deletes all contents, including dotfiles, of its compile cache**; it is
not a routine restart. Back up anything you need before authorizing it. The directory must
be exactly `$HALOGEN_DIR/cache`, with no symlink, and the resolved Compose configuration
must explicitly set `HALOGEN_CACHE_DIR=/cache`. An existing container is required so the
runner can verify that its actual bind mount agrees with Compose. Unsupported or
ambiguous layouts are refused, not guessed.

Without `--clear-cache` the runner refuses before stopping any service. With authorization
it displays the target, verifies mounts, stops the container, verifies again, and clears
only that directory's contents. Any stop or cleanup failure aborts before timing. Do not
change mounts or start the container concurrently. Dropping the OS page cache is a separate
operation requiring non-interactive sudo; it does not clear the compile cache. The warm
restart later retains both compile caches and the OS page cache; it does not reboot the host.

## Steps

```sh
./bench.sh setup        # vendor the upstream bench tool at the pinned commit
./bench.sh preflight    # digests, GTT baseline, availability; writes runs/preflight/
./bench.sh smoke        # tiny sizes against whichever engine is up
./bench.sh halogen --clear-cache "$HALOGEN_DIR/cache" # phase A: authorize cache-content deletion
./bench.sh kyojin-s1    # phase B: stop Halogen, cold start Kyojin at --sessions 1
./bench.sh kyojin-s4    # phase C: warm restart at --sessions 4, concurrency arm
./bench.sh variance <label>  # optional: repeat the verdict's numbers, engine up
./bench.sh restore      # phase D: Halogen back, answering
python3 report/build.py # summary, page, issue body, export
```

`bench.sh` writes `runs/<phase>/` and appends to `runs/session.log`, which is how the report
found every number. `./bench.sh variance <label>` repeats the numbers the verdict leans on
(three passes of prefill and first-token latency at 32K/128K/262K, and three N=4 runs) while
that engine is up; it uses whatever session count is running, so repeat the configuration you
mean to repeat. Read the abort rules in the [README](../README.md#abort-rules) before you
start; two of them exist because this hardware can be left unusable, and they bite at the
swap between engines and after a failed start.

## The four things that cost time here

1. **Force the n-gram/PLE table to disk.** `EXL3_NGRAM_STREAM=1`. Left to its own choice the
   engine can put a 30 GiB table in RAM while an 89 GB pack is still loading; on this box that
   ended in a hard freeze (`runs/_incident-freeze/`).
2. **Settings go through environment variables, not a compose `command:`.** A `command:` that
   does not reach the container leaves the server at 65536 positions with vision off.
3. **Pin images by digest.** The tag this work started from did not exist in the registry; the
   digest is the only stable identity, and `runs/*/env.txt` records it.
4. **A cold start means a cold page cache.** `sync` + `drop_caches` before timing, or the
   "cold" start is served from RAM.

## What will legitimately differ

- **The numbers.** Different pack, different driver, different board cooling.
- **The conclusion, if your quantization differs.** Every speed figure describes engine *and*
  precision together; that caveat is in the report's scope block and it applies to your run
  too.
- **The startup cost**, which is mostly kernel compilation and the image's cache. It is the
  number most sensitive to a first run on new hardware.

What should be comparable is the *shape*: prefill is a constant factor rather than a
long-context effect, decode is a tie within the noise, and the cost of going parallel shows up
in median and p95 first-token latency, not just aggregate throughput. If your run disagrees with that
shape, that is the interesting result.

## What is not automated

Measurement 8 and 9 (one-shot and bounded agent artifacts) need a browser and a screenshot;
measurement 10 (container experience) is a person writing down what happened. The prompts are
in [`artifacts.md`](artifacts.md), the rest is judgement.

## How many times each number was measured

See the top of the [findings](../results/findings.md) and the Repetitions and Variance
tables on the [report](../docs/index.html). Prefill and decode at the author's sizes and the
newly repeated points (32K/128K/262K prefill and TTFT, N=4) have three observations; startup
and the artifacts are single observations. Reproduce with the same sample sizes or state
yours.
