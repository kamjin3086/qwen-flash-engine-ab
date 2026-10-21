#!/usr/bin/env python3
"""Derive one flat summary of measurements from the phase directories.

This is the only step that reads `runs/`. Everything downstream reads `summary.json`,
so a number can never be re-derived differently in two places.

Each entry says what was measured, on which engine, in which phase, with which image
digest, under which condition, whether it was measured / not run / aborted, and which
raw file proves it. A measurement that is absent is an entry with status `not_run`,
never a missing key: absence is how a report silently loses a result.

    python3 report/summary.py --runs runs --out results/summary.json \
        [--csv results/measurements.csv]
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import re
import statistics
import sys
from pathlib import Path

# metric id -> unit. An unknown metric is an error, not a new row.
METRICS = {
    "prefill_tps": "tok/s",
    "prompt_tokens": "tokens",
    "decode_tps": "tok/s",
    "ttft_s": "s",
    "needle_found": "bool",
    "tool_call_ok": "bool",
    "tool_call_has_arguments": "bool",
    "vision_ok": "bool",
    "thinking_tokens": "tokens",
    "aggregate_decode_tps": "tok/s",
    "per_request_decode_tps": "tok/s",
    "ttft_p50_s": "s",
    "ttft_p95_s": "s",
    "peak_in_flight": "requests",
    "prompt_cache_hit_tokens": "tokens",
    "prefix_reuse_ttft_s": "s",
    "prefix_cold_ttft_s": "s",
    "startup_s": "s",
    "artifact_tokens": "tokens",
    "artifact_truncated": "bool",
    "artifact_complete_html": "bool",
    "quality_case_pass": "bool",
    "quality_pass_rate": "ratio",
}

PHASES = ["halogen", "halogen-extra", "kyojin-s1", "kyojin-s4", "kyojin-extra"]
ENGINES = ("halogen", "kyojin")

# Metrics an engine may legitimately not report at all: Kyojin's /health answers, but
# publishes no occupancy counters, so "in flight" cannot be observed on it. A missing value
# there is a fact, not a bug; for every other metric a missing value means the extractor is
# wrong and the run stops.
OPTIONAL_METRICS = {"peak_in_flight", "prompt_cache_hit_tokens"}

# The files a phase is allowed to contain. Anything else is a capture this step does not
# understand, and ignoring it is how a result goes missing without anyone noticing.
KNOWN_FILES = {
    "env.txt", "health.json", "models.json", "metrics.txt", "bench.txt", "ctx.json", "variance.json",
    "ctx-warmup.json", "needle.json", "tool.json", "image.json", "thinking.json",
    "conc.json", "conc1.json", "conc2.json", "conc4.json", "reuse.json", "warmup.json",
    "artifact-pagoda.json", "artifact-pagoda.html", "artifact-hexagon.json",
    "artifact-hexagon.html", "startup.txt", "stop-state.txt", "stop-before.log",
    "stop-halogen.log", "stop-h2.log", "stop.log", "start.log", "start-h1.log",
    "start-h2.log", "compose.resolved.yml", "model-id.txt", "cache-state.txt",
    "drop-h1.txt", "drop-k1.txt", "stats-pre.txt", "stats-ctx.txt", "stats-conc.txt",
    "stats-end.txt", "docker.log", "docker-startup.log", "effective-config.txt",
    "sessions-warnings.txt", "probe-missing-env.txt", "probe-port-in-use.txt",
    "smoke.json", "ABORT.txt", "WATCHDOG-KILL.txt", ".watchdog-stop",
}


def engine_of(phase: str) -> str:
    for engine in ENGINES:
        if phase.startswith(engine):
            return engine
    raise SystemExit(f"phase {phase!r} does not belong to a known engine {ENGINES}")


def digests(runs: Path, phase: str) -> dict:
    """Image identity for a phase, from the environment capture that phase wrote."""
    env = runs / phase / "env.txt"
    out = {"halogen": None, "kyojin": None}
    if not env.is_file():
        return out
    for line in env.read_text(errors="replace").splitlines():
        if line.startswith("halogen_digest "):
            out["halogen"] = line.split(" ", 1)[1].strip()
        elif line.startswith("kyojin_local_tag "):
            parts = line.split()
            if len(parts) >= 3 and parts[1] in ("1.5", "1.6", "1.6.0", "latest"):
                # prefer the newest published tag present
                out.setdefault("_tags", {})[parts[1]] = parts[2]
        elif line.strip().startswith("image: ghcr.io/yamz-labs/kyojin-qwen@"):
            out["kyojin"] = line.strip().split("image: ", 1)[1]
    tags = out.pop("_tags", {}) or {}
    if not out["kyojin"]:
        for tag in ("1.6", "1.6.0", "latest", "1.5"):
            if tag in tags:
                out["kyojin"] = f"ghcr.io/yamz-labs/kyojin-qwen@{tags[tag]}"
                break
    return out


def load(path: Path) -> dict | None:
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text())
    except json.JSONDecodeError as e:
        raise SystemExit(f"{path}: not valid JSON ({e})")


def phase_abort(runs: Path, phase: str) -> str | None:
    d = runs / phase
    for name, rule in (("WATCHDOG-KILL.txt", "watchdog"), ("ABORT.txt", "abort")):
        f = d / name
        if f.is_file():
            head = f.read_text(errors="replace").strip().splitlines()
            return head[0] if head else rule
    return None


class Collector:
    """Rows are keyed by (metric, condition); each engine fills a cell.

    A row exists only if some engine actually measured it, and a cell is `not_run` only
    when the same measurement was taken on the other engine. That keeps "not run" honest
    (it means the comparison has a hole) instead of turning every phase-specific extra
    into a false gap.
    """

    def __init__(self, runs: Path):
        self.runs = runs
        self.rows: dict[tuple[str, str], dict[str, dict]] = {}
        # one digest per engine, taken from whichever phase recorded it first: a quality
        # run has no env.txt of its own but still came from the same image
        self.engine_digest: dict[str, str | None] = {}
        for phase in PHASES:
            for engine, dig in digests(runs, phase).items():
                if dig and not self.engine_digest.get(engine):
                    self.engine_digest[engine] = dig

    def add(self, phase: str, metric: str, condition: str, value, raw: Path,
            status: str = "measured", abort_rule: str | None = None,
            provenance_source: str = "phase env.txt",
            spread: dict | None = None) -> None:
        if metric not in METRICS:
            raise SystemExit(f"unknown metric {metric!r} from {raw}")
        if status == "measured" and value is None:
            if metric in OPTIONAL_METRICS:
                status = "not_run"
            else:
                raise SystemExit(f"{raw}: {metric} under {condition!r} produced no value")
        entry = {
            "metric": metric,
            "unit": METRICS[metric],
            "engine": engine_of(phase),
            "phase": phase,
            "digest": self.engine_digest.get(engine_of(phase)),
            "condition": condition,
            "value": value,
            "raw_path": str(raw.relative_to(self.runs.parent)) if raw.exists() else str(raw),
            "status": status,
            "abort_rule": abort_rule,
            "provenance_source": provenance_source,
        }
        if spread:
            entry["spread"] = spread
        key = (metric, condition)
        cell = self.rows.setdefault(key, {}).get(entry["engine"])
        # a measured value always wins over a not_run recorded by another phase; between two
        # not_run records, the one whose raw file exists wins, so the reader gets evidence
        def exists(e: dict) -> bool:
            return bool(e.get("raw_path")) and (self.runs.parent / e["raw_path"]).is_file()

        if cell is None:
            self.rows[key][entry["engine"]] = entry
        elif cell["status"] != "measured" and entry["status"] == "measured":
            self.rows[key][entry["engine"]] = entry
        elif cell["status"] != "measured" and not exists(cell) and exists(entry):
            self.rows[key][entry["engine"]] = entry

    def not_run(self, phase: str, metric: str, condition: str, raw: Path,
                abort_rule: str | None = None) -> None:
        self.add(phase, metric, condition, None, raw,
                 status="aborted" if abort_rule else "not_run", abort_rule=abort_rule)


def read_startup(path: Path) -> dict:
    out = {}
    if not path.is_file():
        return out
    for line in path.read_text(errors="replace").splitlines():
        if " " in line:
            k, v = line.split(None, 1)
            try:
                out[k] = float(v)
            except ValueError:
                out[k] = v
    return out


def spread_of(values) -> dict | None:
    """The repetitions behind one number, when the tool recorded them."""
    vals = [v for v in (values or []) if isinstance(v, (int, float)) and not isinstance(v, bool)]
    if len(vals) < 2:
        return None
    return {"n": len(vals), "min": min(vals), "max": max(vals)}


def bench_json(path: Path) -> dict | None:
    """The fenced JSON block that upstream tools/bench.py prints beside its table.

    A file that is present but unreadable is an error: silently downgrading it to "not run"
    turns a broken capture into a missing result, which is the failure this report is
    built to avoid.
    """
    if not path.is_file():
        return None
    text = path.read_text(errors="replace")
    m = re.search(r"```json\s*(\{.*?\})\s*```", text, re.S)
    if not m:
        raise SystemExit(f"{path}: no fenced JSON block; the capture is incomplete")
    try:
        return json.loads(m.group(1))
    except json.JSONDecodeError as e:
        raise SystemExit(f"{path}: fenced JSON does not parse ({e})")


def variance_block(runs: Path) -> list[dict]:
    """Statistics over the repetitions a `bench.sh variance` phase recorded.

    Kept out of the headline table: the headline stays the run as it happened, and this is
    the same configuration measured again to show how far one observation travels.
    """
    out: list[dict] = []
    for phase in PHASES:
        path = runs / phase / "variance.json"
        doc = load(path)
        if not doc:
            continue
        engine = engine_of(phase)
        raw = str(path.relative_to(runs.parent))

        def add(metric: str, condition: str, values: list) -> None:
            vals = [v for v in values if isinstance(v, (int, float)) and not isinstance(v, bool)]
            if len(vals) < 2:
                return
            out.append({"engine": engine, "phase": phase, "metric": metric,
                        "unit": METRICS[metric], "condition": condition,
                        "n": len(vals), "median": round(statistics.median(vals), 2),
                        "min": min(vals), "max": max(vals), "raw_path": raw})

        ctx = doc.get("ctx") or []
        for size in (32000, 128000, 262144):
            cond = f"prompt ~{size // 1000}K"
            runs_at = [next((r for r in rep.get("runs", []) if r.get("requested_tokens") == size),
                            None) for rep in ctx]
            add("prefill_tps", cond, [r.get("prefill_tps_server") for r in runs_at if r])
            add("ttft_s", cond, [r.get("ttft_s") for r in runs_at if r])
        conc = doc.get("conc4") or []
        add("aggregate_decode_tps", "N=4", [rep.get("summary", {}).get("aggregate_decode_tps")
                                           for rep in conc])
        add("per_request_decode_tps", "N=4",
            [statistics.median([v for v in rep.get("summary", {}).get("per_request_decode_tps") or []
                                if v is not None])
             for rep in conc if rep.get("summary", {}).get("per_request_decode_tps")])
        add("ttft_p50_s", "N=4", [rep.get("summary", {}).get("ttft_p50") for rep in conc])
    return out


def collect(runs: Path) -> dict:
    c = Collector(runs)
    present = [p for p in PHASES if (runs / p).is_dir()]
    if not present:
        raise SystemExit(f"no phase directories under {runs}")
    for phase in sorted(p.name for p in runs.iterdir() if p.is_dir() and not p.name.startswith("_")):
        unknown = sorted(f.name for f in (runs / phase).iterdir()
                         if f.is_file() and f.suffix == ".json" and f.name not in KNOWN_FILES)
        if unknown:
            raise SystemExit(f"{phase}: unrecognised capture file(s) {unknown}; refusing to "
                             f"ignore a result it does not know how to read")
    # a phase that cannot name the image that produced its numbers is not usable
    for phase in present:
        if not (runs / phase / "env.txt").is_file():
            raise SystemExit(f"{phase}: env.txt is missing, so the image digest of its "
                             f"measurements cannot be established")

    for phase in PHASES:
        if not (runs / phase).is_dir():
            for metric, cond in (("prefill_tps", "bench.py method"), ("decode_tps", "chat")):
                c.not_run(phase, metric, cond, runs / phase / "bench.txt")
            continue
        d = runs / phase
        abort = phase_abort(runs, phase)

        # upstream bench.py: the author's own prefill and decode method
        bj = bench_json(d / "bench.txt")
        if bj and "prefill" in bj:
            cond = "bench.py method"
            c.add(phase, "prefill_tps", cond, bj["prefill"].get("tok_s"), d / "bench.txt",
                  spread=spread_of(bj["prefill"].get("runs")))
            c.add(phase, "prompt_tokens", cond, bj["prefill"].get("prompt_tokens"), d / "bench.txt")
            for cat, blob in (bj.get("decode") or {}).items():
                c.add(phase, "decode_tps", f"decode {cat}", blob.get("tok_s"), d / "bench.txt",
                      spread=spread_of(blob.get("runs")))
        else:
            c.not_run(phase, "prefill_tps", "bench.py method", d / "bench.txt", abort)

        # prefill and TTFT against context length
        ctx = load(d / "ctx.json")
        for size in (32000, 128000, 262144):
            cond = f"prompt ~{size // 1000}K"
            if ctx is None:
                c.not_run(phase, "prefill_tps", cond, d / "ctx.json", abort)
                c.not_run(phase, "ttft_s", cond, d / "ctx.json", abort)
                continue
            run = next((r for r in ctx.get("runs", []) if r.get("requested_tokens") == size), None)
            if not run or run.get("error"):
                c.not_run(phase, "prefill_tps", cond, d / "ctx.json", abort or (run or {}).get("error"))
                c.not_run(phase, "ttft_s", cond, d / "ctx.json", abort or (run or {}).get("error"))
                continue
            c.add(phase, "prefill_tps", cond, run.get("prefill_tps_server"), d / "ctx.json")
            c.add(phase, "ttft_s", cond, run.get("ttft_s"), d / "ctx.json")
            c.add(phase, "prompt_tokens", cond, run.get("prompt_tokens"), d / "ctx.json")

        # retrieval at depth
        needle = load(d / "needle.json")
        positions = (needle or {}).get("positions") or [0.40, 0.85]
        for i, pos in enumerate(positions):
            cond = f"fact at {int(pos * 100)}% of 250K"
            if needle is None:
                c.not_run(phase, "needle_found", cond, d / "needle.json", abort)
                continue
            run = (needle.get("runs") or [])[i] if i < len(needle.get("runs") or []) else None
            if run is None:
                c.not_run(phase, "needle_found", cond, d / "needle.json", abort)
            else:
                c.add(phase, "needle_found", cond, bool(run.get("found")), d / "needle.json")

        # tool call
        tool = load(d / "tool.json")
        if tool is None:
            c.not_run(phase, "tool_call_ok", "single tool call", d / "tool.json", abort)
        else:
            c.add(phase, "tool_call_ok", "single tool call", bool(tool.get("called")), d / "tool.json")
            c.add(phase, "tool_call_has_arguments", "single tool call",
                  bool((tool.get("first_arguments") or "").strip()), d / "tool.json")

        # vision
        img = load(d / "image.json")
        if img is None:
            c.not_run(phase, "vision_ok", "generated PNG", d / "image.json", abort)
        else:
            c.add(phase, "vision_ok", "generated PNG", bool(img.get("pass")), d / "image.json")

        # thinking sample
        think = load(d / "thinking.json")
        if think is None:
            c.not_run(phase, "thinking_tokens", "effort xhigh", d / "thinking.json", abort)
        else:
            usage = think.get("usage") or {}
            details = usage.get("completion_tokens_details") or {}
            c.add(phase, "thinking_tokens", "effort xhigh",
                  details.get("reasoning_tokens", usage.get("completion_tokens")), d / "thinking.json")

        # concurrency
        for name, n in (("conc1.json", 1), ("conc2.json", 2), ("conc4.json", 4)):
            conc = load(d / name)
            cond = f"N={n}"
            if conc is None:
                for metric in ("aggregate_decode_tps", "per_request_decode_tps", "ttft_p50_s",
                               "ttft_p95_s", "peak_in_flight"):
                    c.not_run(phase, metric, cond, d / name, abort)
                continue
            s = conc.get("summary") or {}
            per = [v for v in (s.get("per_request_decode_tps") or []) if v is not None]
            c.add(phase, "aggregate_decode_tps", cond, s.get("aggregate_decode_tps"), d / name)
            c.add(phase, "per_request_decode_tps", cond, round(statistics.median(per), 2) if per else None, d / name)
            c.add(phase, "ttft_p50_s", cond, s.get("ttft_p50"), d / name)
            c.add(phase, "ttft_p95_s", cond, s.get("ttft_p95"), d / name)
            c.add(phase, "peak_in_flight", cond, s.get("peak_in_flight"), d / name)

        # repeated prefix
        reuse = load(d / "reuse.json")
        if reuse is None:
            c.not_run(phase, "prefix_reuse_ttft_s", "same prefix again", d / "reuse.json", abort)
            c.not_run(phase, "prefix_cold_ttft_s", "cold control", d / "reuse.json", abort)
        else:
            s = reuse.get("summary") or {}
            c.add(phase, "prefix_cold_ttft_s", "cold control", (s.get("cold_1") or {}).get("ttft_s"), d / "reuse.json")
            c.add(phase, "prefix_reuse_ttft_s", "same prefix again", (s.get("reuse") or {}).get("ttft_s"), d / "reuse.json")
            c.add(phase, "prompt_cache_hit_tokens", "same prefix again", (s.get("reuse") or {}).get("cache_n"), d / "reuse.json")

        # startup
        st = read_startup(d / "startup.txt")
        for key, cond in (("first_start_to_models_s", "first start"),
                          ("warm_start_to_models_s", "warm start")):
            if key in st:
                c.add(phase, "startup_s", cond, st[key], d / "startup.txt")
        if "first_start_to_models_s" not in st:
            c.not_run(phase, "startup_s", "first start", d / "startup.txt", abort)

        # one-shot artifact
        art = load(d / "artifact-pagoda.json")
        if art is None:
            c.not_run(phase, "artifact_tokens", "pagoda one-shot", d / "artifact-pagoda.json", abort)
        else:
            c.add(phase, "artifact_tokens", "pagoda one-shot", art.get("completion_tokens"), d / "artifact-pagoda.json")
            c.add(phase, "artifact_truncated", "pagoda one-shot", bool(art.get("truncated")), d / "artifact-pagoda.json")
            c.add(phase, "artifact_complete_html", "pagoda one-shot",
                  bool(art.get("looks_complete_html")), d / "artifact-pagoda.json")

    # quality: 13 script-checkable cases, one file per engine
    for label, engine in (("halogen", "halogen"), ("kyojin", "kyojin")):
        qpath = runs.parent / "results" / "quality" / f"{label}.json"
        q = load(qpath) if qpath.is_file() else None
        phase = f"{label}-quality"
        # the digest is the quality run's own if it recorded one; otherwise it is inherited
        # from the engine's measurement phases, and the summary says exactly that
        recorded = ((q or {}).get("provenance") or {}).get("digest")
        source = ("record" if recorded
                  else f"results/quality/{label}.json; digest inherited from the {engine} phases")
        c.engine_digest[engine] = recorded or c.engine_digest.get(engine)
        if not q:
            c.not_run(phase, "quality_pass_rate", "all 13 cases", qpath)
            continue
        for case in q.get("runs", []):
            c.add(phase, "quality_case_pass", case["id"], bool(case.get("pass")), qpath,
                  provenance_source=source)
        s_ = q.get("summary") or {}
        c.add(phase, "quality_pass_rate", f"all {s_.get('cases', 13)} cases",
              round((s_.get("passed", 0)) / max(1, s_.get("cases", 13)), 3), qpath,
              provenance_source=source)

    entries: list[dict] = []
    for (metric, condition), cells in sorted(c.rows.items()):
        # a row survives if any engine measured it or was stopped while trying: an aborted
        # row is a hole in the comparison that the reader has to see
        if not any(e["status"] in ("measured", "aborted") for e in cells.values()):
            continue
        for engine in ENGINES:
            if engine in cells:
                entries.append(cells[engine])
            else:
                entries.append({
                    "metric": metric, "unit": METRICS[metric], "engine": engine,
                    "phase": None, "digest": c.engine_digest.get(engine),
                    "condition": condition, "value": None, "raw_path": "",
                    "status": "not_run", "abort_rule": None, "provenance_source": "absent",
                })
    # a record that carries its own provenance wins over the phase-level capture
    cache: dict[str, dict | None] = {}
    for e in entries:
        rp = e.get("raw_path") or ""
        if not rp.endswith(".json"):
            continue
        if rp not in cache:
            try:
                cache[rp] = json.loads((runs.parent / rp).read_text())
            except (OSError, json.JSONDecodeError):
                cache[rp] = None
        doc = cache[rp] or {}
        prov = doc.get("provenance") or {}
        if prov.get("digest"):
            e["digest"] = prov["digest"]
            e["provenance_source"] = "record"
            if prov.get("phase"):
                e["phase"] = prov["phase"]

    measured = [e for e in entries if e["status"] == "measured"]
    var = variance_block(runs)
    doc = {
        "schema": 1,
        "phases": present,
        "engines": sorted({e["engine"] for e in entries}),
        "measurements": sorted(entries, key=lambda e: (e["metric"], e["condition"], e["engine"])),
        "counts": {
            "total": len(entries),
            "measured": len(measured),
            "not_run": sum(1 for e in entries if e["status"] == "not_run"),
            "aborted": sum(1 for e in entries if e["status"] == "aborted"),
        },
    }
    if var:
        doc["variance"] = var
    return doc


CSV_COLUMNS = ("engine", "phase", "metric", "unit", "condition", "value", "status",
               "digest", "raw_path", "abort_rule")


def csv_text(doc: dict) -> str:
    """The same rows as the summary, flattened, for readers who want to plot them."""
    buf = io.StringIO()
    writer = csv.writer(buf, lineterminator="\n")
    writer.writerow(CSV_COLUMNS)
    for e in doc["measurements"]:
        row = []
        for key in CSV_COLUMNS:
            value = e.get(key)
            if key == "value" and isinstance(value, bool):
                value = "true" if value else "false"
            row.append("" if value is None else value)
        writer.writerow(row)
    return buf.getvalue()


def write_if_changed(path: Path, text: str, label: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_file() and path.read_text() == text:
        print(f"{path}: unchanged")
    else:
        path.write_text(text)
        print(f"{path}: {label}")


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--runs", default="runs")
    p.add_argument("--out", default="results/summary.json")
    p.add_argument("--csv", default="results/measurements.csv")
    a = p.parse_args()
    runs = Path(a.runs)
    doc = collect(runs)
    out = Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(doc, indent=2, ensure_ascii=False, sort_keys=True)
    if out.is_file() and out.read_text() == text:
        print(f"{out}: unchanged ({doc['counts']['measured']} measured)")
    else:
        out.write_text(text)
        print(f"{out}: {doc['counts']['measured']} measured, {doc['counts']['not_run']} not run, "
              f"{doc['counts']['aborted']} aborted")
    if doc["counts"]["measured"] == 0:
        sys.exit("no measured values: refusing to call that a summary")
    if a.csv:
        write_if_changed(Path(a.csv), csv_text(doc),
                         f"{len(doc['measurements'])} rows, {len(CSV_COLUMNS)} columns")


if __name__ == "__main__":
    main()
