#!/usr/bin/env python3
"""Measurement client for one engine at a time, OpenAI-compatible, stdlib only.

Covers only what upstream `tools/bench.py` (Kyojin repo, `bench/decode.md` method) does
not: exact-size long-context prefill, TTFT at the top of the context, a needle check,
one tool call, and N-way concurrency. Prefill/decode at the author's sizes stay in
upstream bench.py so those numbers remain directly comparable to the published ones.

    python3 tools/kbench.py ctx   --base URL --sizes 32000,128000,262144
    python3 tools/kbench.py needle--base URL --at 0.40,0.85 --target 250000
    python3 tools/kbench.py tool  --base URL
    python3 tools/kbench.py conc  --base URL --n 4 --prompt-tokens 8000 --max-tokens 512

Every request carries a unique salt so no prompt cache can answer it, and every run
costs exactly one request: no warmup inside a measurement.
"""
from __future__ import annotations

import argparse
import base64
import json
import math
import os
import statistics
import struct
import sys
import threading
import time
import urllib.error
import urllib.request
import zlib
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
DEFAULT_CORPUS = HERE / "vendor" / "kyojin" / "doc" / "benchmarks.md"
CHARS_PER_TOKEN = 3.6  # fallback only: every command calibrates against the live tokenizer

NEEDLE = (
    "\n\nMAINTENANCE LOG, DO NOT SUMMARIZE: the spare pressure valve for loop C is "
    "stored in cabinet {slot}, and it was last certified by {who}.\n\n"
)
QUESTIONS = [
    ("In which cabinet is the spare pressure valve for loop C stored?",
     lambda slot, who: slot),
    ("Who last certified the spare pressure valve for loop C?",
     lambda slot, who: who),
]


def corpus_text(path: Path) -> str:
    text = path.read_text(encoding="utf-8", errors="replace")
    if len(text) < 2000:
        sys.exit(f"corpus too small: {path}")
    return text.replace("\x00", " ")


def filler(text: str, approx_chars: int, salt: str) -> str:
    """A deterministic body of roughly `approx_chars`, prefixed with a unique salt."""
    head = f"[request {salt}]\n"
    reps = max(1, approx_chars // len(text) + 1)
    return head + (text * reps)[:approx_chars]


def post(base: str, body: dict, timeout: float = 3600) -> dict:
    req = urllib.request.Request(
        base.rstrip("/") + "/chat/completions",
        data=json.dumps(body, ensure_ascii=False).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.load(resp)


def stream(base: str, body: dict, timeout: float = 3600) -> dict:
    """One streaming request. Returns wall timing, server-reported timing, usage and text."""
    body = dict(body, stream=True, stream_options={"include_usage": True})
    req = urllib.request.Request(
        base.rstrip("/") + "/chat/completions",
        data=json.dumps(body, ensure_ascii=False).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    t0 = time.perf_counter()
    first = None
    usage: dict = {}
    timing: dict = {}
    text: list[str] = []
    calls: dict[int, dict] = {}
    finish = None
    n_chunks = 0
    try:
        resp_cm = urllib.request.urlopen(req, timeout=timeout)
    except urllib.error.HTTPError as e:
        if e.code == 400 and "stream_options" in body:
            # an engine that rejects the field is not a failure; retry once without it
            body.pop("stream_options")
            req = urllib.request.Request(
                base.rstrip("/") + "/chat/completions",
                data=json.dumps(body, ensure_ascii=False).encode(),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            resp_cm = urllib.request.urlopen(req, timeout=timeout)
        else:
            raise
    with resp_cm as resp:
        for line in resp:
            line = line.strip()
            if not line.startswith(b"data:"):
                continue
            raw = line[5:].strip()
            if raw == b"[DONE]":
                break
            try:
                item = json.loads(raw)
            except json.JSONDecodeError:
                continue
            if isinstance(item.get("usage"), dict):
                usage.update(item["usage"])
            if isinstance(item.get("timings"), dict):
                timing.update(item["timings"])
            for choice in item.get("choices") or []:
                if choice.get("finish_reason"):
                    finish = choice["finish_reason"]
                delta = choice.get("delta") or {}
                for part in delta.get("tool_calls") or []:
                    slot = calls.setdefault(part.get("index", 0), {"function": {"name": "", "arguments": ""}})
                    fn = part.get("function") or {}
                    if fn.get("name"):
                        slot["function"]["name"] = fn["name"]
                    if fn.get("arguments"):
                        slot["function"]["arguments"] += fn["arguments"]
                    if part.get("id"):
                        slot["id"] = part["id"]
                    if part.get("type"):
                        slot["type"] = part["type"]
                piece = delta.get("content") or delta.get("reasoning_content") or ""
                if piece:
                    n_chunks += 1
                    if first is None:
                        first = time.perf_counter()
                    text.append(piece)
    end = time.perf_counter()
    prompt_tokens = usage.get("prompt_tokens") or timing.get("prompt_n")
    completion_tokens = usage.get("completion_tokens") or timing.get("predicted_n")
    return {
        "ttft_s": round(first - t0, 3) if first else None,
        "wall_s": round(end - t0, 3),
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "prefill_tps_client": round(prompt_tokens / (first - t0), 1) if prompt_tokens and first else None,
        "decode_tps_client": (
            round((completion_tokens - 1) / (end - first), 2)
            if completion_tokens and completion_tokens > 1 and first else None
        ),
        "prefill_tps_server": timing.get("prompt_per_second"),
        "decode_tps_server": timing.get("predicted_per_second"),
        "prompt_ms_server": timing.get("prompt_ms"),
        "predicted_ms_server": timing.get("predicted_ms"),
        "cache_n": timing.get("cache_n", usage.get("prompt_tokens_details", {}).get("cached_tokens")),
        "draft_n": timing.get("draft_n"),
        "draft_n_accepted": timing.get("draft_n_accepted"),
        "finish_reason": finish,
        "chunks": n_chunks,
        "chars": sum(len(s) for s in text),
        "text": "".join(text),
        "tool_calls": [calls[k] for k in sorted(calls)],
        "usage": usage,
        "timings": timing,
    }


def model_of(base: str) -> str:
    with urllib.request.urlopen(base.rstrip("/") + "/models", timeout=30) as r:
        return json.load(r)["data"][0]["id"]


def salt() -> str:
    return f"{os.getpid()}-{time.time_ns()}"


def chars_per_token(base: str, model: str, text: str) -> float:
    """Measure the corpus in the engine's own tokenizer instead of assuming a ratio.

    A guessed ratio silently turns "262144 tokens" into "354K tokens", which the server
    rejects. One cheap probe makes the sizing a measurement rather than an estimate.
    """
    sent = filler(text, 20000, "calibration")  # big enough that the ratio matches a real long prompt
    r = stream(base, {
        "model": model,
        "messages": [{"role": "user", "content": sent}],
        "max_tokens": 1,
        "temperature": 0,
        "enable_thinking": False,
    })
    if not r["prompt_tokens"]:
        sys.exit("calibration failed: the engine reported no prompt token count")
    return len(sent) / r["prompt_tokens"]


PROV: dict[str, str | None] = {"phase": None, "digest": None}


def emit(payload: dict, out: str | None) -> None:
    """Attach the provenance that makes a record placeable, then write it.

    A record that does not say which phase and which image digest produced it cannot be
    used in the report, so the client refuses to write one.
    """
    payload = dict(payload)
    payload["provenance"] = {"phase": PROV["phase"], "digest": PROV["digest"]}
    if out:
        Path(out).parent.mkdir(parents=True, exist_ok=True)
        Path(out).write_text(json.dumps(payload, ensure_ascii=False, indent=2))
        print(f"saved {out}")
    else:
        print(json.dumps(payload, ensure_ascii=False, indent=2))


def cmd_ctx(a) -> None:
    text = corpus_text(Path(a.corpus))
    model = a.model or model_of(a.base)
    cpt = chars_per_token(a.base, model, text)
    print(f"calibration: {cpt:.3f} chars/token, measured on this tokenizer")
    runs = []
    for size in [int(s) for s in a.sizes.split(",")]:
        factor, r, last = 0.96, None, None
        for attempt in (1, 2):
            approx = int(size * cpt * factor)
            body = {
                "model": model,
                "messages": [{"role": "user", "content": filler(text, approx, salt()) + "\n\nReply with the single word: ok"}],
                "max_tokens": a.max_tokens,
                "temperature": 0,
                "enable_thinking": False,
            }
            try:
                r = stream(a.base, body)
                break
            except urllib.error.HTTPError as e:
                last = f"HTTP {e.code}: {e.read()[:300].decode(errors='replace')}"
                if e.code == 400 and attempt == 1:
                    factor = 0.88
                    print(f"{size:>7} -> refused at factor {0.96}, retrying smaller: {last[:120]}")
                    continue
                break
        if r is None:
            runs.append({"requested_tokens": size, "error": last})
            print(runs[-1])
            continue
        r["requested_tokens"] = size
        r["sizing_factor"] = factor
        r["chars_per_token"] = round(cpt, 3)
        r.pop("text", None)
        runs.append(r)
        print(f"{size:>7} -> prompt={r['prompt_tokens']} cache={r['cache_n']} ttft={r['ttft_s']}s "
              f"prefill_server={r['prefill_tps_server']} prefill_client={r['prefill_tps_client']}")
    emit({"label": a.label, "base": a.base, "model": model, "kind": "ctx", "runs": runs}, a.out)


def cmd_needle(a) -> None:
    text = corpus_text(Path(a.corpus))
    model = a.model or model_of(a.base)
    cpt = chars_per_token(a.base, model, text)
    target_chars = int(a.target * cpt * 0.96)
    slot, who = f"cabinet-{salt()[:6]}", f"engineer-{salt()[-6:]}"
    facts = [(NEEDLE.format(slot=slot, who=who)).strip(), (NEEDLE.format(slot=slot, who=who)).strip()]
    positions = [float(p) for p in a.at.split(",")]
    pieces, cursor = [], 0
    for i, pos in enumerate(positions):
        cut = int(target_chars * pos)
        pieces.append(filler(text, cut - cursor, f"{salt()}-{i}"))
        pieces.append("\n" + facts[i] + "\n")
        cursor = cut
    pieces.append(filler(text, target_chars - cursor, f"{salt()}-tail"))
    doc = "".join(pieces)
    runs = []
    for question, _ in QUESTIONS:
        body = {
            "model": model,
            "messages": [
                {"role": "user", "content": doc + f"\n\nQuestion: {question} Answer with the exact string only."}
            ],
            "max_tokens": 64,
            "temperature": 0,
            "enable_thinking": False,
        }
        r = stream(a.base, body)
        answer = r["text"].strip()
        runs.append({
            "question": question,
            "answer": answer[:200],
            "found": (slot in answer) or (who in answer),
            "prompt_tokens": r["prompt_tokens"],
            "ttft_s": r["ttft_s"],
            "wall_s": r["wall_s"],
        })
        print(("PASS " if runs[-1]["found"] else "MISS ") + question + " -> " + answer[:80].replace("\n", " "))
    emit({"label": a.label, "base": a.base, "model": model, "kind": "needle",
          "positions": positions, "needles": {"slot": slot, "who": who}, "runs": runs}, a.out)


def cmd_tool(a) -> None:
    model = a.model or model_of(a.base)
    tools = [{
        "type": "function",
        "function": {
            "name": "read_room_temperature",
            "description": "Read the temperature of one room in degrees Celsius.",
            "parameters": {
                "type": "object",
                "properties": {"room": {"type": "string", "description": "Room name"}},
                "required": ["room"],
            },
        },
    }]
    body = {
        "model": model,
        "messages": [{"role": "user", "content": "What is the temperature in the kitchen right now?"}],
        "tools": tools,
        "tool_choice": "auto",
        "temperature": 0,
        "max_tokens": 256,
    }
    r = stream(a.base, body)
    calls = r["tool_calls"]
    emit({"label": a.label, "base": a.base, "model": model, "kind": "tool",
          "called": bool(calls), "tool_calls": calls,
          "first_arguments": (calls[0].get("function") or {}).get("arguments") if calls else None,
          "text_head": r["text"][:300], "wall_s": r["wall_s"], "finish_reason": r["finish_reason"]}, a.out)
    print(("CALLED " if calls else "NO CALL ") + json.dumps(calls[:1])[:200])


def cmd_conc(a) -> None:
    text = corpus_text(Path(a.corpus))
    model = a.model or model_of(a.base)
    cpt = chars_per_token(a.base, model, text)
    approx = int(a.prompt_tokens * cpt * 0.96)
    results: list[dict | None] = [None] * a.n
    lock = threading.Lock()
    barrier = threading.Barrier(a.n)
    health_samples: list[dict] = []
    stop_sampler = threading.Event()
    health_url = a.base.rstrip("/").removesuffix("/v1") + "/health"

    def sample_health() -> None:
        """Prove the engine really ran the requests together, rather than inferring it."""
        while not stop_sampler.is_set():
            try:
                with urllib.request.urlopen(health_url, timeout=2) as r:
                    doc = json.load(r)
                keep = {k: doc[k] for k in ("busy", "in_flight", "queued", "slots", "longest_wait_s")
                        if k in doc}
                if keep:
                    with lock:
                        health_samples.append(keep)
            except Exception:  # noqa: BLE001 - an engine without /health is a finding, not an error
                pass
            stop_sampler.wait(0.5)

    t_start = time.perf_counter()

    def one(i: int) -> None:
        body = {
            "model": model,
            "messages": [{"role": "user", "content": filler(text, approx, f"{salt()}-conc{i}")
                          + "\n\nSummarize the text above in about 200 words."}],
            "max_tokens": a.max_tokens,
            "temperature": 0,
            "enable_thinking": False,
        }
        barrier.wait()
        try:
            results[i] = stream(a.base, body)
        except Exception as e:  # noqa: BLE001 - recorded, not raised
            results[i] = {"error": repr(e)}

    sampler = threading.Thread(target=sample_health, daemon=True)
    sampler.start()
    threads = [threading.Thread(target=one, args=(i,)) for i in range(a.n)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    wall = time.perf_counter() - t_start
    stop_sampler.set()
    sampler.join(timeout=3)
    ok = [r for r in results if r and "error" not in r]
    total_out = sum((r.get("completion_tokens") or 0) for r in ok)
    peak_in_flight = max((s.get("in_flight") or 0) for s in health_samples) if health_samples else None
    summary = {
        "n": a.n,
        "requested_prompt_tokens": a.prompt_tokens,
        "max_tokens": a.max_tokens,
        "wall_s": round(wall, 2),
        "completed": len(ok),
        "errors": [r["error"] for r in results if r and "error" in r],
        "aggregate_decode_tps": round(total_out / wall, 2) if wall > 0 else None,
        "requests_that_hit_prompt_cache": sum(1 for r in ok if (r.get("cache_n") or 0) > 0),
        "ttft_s": sorted(round(r["ttft_s"], 3) for r in ok if r.get("ttft_s") is not None),
        "per_request_decode_tps": [r.get("decode_tps_client") for r in ok],
        "per_request_decode_tps_server": [r.get("decode_tps_server") for r in ok],
        "health_available": bool(health_samples),
        "peak_in_flight": peak_in_flight,
        "health_samples": len(health_samples),
    }
    if summary["ttft_s"]:
        summary["ttft_p50"] = statistics.median(summary["ttft_s"])
        summary["ttft_p95"] = summary["ttft_s"][min(len(summary["ttft_s"]) - 1, math.ceil(0.95 * len(summary["ttft_s"])) - 1)]
    emit({"label": a.label, "base": a.base, "model": model, "kind": "conc",
          "summary": summary,
          "health_timeline": health_samples,
          "runs": [{k: v for k, v in (r or {}).items() if k != "text"} for r in results]}, a.out)
    print(json.dumps({k: v for k, v in summary.items() if k != "ttft_s"}, indent=2))


def png_with_square(size: int = 128, square: int = 64, rgb: tuple[int, int, int] = (220, 20, 20)) -> bytes:
    """A white PNG with a solid coloured square in the middle, encoded with the stdlib.

    Generated rather than loaded so the vision check is reproducible anywhere and the
    expected answer is not something a reader has to take on trust.
    """
    bg, fg = (255, 255, 255), rgb
    off = (size - square) // 2
    rows = []
    for y in range(size):
        row = bytearray(b"\x00")  # filter type 0
        for x in range(size):
            inside = off <= x < off + square and off <= y < off + square
            row.extend(fg if inside else bg)
        rows.append(bytes(row))
    raw = b"".join(rows)

    def chunk(tag: bytes, data: bytes) -> bytes:
        return (struct.pack(">I", len(data)) + tag + data
                + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF))

    ihdr = struct.pack(">IIBBBBB", size, size, 8, 2, 0, 0, 0)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr)
            + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b""))


def cmd_image(a) -> None:
    """One image input. Vision is loaded on both engines, so it should be exercised once."""
    model = a.model or model_of(a.base)
    data = base64.b64encode(png_with_square()).decode()
    body = {
        "model": model,
        "messages": [{
            "role": "user",
            "content": [
                {"type": "text", "text": "What colour is the square in this image? Answer with one word."},
                {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{data}"}},
            ],
        }],
        "max_tokens": 32,
        "temperature": 0,
        "enable_thinking": False,
    }
    try:
        r = stream(a.base, body)
    except urllib.error.HTTPError as e:
        emit({"label": a.label, "base": a.base, "model": model, "kind": "image",
              "status": "error", "error": f"HTTP {e.code}: {e.read()[:400].decode(errors='replace')}"}, a.out)
        print("image input rejected by the engine, recorded as such")
        return
    answer = r["text"].strip()
    emit({"label": a.label, "base": a.base, "model": model, "kind": "image",
          "status": "answered", "expected": "red", "answer": answer[:200],
          "pass": "red" in answer.lower(), "ttft_s": r["ttft_s"], "wall_s": r["wall_s"]}, a.out)
    print(("PASS " if "red" in answer.lower() else "FAIL ") + answer[:80])


def cmd_reuse(a) -> None:
    """What a repeated prefix costs: the same document, asked again.

    An agent turn re-sends its whole history, so the daily feel of an engine is set by
    what a cached prefix costs, not by a cold prefill. Three requests: a cold one, the
    same document with a different tail, then a second cold one as a control, so the
    speedup can be attributed to reuse rather than to anything else.
    """
    text = corpus_text(Path(a.corpus))
    model = a.model or model_of(a.base)
    cpt = chars_per_token(a.base, model, text)
    approx = int(a.prompt_tokens * cpt * 0.96)

    def ask(doc: str, tail: str) -> dict:
        r = stream(a.base, {
            "model": model,
            "messages": [{"role": "user", "content": doc + "\n\n" + tail}],
            "max_tokens": a.max_tokens,
            "temperature": 0,
            "enable_thinking": False,
        })
        r.pop("text", None)
        r["tail"] = tail
        return r

    shared = filler(text, approx, salt())
    cold_1 = ask(shared, "Reply with the single word: first")
    reuse = ask(shared, "Reply with the single word: second")
    cold_2 = ask(filler(text, approx, salt()), "Reply with the single word: third")

    def brief(r: dict) -> dict:
        return {k: r.get(k) for k in ("prompt_tokens", "cache_n", "ttft_s", "wall_s",
                                      "prefill_tps_server", "finish_reason", "tail")}

    summary = {
        "cold_1": brief(cold_1),
        "reuse": brief(reuse),
        "cold_2": brief(cold_2),
        "reused_prompt_tokens": (reuse.get("prompt_tokens") or 0) - (reuse.get("cache_n") or 0),
        "reuse_ttft_ratio_vs_cold1": (
            round(reuse["ttft_s"] / cold_1["ttft_s"], 4)
            if reuse.get("ttft_s") and cold_1.get("ttft_s") else None
        ),
    }
    emit({"label": a.label, "base": a.base, "model": model, "kind": "reuse",
          "summary": summary, "runs": [cold_1, reuse, cold_2]}, a.out)
    print(json.dumps(summary, indent=2))


def cmd_oneshot(a) -> None:
    """One request, one file. Used for the artifact run: no tools, no retry, no repair."""
    model = a.model or model_of(a.base)
    prompt = Path(a.prompt_file).read_text(encoding="utf-8").strip() if a.prompt_file else a.prompt
    body = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": a.max_tokens,
        "temperature": 0,
        "enable_thinking": False,
    }
    r = stream(a.base, body)
    out_html = Path(a.out_html)
    out_html.parent.mkdir(parents=True, exist_ok=True)
    out_html.write_text(r["text"], encoding="utf-8")
    meta = {k: v for k, v in r.items() if k != "text"}
    meta.update({
        "label": a.label,
        "base": a.base,
        "model": model,
        "kind": "oneshot",
        "artifact": a.out_html,
        "prompt_file": a.prompt_file,
        "max_tokens": a.max_tokens,
        "truncated": r["finish_reason"] == "length",
        "looks_complete_html": "</html>" in r["text"].lower(),
        "artifact_sha256": __import__("hashlib").sha256(r["text"].encode()).hexdigest(),
    })
    emit(meta, a.out)
    print(f"{a.out_html}: {meta['chars']} chars, finish={meta['finish_reason']}, "
          f"truncated={meta['truncated']}, complete_html={meta['looks_complete_html']}")


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--phase", required=True, help="phase directory this record belongs to")
    p.add_argument("--digest", required=True, help="image digest of the engine that produced it")
    p.add_argument("--base", default="http://127.0.0.1:8731/v1")
    p.add_argument("--model", default=None, help="default: first id from /v1/models")
    p.add_argument("--label", default="engine")
    p.add_argument("--out", default=None)
    p.add_argument("--corpus", default=str(DEFAULT_CORPUS))
    sub = p.add_subparsers(dest="cmd", required=True)

    c = sub.add_parser("ctx", help="prefill + TTFT at exact prompt sizes")
    c.add_argument("--sizes", default="32000,128000,262144")
    c.add_argument("--max-tokens", type=int, default=1)
    c.set_defaults(fn=cmd_ctx)

    n = sub.add_parser("needle", help="two facts at two depths, one request each")
    n.add_argument("--target", type=int, default=250000)
    n.add_argument("--at", default="0.40,0.85")
    n.set_defaults(fn=cmd_needle)

    t = sub.add_parser("tool", help="one forced-by-choice tool call")
    t.set_defaults(fn=cmd_tool)

    q = sub.add_parser("conc", help="N requests released simultaneously")
    q.add_argument("--n", type=int, default=4)
    q.add_argument("--prompt-tokens", type=int, default=8000)
    q.add_argument("--max-tokens", type=int, default=512)
    q.set_defaults(fn=cmd_conc)

    i = sub.add_parser("image", help="one image input, generated PNG with a known answer")
    i.set_defaults(fn=cmd_image)

    u = sub.add_parser("reuse", help="cold prefills and a repeated-prefix follow-up")
    u.add_argument("--prompt-tokens", type=int, default=100000)
    u.add_argument("--max-tokens", type=int, default=16)
    u.set_defaults(fn=cmd_reuse)

    o = sub.add_parser("oneshot", help="one request written verbatim to a file (artifact run)")
    o.add_argument("--prompt-file", default=None)
    o.add_argument("--prompt", default=None)
    o.add_argument("--max-tokens", type=int, default=16384)
    o.add_argument("--out-html", required=True)
    o.set_defaults(fn=cmd_oneshot)

    a = p.parse_args()
    if not a.digest or a.digest == "unknown":
        sys.exit("--digest is required and must be a real image digest: a record without it "
                 "cannot be placed in the report")
    PROV["phase"], PROV["digest"] = a.phase, a.digest
    a.fn(a)


if __name__ == "__main__":
    main()
