#!/usr/bin/env python3
"""A bounded, identical tool loop for both engines — the agent-side artifact run.

The maintainer's gallery rows were produced by Hermes, which is not published, so this
cannot be compared to those timings. What it can do is put both engines in the *same*
harness with the *same* budget and record what came out: did a page get written, how
many tool calls did it take, how long did it take, and does the page depend on a CDN.

    python3 tools/agentrun.py --base http://127.0.0.1:8732/v1 \
        --prompt-file docs/prompts/hexagon.txt \
        --out-html runs/kyojin-s1/artifact-hexagon.html \
        --out-meta runs/kyojin-s1/artifact-hexagon.json

The loop gives the model exactly two tools: `write_file` and `finish`. It stops on the
first `finish`, at `--max-turns`, or at the wall cap, and records which one stopped it.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import time
import urllib.error
import urllib.request
from pathlib import Path

SYSTEM = (
    "You are a coding agent. You have two tools: write_file to write a file, and finish to "
    "declare the work complete. Write the requested page by calling write_file with the whole "
    "HTML document as `content`. Call finish only after the file is written. Do not explain."
)

TOOLS = [
    {"type": "function", "function": {
        "name": "write_file",
        "description": "Write a file with the given content, replacing it if it exists.",
        "parameters": {"type": "object",
                       "properties": {"path": {"type": "string"},
                                      "content": {"type": "string"}},
                       "required": ["path", "content"]}}},
    {"type": "function", "function": {
        "name": "finish",
        "description": "Declare the work finished.",
        "parameters": {"type": "object",
                       "properties": {"summary": {"type": "string"}},
                       "required": []}}},
]


def post(base: str, body: dict, timeout: float = 900) -> dict:
    req = urllib.request.Request(base.rstrip("/") + "/chat/completions",
                                 data=json.dumps(body, ensure_ascii=False).encode(),
                                 headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)


def tool_calls_of(doc: dict) -> list[dict]:
    msg = ((doc.get("choices") or [{}])[0].get("message") or {})
    calls = msg.get("tool_calls") or []
    if calls:
        return calls
    # some engines put the call inside the text as qwen-xml; recover it rather than fail
    text = msg.get("content") or ""
    out = []
    for m in re.finditer(r"<function=(\w+)>(.*?)</function>", text, re.S):
        args = {}
        for pm in re.finditer(r"<parameter=(\w+)>(.*?)</parameter>", m.group(2), re.S):
            args[pm.group(1)] = pm.group(2)
        out.append({"id": f"xml-{len(out)}", "type": "function",
                    "function": {"name": m.group(1), "arguments": json.dumps(args)}})
    return out


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--base", default="http://127.0.0.1:8732/v1")
    p.add_argument("--model", default=None)
    p.add_argument("--prompt-file", required=True)
    p.add_argument("--out-html", required=True)
    p.add_argument("--out-meta", required=True)
    p.add_argument("--label", default="engine")
    p.add_argument("--max-turns", type=int, default=8)
    p.add_argument("--wall-cap", type=int, default=600)
    a = p.parse_args()

    if not a.model:
        with urllib.request.urlopen(a.base.rstrip("/") + "/models", timeout=30) as r:
            a.model = json.load(r)["data"][0]["id"]
    task = Path(a.prompt_file).read_text().strip()
    messages = [{"role": "system", "content": SYSTEM},
                {"role": "user", "content": task}]
    turns, calls, t0 = 0, [], time.perf_counter()
    written: dict[str, str] = {}
    stopped = "turns"
    transcript = []

    while turns < a.max_turns and time.perf_counter() - t0 < a.wall_cap:
        turns += 1
        try:
            doc = post(a.base, {"model": a.model, "messages": messages, "tools": TOOLS,
                                "tool_choice": "auto", "temperature": 0,
                                "max_tokens": 8192, "enable_thinking": False})
        except urllib.error.HTTPError as e:
            stopped = f"http {e.code}"
            transcript.append({"turn": turns, "error": f"HTTP {e.code}: {e.read()[:200].decode(errors='replace')}"})
            break
        msg = ((doc.get("choices") or [{}])[0].get("message") or {})
        tcs = tool_calls_of(doc)
        transcript.append({"turn": turns, "content": (msg.get("content") or "")[:400],
                           "calls": [{"name": c["function"]["name"],
                                      "args_bytes": len(c["function"].get("arguments") or "")}
                                     for c in tcs]})
        if not tcs:
            stopped = "no tool call"
            break
        messages.append({"role": "assistant", "content": msg.get("content") or "",
                         "tool_calls": tcs})
        done = False
        for c in tcs:
            name = c["function"]["name"]
            try:
                args = json.loads(c["function"].get("arguments") or "{}")
            except json.JSONDecodeError:
                args = {}
            calls.append(name)
            if name == "write_file":
                path = args.get("path") or "index.html"
                content = args.get("content") or ""
                written[Path(path).name] = content
                result = f"wrote {len(content)} chars to {path}"
            elif name == "finish":
                done = True
                result = "finished"
            else:
                result = f"unknown tool {name}"
            messages.append({"role": "tool", "tool_call_id": c.get("id", ""), "content": result})
        if done:
            stopped = "finish"
            break
        if time.perf_counter() - t0 >= a.wall_cap:
            stopped = "wall cap"

    elapsed = time.perf_counter() - t0
    page = ""
    for name in sorted(written, key=lambda k: (not k.endswith(".html"), -len(written[k]))):
        if name.endswith((".html", ".htm")):
            page = written[name]
            break
    if not page and written:
        page = max(written.values(), key=len)
    out_html = Path(a.out_html)
    out_html.parent.mkdir(parents=True, exist_ok=True)
    out_html.write_text(page)
    external = sorted(set(re.findall(r"https?://([^/\"'\s)]+)", page)))
    meta = {
        "label": a.label, "base": a.base, "model": a.model, "kind": "agent",
        "prompt_file": a.prompt_file, "stopped_by": stopped,
        "turns": turns, "tool_calls": len(calls), "calls": calls,
        "wall_s": round(elapsed, 1), "max_turns": a.max_turns, "wall_cap_s": a.wall_cap,
        "produced_page": bool(page),
        "bytes": len(page),
        "looks_complete_html": "</html>" in page.lower(),
        "external_refs": external,
        "files_written": sorted(written),
        "artifact_sha256": hashlib.sha256(page.encode()).hexdigest(),
        "transcript": transcript,
    }
    Path(a.out_meta).parent.mkdir(parents=True, exist_ok=True)
    Path(a.out_meta).write_text(json.dumps(meta, indent=2, ensure_ascii=False))
    print(f"{out_html}: {len(page)} bytes after {turns} turns, {len(calls)} calls, "
          f"{elapsed:.0f}s, stopped by {stopped}, external refs: {external or 'none'}")


if __name__ == "__main__":
    main()
