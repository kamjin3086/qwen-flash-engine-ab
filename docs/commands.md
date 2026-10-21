# The two invocations

What was actually executed, as the containers saw it. The record is the resolved compose
file from each phase — [`runs/halogen/compose.resolved.yml`](../runs/halogen/compose.resolved.yml)
and [`runs/kyojin-s1/compose.resolved.yml`](../runs/kyojin-s1/compose.resolved.yml) — and
the blocks below are transcriptions of them, with host directories left as variables.

Both engines are started with `docker compose up -d` from their own project directory and
stopped with `docker compose stop`. **Never `down -v`**: that deletes the cache volume, which
is the difference between a 16 s and a 561 s start.

## Halogen — the reference configuration

Image `ghcr.io/peonist-ai/halogen-flash-server@sha256:2e98dc53ed4a…` (0.18.13).
These are its daily settings; nothing here was varied.

```sh
docker run --rm --name halogen-flash-server-halogen-1 \
  --device /dev/kfd --device /dev/dri --device /dev/accel/accel0 \
  --group-add 39 --group-add 105 --ipc host --ulimit memlock=-1 \
  -e HALOGEN_CTX=262144 \
  -e HALOGEN_KV_POOL_POSITIONS=262144 \
  -e HALOGEN_KV_SLOTS=4 \
  -e HALOGEN_MAX_TOK=16384 \
  -e HALOGEN_VISION_TOWER=1 \
  -e HALOGEN_PROMPT_CACHE=2 \
  -e HALOGEN_CHAT_TEMPLATE=/templates/qwen-sharp-v22.5.0.jinja \
  -e HALOGEN_CACHE_DIR=/cache \
  -e HALOGEN_CACHE_DISK_GIB=64 \
  -e HALOGEN_CACHE_PRUNE_OLD=1 \
  -e HALOGEN_ENGINE_WATCHDOG_S=600 \
  -e HALOGEN_NPU_MODELS=flux2-klein-4b \
  -v "$MODELS":/models -v "$CACHE":/cache -v "$TEMPLATES":/templates:ro \
  -v /opt/xilinx/xrt:/opt/xilinx/xrt:ro \
  -p 127.0.0.1:8731:8731 \
  ghcr.io/peonist-ai/halogen-flash-server@sha256:2e98dc53ed4a43b5600b11a80852eedfa573f4ffc3f10c64da01245f2a3217fc
```

`$MODELS` holds the `.hgn` checkpoint, its lookup table and the vision tower; `$CACHE` is the
compile/tuning cache that must survive restarts; `$TEMPLATES` holds the local chat template.
The NPU device is passed for the image's own text-to-image engine, which this comparison does
not measure.

The healthcheck is the image's own (`/usr/local/bin/halogen-healthcheck auto`), 20 min start
period, 10 s interval. `bench.sh` waits on that, not on a sleep.

## Kyojin — raised to the same configuration

Image `ghcr.io/yamz-labs/kyojin-qwen@sha256:a0c48fea49a6…` (1.6).

```sh
docker run --rm --name kyojin-qwen-trial \
  --device /dev/kfd --device /dev/dri \
  --group-add 39 --group-add 105 --ipc host --ulimit memlock=-1 \
  -e CONTEXT=262144 \
  -e KYOJIN_ENABLE_VISION=1 \
  -e KYOJIN_ENABLE_UNCENSOR=0 \
  -e KYOJIN_MODEL_ID=kyojin-qwen38 \
  -e KYOJIN_DOWNLOAD=1 \
  -e KYOJIN_CACHE_DIR=/root/.cache \
  -e EXL3_NGRAM_STREAM=1 \
  -e KYOJIN_EXTRA_ARGS="--sessions 1 --default-max-tokens 16384 --default-reasoning-effort xhigh" \
  -v "$MODELS":/models -v "$CACHE":/root/.cache \
  -p 127.0.0.1:8732:8731 \
  ghcr.io/yamz-labs/kyojin-qwen@sha256:a0c48fea49a605da3e5eaeee4fcd82aa5a8591063976bbbbbca7c2c4f9c20b51
```

What is overridden, and why:

| Setting | Container default | Used here | Reason |
|---|---|---|---|
| Context | 65536 | `CONTEXT=262144` | match the server being replaced |
| Vision | off | `KYOJIN_ENABLE_VISION=1` | match the reference server |
| Reply budget | engine default | `--default-max-tokens 16384` | match the reference server |
| Reasoning effort | engine default | `--default-reasoning-effort xhigh` | one thinking sample only |
| Sessions | 1 | `--sessions 1`, and `4` for the concurrency phase | see ADR-0002 |
| Table placement | engine auto | `EXL3_NGRAM_STREAM=1` | forced after `runs/_incident-freeze/` |
| Uncensored mode | off | `KYOJIN_ENABLE_UNCENSOR=0` | not part of the question |

Two things that bite here, both recorded in the README:

- **Settings go through environment variables, not a compose `command:`.** A `command:` that
  does not reach the container leaves the server on 65536 positions and vision off, and the
  only signal is one line in the log.
- **The image tag is not the image.** The compose file this work started from asked for
  `1.5.2`, which the registry never published. The run is pinned by digest, and
  `runs/*/env.txt` records both the digest and the local tag it resolved from.

For the concurrency phase the same command is used with `--sessions 4`; everything else is
identical. The two phases are kept apart because the session count changes the decode
scheduling, not just the queue depth.
