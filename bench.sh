#!/usr/bin/env bash
# One engine at a time, in phases. Nothing here is destructive to models or caches it
# is not explicitly asked to clear: no `down -v`, no deletion of models/, no edit of an
# existing compose file.
#
#   ./bench.sh setup        # vendor the upstream bench tool at a pinned commit
#   ./bench.sh preflight    # environment, digests, GTT, availability
#   ./bench.sh smoke        # tooling check at tiny sizes against the engine already up
#   ./bench.sh halogen      # H1 first start (caches cleared, page cache dropped) + matrix
#                           #   + artifacts + concurrency, then H2 warm start timing
#   ./bench.sh kyojin-s1    # K1 first start (sessions=1) + deterministic matrix + artifacts
#   ./bench.sh kyojin-s4    # K2 warm start (sessions=4) + concurrency arm
#   ./bench.sh status       # where the run is, without reading logs
#   ./bench.sh extras LABEL # repeated-prefix cost + concurrency N=2, on whatever is up
#   ./bench.sh variance LABEL # 3 reps of prefill/TTFT at 32K/128K/262K and N=4, engine up
#   ./bench.sh restore      # back to Halogen, verified answering
#
# Every phase writes runs/<phase>/ and appends to runs/session.log.
set -Eeuo pipefail

HALOGEN_DIR="${HALOGEN_DIR:-$HOME/apps/halogen-flash-server}"
KYOJIN_DIR="${KYOJIN_DIR:-$HOME/apps/kyojin-compose-starter}"
HALOGEN_URL="${HALOGEN_URL:-http://127.0.0.1:8731}"
KYOJIN_URL="${KYOJIN_URL:-http://127.0.0.1:8732}"
HALOGEN_NAME=halogen-flash-server-halogen-1
KYOJIN_NAME=kyojin-qwen-trial
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
KYOJIN_S1=(-f compose.yaml -f docker-compose.s1.yml)
KYOJIN_S4=(-f compose.yaml -f docker-compose.s4.yml)
PY="${PYTHON:-python3}"
KB="$ROOT/tools/kbench.py"
ARTIFACT_MAX_TOKENS=16384

log()  { printf '%s %s\n' "$(date -Is)" "$*" | tee -a "$ROOT/runs/session.log"; }
die()  { log "ABORT: $*"; exit 1; }
phase_dir() { local d="$ROOT/runs/$1"; mkdir -p "$d"; echo "$d"; }

HALOGEN_DIGEST="${HALOGEN_DIGEST:-}"
KYOJIN_DIGEST="${KYOJIN_DIGEST:-}"
resolve_digests() {
  HALOGEN_DIGEST=$(docker image inspect ghcr.io/peonist-ai/halogen-flash-server:0.18.13 \
    --format '{{index .RepoDigests 0}}' 2>/dev/null || echo unknown)
  KYOJIN_DIGEST=$(grep -h 'image: ghcr.io/yamz-labs/kyojin-qwen@' "$KYOJIN_DIR"/docker-compose.s1.yml 2>/dev/null \
    | head -1 | sed 's/^ *image: //')
  KYOJIN_DIGEST="${KYOJIN_DIGEST:-unknown}"
}
digest_for() { case "$1" in *8731*) echo "$HALOGEN_DIGEST" ;; *) echo "$KYOJIN_DIGEST" ;; esac; }

avail_gib() { awk '/MemAvailable/ {printf "%d", $2/1024/1024}' /proc/meminfo; }
gtt_mib() {
  local total=0 f v
  for f in /sys/class/drm/card*/device/mem_info_gtt_used; do
    [ -r "$f" ] || continue
    v=$(cat "$f" 2>/dev/null || echo 0); total=$(( total + v / 1024 / 1024 ))
  done
  echo "$total"
}
gtt_floor_mib() {
  # A desktop on this iGPU holds several GiB of GTT by itself, so an absolute threshold
  # false-fires. The floor is the baseline recorded at preflight plus a margin.
  local base_file="$ROOT/runs/preflight/gtt-baseline.txt" base=0
  [ -f "$base_file" ] && base=$(cat "$base_file")
  echo $(( base + 4096 ))
}
host_snapshot() { # dir, tag
  local d="$1" tag="$2"
  { echo "# docker stats"; docker stats --no-stream \
      --format 'table {{.Name}}\t{{.MemUsage}}\t{{.MemPerc}}' 2>&1 | head -20
    echo "# gtt_mib $(gtt_mib)"
    echo "# avail_gib $(avail_gib)"
    echo "# free"; free -g; } > "$d/$tag.txt" 2>&1
}
drop_page_cache() { # dir, tag
  local d="$1" tag="$2"
  sync
  sudo -n sh -c 'sync; echo 3 > /proc/sys/vm/drop_caches' 2>/dev/null \
    || die "A5: cannot drop page cache; a cold start would not be cold"
  sleep 2
  { echo "dropped at $(date -Is)"; echo "avail_gib $(avail_gib)"; echo "gtt_mib $(gtt_mib)"; } > "$d/drop-$tag.txt"
  log "page cache dropped ($tag), avail $(avail_gib)GiB"
}
WATCHDOG_PID=""
WATCHDOG_FLOOR_GIB="${WATCHDOG_FLOOR_GIB:-10}"
start_watchdog() { # dir — kills the engine if the host runs out of memory, so a bad
  local d="$1" sentinel="$1/.watchdog-stop" a            # configuration cannot freeze the desktop
  rm -f "$sentinel"
  ( while [ ! -f "$sentinel" ]; do
      a=$(awk '/MemAvailable/ {printf "%d", $2/1024/1024}' /proc/meminfo)
      if [ "${a:-999}" -lt "$WATCHDOG_FLOOR_GIB" ]; then
        { echo "WATCHDOG $(date -Is): MemAvailable ${a}GiB < ${WATCHDOG_FLOOR_GIB}GiB"
          echo "killing the engines to protect the host"
          docker kill "$KYOJIN_NAME" 2>&1
          docker kill "$HALOGEN_NAME" 2>&1
          echo "done"; } >> "$d/WATCHDOG-KILL.txt"
        exit 9
      fi
      sleep 2
    done ) &
  WATCHDOG_PID=$!
  log "watchdog armed: kills the engine below ${WATCHDOG_FLOOR_GIB}GiB available (pid $WATCHDOG_PID)"
}
stop_watchdog() { # dir
  local d="$1"
  if [ -n "$WATCHDOG_PID" ]; then
    : > "$d/.watchdog-stop"
    kill "$WATCHDOG_PID" 2>/dev/null || true
    wait "$WATCHDOG_PID" 2>/dev/null || true
    WATCHDOG_PID=""
    [ -f "$d/WATCHDOG-KILL.txt" ] && die "watchdog fired: $(head -1 "$d/WATCHDOG-KILL.txt")"
  fi
  return 0
}

wait_models() { # url, limit
  local url="$1" limit="${2:-1800}" t0=$SECONDS
  until curl -fsS -m 5 "$url/v1/models" >/dev/null 2>&1; do
    (( SECONDS - t0 > limit )) && die "no /v1/models on $url after ${limit}s"
    sleep 2
  done
  echo $(( SECONDS - t0 ))
}
wait_healthy() { # name, limit
  local name="$1" limit="${2:-1800}" t0=$SECONDS state
  while :; do
    state=$(docker inspect -f '{{.State.Health.Status}}' "$name" 2>/dev/null || echo missing)
    [ "$state" = "healthy" ] && { echo $(( SECONDS - t0 )); return 0; }
    (( SECONDS - t0 > limit )) && die "A1: $name not healthy after ${limit}s (state=$state)"
    sleep 5
  done
}
record_env() { # dir
  local d="$1"
  { echo "kernel $(uname -r)"
    echo "machine $(cat /sys/devices/virtual/dmi/id/product_name 2>/dev/null)"
    echo "cpu $(awk -F: '/model name/ {print $2; exit}' /proc/cpuinfo | sed 's/^ //')"
    echo "mem_total_gib $(awk '/MemTotal/ {printf "%d", $2/1024/1024}' /proc/meminfo)"
    echo "timestamp $(date -Is)"
    echo "kyojin_repo_commit $(cat "$ROOT/vendor/kyojin.commit" 2>/dev/null || echo unknown)"; } > "$d/env.txt" 2>&1
  docker image inspect ghcr.io/peonist-ai/halogen-flash-server:0.18.13 \
    --format 'halogen_digest {{index .RepoDigests 0}}' >> "$d/env.txt" 2>&1 || true
  docker images ghcr.io/yamz-labs/kyojin-qwen --format 'kyojin_local_tag {{.Tag}} {{.Digest}}' \
    >> "$d/env.txt" 2>&1 || true
  grep -h 'image:' "$KYOJIN_DIR"/docker-compose.s1.yml "$KYOJIN_DIR"/docker-compose.s4.yml \
    >> "$d/env.txt" 2>&1 || true
}

cmd_setup() {
  mkdir -p "$ROOT/vendor" "$ROOT/runs"
  if [ ! -d "$ROOT/vendor/kyojin/.git" ]; then
    git clone --depth 1 https://github.com/Yamz-Labs/kyojin.git "$ROOT/vendor/kyojin"
  fi
  git -C "$ROOT/vendor/kyojin" rev-parse HEAD | tee "$ROOT/vendor/kyojin.commit"
  log "vendored kyojin at $(cat "$ROOT/vendor/kyojin.commit") — used for tools/bench.py only, not redistributed"
}

cmd_preflight() {
  resolve_digests
  local d; d=$(phase_dir preflight); record_env "$d"; host_snapshot "$d" stats-pre
  log "preflight: MemAvailable=$(avail_gib)GiB GTT=$(gtt_mib)MiB buffcache=$(awk '/^Cached/ {printf "%d", ($2)/1024/1024}' /proc/meminfo)GiB"
  log "halogen: $(docker inspect -f '{{.State.Status}}/{{.State.Health.Status}}' $HALOGEN_NAME 2>/dev/null || echo absent)"
  log "kyojin:  $(docker inspect -f '{{.State.Status}}' $KYOJIN_NAME 2>/dev/null || echo absent)"
  log "ports: 8731=$(ss -tlnH 'sport = :8731' | wc -l) 8732=$(ss -tlnH 'sport = :8732' | wc -l)"
  gtt_mib > "$ROOT/runs/preflight/gtt-baseline.txt"
  log "A2 floor: GTT baseline $(cat "$ROOT/runs/preflight/gtt-baseline.txt")MiB + 4096 = $(gtt_floor_mib)MiB"
  true
}

cmd_smoke() {
  resolve_digests
  local d; d=$(phase_dir smoke)
  log "smoke against $HALOGEN_URL at tiny sizes (validates tooling and the argument-passing assumption)"
  "$PY" "$KB" --base "$HALOGEN_URL/v1" --label smoke --phase smoke --digest "$(digest_for "$HALOGEN_URL")" --out "$d/ctx.json" ctx --sizes 2000 --max-tokens 1
  "$PY" "$KB" --base "$HALOGEN_URL/v1" --label smoke --phase smoke --digest "$(digest_for "$HALOGEN_URL")" --out "$d/tool.json" tool
  "$PY" "$KB" --base "$HALOGEN_URL/v1" --label smoke --phase smoke --digest "$(digest_for "$HALOGEN_URL")" --out "$d/image.json" image
  "$PY" "$KB" --base "$HALOGEN_URL/v1" --label smoke --phase smoke --digest "$(digest_for "$HALOGEN_URL")" --out "$d/conc.json" conc --n 2 --prompt-tokens 2000 --max-tokens 64
  "$PY" "$KB" --base "$HALOGEN_URL/v1" --label smoke --phase smoke --digest "$(digest_for "$HALOGEN_URL")" --out "$d/needle.json" needle --target 8000 --at 0.4,0.85
  log "smoke done: $d"
}

run_matrix() { # label, url, dir
  local label="$1" url="$2" d="$3" model
  model=$(curl -fsS -m 20 "$url/v1/models" | "$PY" -c 'import json,sys;print(json.load(sys.stdin)["data"][0]["id"])')
  echo "$model" > "$d/model-id.txt"
  curl -fsS -m 30 "$url/health"     > "$d/health.json"  2>&1 || echo '{"error":"no /health"}' > "$d/health.json"
  curl -fsS -m 30 "$url/v1/models" > "$d/models.json" 2>&1 || true
  curl -fsS -m 30 "$url/metrics"    > "$d/metrics.txt" 2>&1 || true

  log "[$label] upstream bench.py (author's own prefill + decode method)"
  ( cd "$ROOT/vendor/kyojin" && "$PY" tools/bench.py --base "$url/v1" --reps 3 --json ) \
    > "$d/bench.txt" 2>&1 || log "[$label] bench.py failed, see $d/bench.txt"

  log "[$label] long-context warmup (first touch of any on-disk lookup table)"
  "$PY" "$KB" --base "$url/v1" --label "$label" --phase "$label" --digest "$(digest_for "$url")" --out "$d/ctx-warmup.json" ctx --sizes 32000 --max-tokens 1 | tail -1

  log "[$label] prefill + TTFT at 32K / 128K / ~251K"
  "$PY" "$KB" --base "$url/v1" --label "$label" --phase "$label" --digest "$(digest_for "$url")" --out "$d/ctx.json" ctx --sizes 32000,128000,262144 --max-tokens 1
  host_snapshot "$d" stats-ctx

  log "[$label] needle at 40% and 85% of 250K"
  "$PY" "$KB" --base "$url/v1" --label "$label" --phase "$label" --digest "$(digest_for "$url")" --out "$d/needle.json" needle --target 250000 --at 0.40,0.85

  log "[$label] one tool call"
  "$PY" "$KB" --base "$url/v1" --label "$label" --phase "$label" --digest "$(digest_for "$url")" --out "$d/tool.json" tool

  log "[$label] one image input"
  "$PY" "$KB" --base "$url/v1" --label "$label" --phase "$label" --digest "$(digest_for "$url")" --out "$d/image.json" image

  log "[$label] one thinking sample at effort xhigh"
  curl -fsS -m 900 "$url/v1/chat/completions" -H 'content-type: application/json' \
    -d "{\"model\":\"$model\",\"messages\":[{\"role\":\"user\",\"content\":\"A shop sells 3 items. Two cost the same and the third costs 20 more than each of them. The total is 80. What does each cost? Show the reasoning briefly.\"}],\"reasoning_effort\":\"xhigh\",\"max_tokens\":2048,\"temperature\":0}" \
    > "$d/thinking.json" 2>&1 || log "[$label] thinking sample failed (recorded)"

  log "[$label] one-shot artifact: voxel pagoda, no tools, no retry, max_tokens $ARTIFACT_MAX_TOKENS"
  "$PY" "$KB" --base "$url/v1" --label "$label" --phase "$label" --digest "$(digest_for "$url")" --out "$d/artifact-pagoda.json" \
    --corpus "$ROOT/vendor/kyojin/doc/benchmarks.md" oneshot \
    --prompt-file "$ROOT/docs/prompts/pagoda.txt" --max-tokens "$ARTIFACT_MAX_TOKENS" \
    --out-html "$d/artifact-pagoda.html" || log "[$label] pagoda run failed (recorded)"
}

run_concurrency() { # label, url, dir
  local label="$1" url="$2" d="$3"
  log "[$label] concurrency N=1 (reference point)"
  "$PY" "$KB" --base "$url/v1" --label "$label" --phase "$label" --digest "$(digest_for "$url")" --out "$d/conc1.json" conc --n 1 --prompt-tokens 8000 --max-tokens 512
  log "[$label] concurrency N=4"
  "$PY" "$KB" --base "$url/v1" --label "$label" --phase "$label" --digest "$(digest_for "$url")" --out "$d/conc4.json" conc --n 4 --prompt-tokens 8000 --max-tokens 512
  host_snapshot "$d" stats-conc
}

cmd_halogen() {
  resolve_digests
  local d; d=$(phase_dir halogen); record_env "$d"
  log "H1 — Halogen first start: caches cleared, page cache dropped"
  ( cd "$HALOGEN_DIR" && docker compose stop ) > "$d/stop-before.log" 2>&1 || true
  sleep 5
  sudo -n rm -rf "${HALOGEN_DIR:?}/cache"/* 2>/dev/null || true
  { echo "halogen_cache_after_clear_bytes $(sudo -n du -sb "$HALOGEN_DIR/cache" 2>/dev/null | cut -f1)"
    echo "gtt_after_stop_mib $(gtt_mib)"; echo "avail_after_stop_gib $(avail_gib)"; } > "$d/stop-state.txt"
  (( $(gtt_mib) > $(gtt_floor_mib) )) && die "A2: $(gtt_mib)MiB GTT still held after stopping Halogen (floor $(gtt_floor_mib)MiB)"
  drop_page_cache "$d" h1
  ( cd "$HALOGEN_DIR" && docker compose config > "$d/compose.resolved.yml" )
  start_watchdog "$d"
  local t0=$SECONDS
  ( cd "$HALOGEN_DIR" && docker compose up -d ) | tee "$d/start-h1.log"
  wait_models "$HALOGEN_URL" 1800 >/dev/null
  local ready=$(( SECONDS - t0 ))
  local healthy; healthy=$(wait_healthy "$HALOGEN_NAME" 1800)
  echo "first_start_to_models_s $ready" > "$d/startup.txt"
  echo "first_start_to_healthy_s $healthy" >> "$d/startup.txt"
  log "H1 first start: ${ready}s to /v1/models, ${healthy}s to healthy"
  docker logs "$HALOGEN_NAME" > "$d/docker-startup.log" 2>&1 || true
  stop_watchdog "$d"

  run_matrix halogen "$HALOGEN_URL" "$d"
  run_concurrency halogen "$HALOGEN_URL" "$d"

  log "H2 — Halogen warm start (cache dir populated, page cache holding its own weights)"
  ( cd "$HALOGEN_DIR" && docker compose stop ) > "$d/stop-h2.log" 2>&1 || true
  sleep 5
  start_watchdog "$d"
  t0=$SECONDS
  ( cd "$HALOGEN_DIR" && docker compose up -d ) | tee "$d/start-h2.log"
  wait_models "$HALOGEN_URL" 1800 >/dev/null
  ready=$(( SECONDS - t0 )); healthy=$(wait_healthy "$HALOGEN_NAME" 1800)
  echo "warm_start_to_models_s $ready" >> "$d/startup.txt"
  echo "warm_start_to_healthy_s $healthy" >> "$d/startup.txt"
  log "H2 warm start: ${ready}s to /v1/models, ${healthy}s to healthy"
  docker logs "$HALOGEN_NAME" > "$d/docker.log" 2>&1 || true
  stop_watchdog "$d"
  host_snapshot "$d" stats-end
  log "phase H done: $d"
}

cmd_kyojin_s1() {
  resolve_digests
  local d; d=$(phase_dir kyojin-s1); record_env "$d"
  log "stopping Halogen for the swap"
  local before_gtt before_avail; before_gtt=$(gtt_mib); before_avail=$(avail_gib)
  ( cd "$HALOGEN_DIR" && docker compose stop ) | tee "$d/stop-halogen.log"
  sleep 5
  printf 'gtt_before_mib %s\ngtt_after_mib %s\navail_before_gib %s\navail_after_gib %s\n' \
    "$before_gtt" "$(gtt_mib)" "$before_avail" "$(avail_gib)" > "$d/stop-state.txt"
  (( $(gtt_mib) > $(gtt_floor_mib) )) && die "A2: $(gtt_mib)MiB GTT still held after stopping Halogen (floor $(gtt_floor_mib)MiB). Not starting Kyojin."
  drop_page_cache "$d" k1

  log "K1 — Kyojin first start, --sessions 1"
  ( cd "$KYOJIN_DIR" && docker compose "${KYOJIN_S1[@]}" config > "$d/compose.resolved.yml" )
  { echo "kyojin_cache_before_bytes $(du -sb "$KYOJIN_DIR/cache" 2>/dev/null | cut -f1)"; } > "$d/cache-state.txt"
  start_watchdog "$d"
  local t0=$SECONDS
  ( cd "$KYOJIN_DIR" && docker compose "${KYOJIN_S1[@]}" up -d ) | tee "$d/start.log"
  local ready; ready=$(wait_models "$KYOJIN_URL" 2400)
  echo "first_start_to_models_s $ready" > "$d/startup.txt"
  echo "wall_from_up_to_models_s $(( SECONDS - t0 ))" >> "$d/startup.txt"
  log "K1 first start: ${ready}s to /v1/models"
  docker logs "$KYOJIN_NAME" > "$d/docker-startup.log" 2>&1 || true
  grep -iE "qserve: starting|sessions=|WARNING --sessions|not guaranteed" "$d/docker-startup.log" \
    > "$d/effective-config.txt" 2>&1 || true
  log "effective config: $(tr '\n' ' ' < "$d/effective-config.txt" | head -c 400)"
  stop_watchdog "$d"

  sleep 20
  curl -fsS -m 900 -X POST "$KYOJIN_URL/v1/chat/completions" -H 'content-type: application/json' \
    -d '{"model":"kyojin-qwen38","messages":[{"role":"user","content":"Reply with the single word: ready"}],"max_tokens":16,"temperature":0,"enable_thinking":false}' \
    > "$d/warmup.json" 2>&1 || true

  run_matrix kyojin-s1 "$KYOJIN_URL" "$d"

  log "container-experience probes"
  { set +e
    mkdir -p <temp> && cp "$KYOJIN_DIR/compose.yaml" <temp>/ 2>/dev/null
    ( cd <temp> && docker compose config ) > "$d/probe-missing-env.txt" 2>&1
    echo "exit=$?" >> "$d/probe-missing-env.txt"
    set -e; } || true
  { set +e
    "$PY" - <<'PYBIND' &
import socket, time
s = socket.socket(); s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
s.bind(("127.0.0.1", 8732)); s.listen(1); time.sleep(25)
PYBIND
    local holder=$!; sleep 2
    ( cd "$KYOJIN_DIR" && docker compose "${KYOJIN_S1[@]}" up -d ) > "$d/probe-port-in-use.txt" 2>&1
    echo "exit=$?" >> "$d/probe-port-in-use.txt"
    kill "$holder" 2>/dev/null
    set -e; } || true
  docker logs "$KYOJIN_NAME" > "$d/docker.log" 2>&1 || true
  host_snapshot "$d" stats-end
  log "phase K1 done: $d"
}

cmd_kyojin_s4() {
  resolve_digests
  local d; d=$(phase_dir kyojin-s4); record_env "$d"
  log "K2 — Kyojin warm start, --sessions 4"
  ( cd "$KYOJIN_DIR" && docker compose "${KYOJIN_S1[@]}" stop ) | tee "$d/stop.log"
  sleep 5
  ( cd "$KYOJIN_DIR" && docker compose "${KYOJIN_S4[@]}" config > "$d/compose.resolved.yml" )
  start_watchdog "$d"
  local t0=$SECONDS
  ( cd "$KYOJIN_DIR" && docker compose "${KYOJIN_S4[@]}" up -d ) | tee "$d/start.log"
  local ready; ready=$(wait_models "$KYOJIN_URL" 2400)
  echo "warm_start_to_models_s $ready" > "$d/startup.txt"
  echo "wall_from_up_to_models_s $(( SECONDS - t0 ))" >> "$d/startup.txt"
  log "K2 warm start: ${ready}s to /v1/models"
  sleep 20
  docker logs "$KYOJIN_NAME" > "$d/docker.log" 2>&1 || true
  grep -iE "qserve: starting|sessions=|WARNING --sessions|not guaranteed" "$d/docker.log" \
    > "$d/effective-config.txt" 2>&1 || true
  curl -fsS -m 30 "$KYOJIN_URL/health" > "$d/health.json" 2>&1 || echo '{"error":"no /health"}' > "$d/health.json"
  stop_watchdog "$d"
  run_concurrency kyojin-s4 "$KYOJIN_URL" "$d"
  log "phase K2 done: $d"
}

cmd_extras() { # label — the two additions the reframing needs
  resolve_digests
  local label="${1:?usage: bench.sh extras <label>}"
  local url; case "$label" in halogen) url="$HALOGEN_URL";; *) url="$KYOJIN_URL";; esac
  local d; d=$(phase_dir "$label-extra"); record_env "$d"
  log "[$label] repeated-prefix cost (what an agent turn actually pays)"
  "$PY" "$KB" --base "$url/v1" --label "$label" --phase "$label" --digest "$(digest_for "$url")" --out "$d/reuse.json" \
    reuse --prompt-tokens 100000 --max-tokens 16 || log "[$label] reuse probe failed (recorded)"
  log "[$label] concurrency N=2"
  "$PY" "$KB" --base "$url/v1" --label "$label" --phase "$label" --digest "$(digest_for "$url")" --out "$d/conc2.json" conc --n 2 --prompt-tokens 8000 --max-tokens 512
  host_snapshot "$d" stats-end
  log "extras done: $d"
}

cmd_variance() { # label — repetitions of the claims the verdict leans on
  resolve_digests
  local label="${1:?usage: bench.sh variance <label>}"
  local url; case "$label" in halogen) url="$HALOGEN_URL";; *) url="$KYOJIN_URL";; esac
  local d; d=$(phase_dir "$label")
  local tmp; tmp=$(mktemp -d)
  log "[$label] variance: 3 x prefill/TTFT at 32K/128K/262K and 3 x N=4"
  local i
  for i in 1 2 3; do
    "$PY" "$KB" --base "$url/v1" --label "$label" --phase "$label" --digest "$(digest_for "$url")" \
      --out "$tmp/ctx-$i.json" ctx --sizes 32000,128000,262144
    "$PY" "$KB" --base "$url/v1" --label "$label" --phase "$label" --digest "$(digest_for "$url")" \
      --out "$tmp/conc4-$i.json" conc --n 4 --prompt-tokens 8000 --max-tokens 512
  done
  "$PY" - "$tmp" "$d/variance.json" <<'PY'
import json, sys
from pathlib import Path
tmp, out = Path(sys.argv[1]), Path(sys.argv[2])
def reps(prefix):
    return [json.loads(p.read_text()) for p in sorted(tmp.glob(f"{prefix}-*.json"))]
doc = {"ctx": reps("ctx"), "conc4": reps("conc4")}
out.write_text(json.dumps(doc, indent=1))
print(f"{out}: {len(doc['ctx'])} ctx reps, {len(doc['conc4'])} concurrency reps")
PY
  rm -rf "$tmp"
  log "variance done: $d"
}

cmd_status() {
  echo "--- phases present ---"
  for d in "$ROOT"/runs/*/; do
    [ -d "$d" ] || continue
    printf '%-22s %s files, %s\n' "$(basename "$d")" "$(find "$d" -maxdepth 1 -type f | wc -l)" \
      "$(find "$d" -maxdepth 1 -type f -printf '%T@ %p\n' 2>/dev/null | sort -n | tail -1 | cut -d' ' -f2-)"
  done
  echo "--- running ---"
  pgrep -af '^bash ./bench.sh' | grep -v pgrep || echo "no phase running"
  echo "--- log tail ---"
  tail -3 "$ROOT/runs/session.log" 2>/dev/null
  echo "--- host ---"
  echo "avail $(avail_gib)GiB  gtt $(gtt_mib)MiB  $(docker ps --format '{{.Names}}' | grep -cE 'halogen|kyojin') engine container(s)"
}

cmd_restore() {
  local d; d=$(phase_dir restore); record_env "$d"
  log "stopping Kyojin"
  ( cd "$KYOJIN_DIR" && docker compose "${KYOJIN_S4[@]}" stop ) | tee "$d/stop.log" || true
  sleep 5
  echo "gtt_after_kyojin_stop_mib $(gtt_mib)" > "$d/stop-state.txt"
  log "restarting Halogen"
  local t0=$SECONDS
  ( cd "$HALOGEN_DIR" && docker compose up -d ) | tee "$d/start.log"
  wait_models "$HALOGEN_URL" 1800 >/dev/null
  local healthy; healthy=$(wait_healthy "$HALOGEN_NAME" 1800)
  curl -fsS -m 30 "$HALOGEN_URL/health" > "$d/health.json" 2>&1 || true
  curl -fsS -m 300 -X POST "$HALOGEN_URL/v1/chat/completions" -H 'content-type: application/json' \
    -d '{"model":"halogen-qwen3.8-flash-next","messages":[{"role":"user","content":"Reply with the single word: ok"}],"max_tokens":8,"temperature":0}' \
    > "$d/smoke.json" 2>&1 || die "A1: Halogen healthy but does not answer"
  log "restore done: Halogen healthy in ${healthy}s and answering ($(( SECONDS - t0 ))s total)"
  host_snapshot "$d" stats-end
}

mkdir -p "$ROOT/runs"
case "${1:-}" in
  setup)      cmd_setup ;;
  preflight)  cmd_preflight ;;
  smoke)      cmd_smoke ;;
  halogen)    cmd_halogen ;;
  kyojin-s1)  cmd_kyojin_s1 ;;
  kyojin-s4)  cmd_kyojin_s4 ;;
  status)     cmd_status ;;
  extras)     cmd_extras "${2:-}" ;;
  variance)   cmd_variance "${2:-}" ;;
  restore)    cmd_restore ;;
  *) sed -n '2,18p' "${BASH_SOURCE[0]}"; exit 2 ;;
esac
