#!/usr/bin/env python3
"""Thirteen checks whose answers a script can decide, run against one engine at a time.

This is not a quality verdict and cannot be one: the two engines load different
quantizations of the same model. What it can decide is whether a piece of output is
*usable*: does the number match, does the function run, are the stated constraints
obeyed, is the JSON the shape that was asked for. A reader who wants to judge the prose
can open the artifact pages instead; nothing here scores taste.

    python3 tools/quality.py --base http://127.0.0.1:8731/v1 --label halogen --out runs/quality/halogen.json
    python3 tools/quality.py --compare runs/quality/halogen.json runs/quality/kyojin.json

Every case is one request: temperature 0, thinking off, a fixed max_tokens. Failures are
recorded with the output that failed, because the interesting number afterwards is the
failure rate, not the mean.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

# ---------------------------------------------------------------- checkers


def last_number(text: str):
    """The last number in the response, as a float, or None.

    Models narrate before answering, so the check is on the final number rather than on
    the text containing the right digits somewhere.
    """
    nums = re.findall(r"-?\d[\d,]*(?:\.\d+)?", text)
    if not nums:
        return None
    return float(nums[-1].replace(",", ""))


def check_last_number(text: str, expected: str) -> tuple[bool, str]:
    got = last_number(text)
    if got is None:
        return False, "no number in the response"
    return abs(got - float(expected)) < 1e-9, f"last number {got:g}, expected {float(expected):g}"


def check_last_time(text: str, expected: str) -> tuple[bool, str]:
    times = re.findall(r"\b([01]?\d|2[0-3]):[0-5]\d\b", text)
    found = re.findall(r"\b(?:[01]?\d|2[0-3]):[0-5]\d\b", text)
    if not found:
        return False, "no HH:MM in the response"
    return found[-1].strip() == expected, f"last time {found[-1]}, expected {expected}"


def strip_fences(text: str) -> str:
    m = re.search(r"```(?:python|py)?\s*\n(.*?)(?:```|$)", text, re.S)
    return (m.group(1) if m else text).strip()


def check_python(text: str, script: str) -> tuple[bool, str]:
    code = strip_fences(text)
    if not code:
        return False, "no code in the response"
    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp)
        (d / "mod.py").write_text(code, encoding="utf-8")
        (d / "check.py").write_text(script, encoding="utf-8")
        p = subprocess.run([sys.executable, "check.py"], cwd=d, capture_output=True, text=True, timeout=120)
        if p.returncode == 0:
            return True, "all assertions passed"
        return False, (p.stderr or p.stdout).strip().splitlines()[-1][:200] if (p.stderr or p.stdout).strip() else "check failed"


CONSTRAINT_SCRIPT_WORDS = re.compile(r"\S+")


def check_bullets_haiku(text: str) -> tuple[bool, str]:
    lines = [ln.rstrip() for ln in text.replace("\r", "").split("\n")]
    bullets = [ln for ln in lines if ln.lstrip().startswith("- ")]
    problems = []
    if len(bullets) != 5:
        problems.append(f"{len(bullets)} bullets, expected 5")
    for i, b in enumerate(bullets, 1):
        body = b.lstrip()[2:].strip()
        words = CONSTRAINT_SCRIPT_WORDS.findall(body)
        if len(words) > 12:
            problems.append(f"bullet {i} has {len(words)} words")
        if re.search(r"\band\b", body, re.I):
            problems.append(f"bullet {i} contains 'and'")
    if bullets:
        last_bullet = max(i for i, ln in enumerate(lines) if ln.lstrip().startswith("- "))
        tail = [ln for ln in lines[last_bullet + 1:] if ln.strip()]
        if len(tail) != 3:
            problems.append(f"{len(tail)} haiku lines after the bullets, expected 3")
    else:
        problems.append("no bullets")
    return (not problems), ("; ".join(problems) if problems else "5 bullets, word caps, no 'and', 3 haiku lines")


def check_json_shape(text: str, expected: dict) -> tuple[bool, str]:
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        return False, "no JSON object in the response"
    try:
        doc = json.loads(m.group(0))
    except json.JSONDecodeError as e:
        return False, f"JSON does not parse: {e}"
    if set(doc) != set(expected):
        return False, f"keys {sorted(doc)} != {sorted(expected)}"
    wrong = {k: doc[k] for k in expected if doc[k] != expected[k]}
    return (not wrong), (f"wrong values {wrong}, expected {expected}" if wrong else "exact match")


# ---------------------------------------------------------------- the cases

SENTENCE = "Local engines make quiet afternoons pleasant."

CASES: list[dict] = [
    # 1-8: one number, decided by arithmetic
    {"id": "r-bat-ball", "kind": "reasoning", "max_tokens": 384,
     "prompt": "A bat and a ball cost $1.10 together. The bat costs $1.00 more than the ball. "
               "How much does the ball cost? Answer with the price only.",
     "check": ("last_number", "0.05")},
    {"id": "r-widgets", "kind": "reasoning", "max_tokens": 384,
     "prompt": "If 5 machines take 5 minutes to make 5 widgets, how many minutes would 100 machines "
               "take to make 100 widgets? Answer with the number of minutes only.",
     "check": ("last_number", "5")},
    {"id": "r-trailing-zeros", "kind": "reasoning", "max_tokens": 512,
     "prompt": "How many trailing zeros does 100! (one hundred factorial) have? Answer with the number only.",
     "check": ("last_number", "24")},
    {"id": "r-painted-cube", "kind": "reasoning", "max_tokens": 384,
     "prompt": "A cube is painted on all six faces and then cut into 27 equal smaller cubes. "
               "How many of the small cubes have exactly two painted faces? Answer with the number only.",
     "check": ("last_number", "12")},
    {"id": "r-geometric", "kind": "reasoning", "max_tokens": 384,
     "prompt": "What is the 10th term of the sequence 2, 6, 18, 54, ...? Answer with the number only.",
     "check": ("last_number", "39366")},
    {"id": "r-arrival-time", "kind": "reasoning", "max_tokens": 384,
     "prompt": "A train leaves at 14:45 and the journey takes 3 hours 50 minutes. "
               "At what time does it arrive? Answer in 24-hour HH:MM only.",
     "check": ("last_time", "18:35")},
    {"id": "r-sum-not-div3", "kind": "reasoning", "max_tokens": 512,
     "prompt": "What is the sum of all integers from 1 to 100 inclusive that are not divisible by 3? "
               "Answer with the number only.",
     "check": ("last_number", "3367")},
    {"id": "r-three-items", "kind": "reasoning", "max_tokens": 384,
     "prompt": "A shop sells three items. Two of them cost the same, and the third costs 20 more than "
               "each of those two. The total is 80. How much does each of the two equal-priced items cost? "
               "Answer with the number only.",
     "check": ("last_number", "20")},

    # 9-11: code that has to run, with assertions we wrote, not the model
    {"id": "c-iso-duration", "kind": "code", "max_tokens": 1536,
     "prompt": "Write a Python function `parse_duration(s)` that parses an ISO-8601 duration string into a "
               "`datetime.timedelta`. Support weeks, days, hours, minutes and seconds. Reply with the code only, "
               "no explanation.",
     "check": ("python", """from datetime import timedelta
from mod import parse_duration
assert parse_duration("PT30S") == timedelta(seconds=30)
assert parse_duration("PT1H30M") == timedelta(hours=1, minutes=30)
assert parse_duration("P2W") == timedelta(days=14)
assert parse_duration("P3DT4H5M6S") == timedelta(days=3, hours=4, minutes=5, seconds=6)
assert parse_duration("P0D") == timedelta(0)
""")},
    {"id": "c-rle-roundtrip", "kind": "code", "max_tokens": 1536,
     "prompt": "Write two Python functions, `rle_encode(s)` and `rle_decode(s)`, implementing run-length "
               "encoding for text. `rle_decode(rle_encode(x))` must return `x` exactly for any string. "
               "Reply with the code only, no explanation.",
     "check": ("python", """from mod import rle_encode, rle_decode
for x in ["aaabbbcccd", "", "a", "ab", "wwwwwwwwwwww", "AbC123!"]:
    assert rle_decode(rle_encode(x)) == x, (x, rle_encode(x), rle_decode(rle_encode(x)))
""")},
    {"id": "c-csv-line", "kind": "code", "max_tokens": 1536,
     "prompt": "Write a Python function `parse_csv_line(line)` that splits one CSV line into a list of fields, "
               "honouring double-quoted fields that may contain commas, and representing an empty field as an "
               "empty string. Use only the standard library. Reply with the code only, no explanation.",
     "check": ("python", """from mod import parse_csv_line
assert parse_csv_line('a,b,"c,d",e') == ['a', 'b', 'c,d', 'e']
assert parse_csv_line('a,,b') == ['a', '', 'b']
assert parse_csv_line('""') == ['']
assert parse_csv_line('x,"y"') == ['x', 'y']
""")},

    # 12-13: instructions with hard edges, where quantization damage shows first
    {"id": "d-bullets-haiku", "kind": "constraint", "max_tokens": 1024,
     "prompt": "Write exactly 5 bullet points. Each bullet must start with '- ', must contain at most 12 words, "
               "and must not contain the word 'and'. After the bullets, leave one blank line, then write a haiku "
               "of exactly 3 lines about rain. Output nothing else, no heading, no closing remark.",
     "check": ("bullets_haiku", None)},
    {"id": "d-json-shape", "kind": "constraint", "max_tokens": 512,
     "prompt": f'Return only a JSON object, no prose and no code fence, with exactly three keys: "vowels" '
               f'(integer, count of aeiou, case-insensitive), "words" (integer), "longest_word" (string), '
               f'describing this sentence: "{SENTENCE}"',
     "check": ("json_shape", {"vowels": 17, "words": 6, "longest_word": "afternoons"})},
]


# ---------------------------------------------------------------- runner

def model_of(base: str) -> str:
    with urllib.request.urlopen(base.rstrip("/") + "/models", timeout=30) as r:
        return json.load(r)["data"][0]["id"]


def ask(base: str, model: str, prompt: str, max_tokens: int) -> dict:
    body = {"model": model, "messages": [{"role": "user", "content": prompt}],
            "max_tokens": max_tokens, "temperature": 0, "enable_thinking": False}
    req = urllib.request.Request(base.rstrip("/") + "/chat/completions",
                                 data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"}, method="POST")
    t0 = time.perf_counter()
    with urllib.request.urlopen(req, timeout=900) as resp:
        doc = json.load(resp)
    wall = time.perf_counter() - t0
    choice = (doc.get("choices") or [{}])[0]
    text = (choice.get("message") or {}).get("content") or ""
    return {"text": text, "finish_reason": choice.get("finish_reason"),
            "usage": doc.get("usage") or {}, "timings": doc.get("timings") or {},
            "wall_s": round(wall, 2)}


def apply_check(check: tuple[str, object], text: str) -> tuple[bool, str]:
    """Run the checker a case names. One table, so adding a checker is one entry."""
    kind, argument = check
    table = {
        "last_number": lambda t: check_last_number(t, argument),
        "last_time": lambda t: check_last_time(t, argument),
        "python": lambda t: check_python(t, argument),
        "bullets_haiku": lambda t: check_bullets_haiku(t),
        "json_shape": lambda t: check_json_shape(t, argument),
    }
    if kind not in table:
        return False, f"unknown checker {kind}"
    return table[kind](text)


def run_case(base: str, model: str, case: dict) -> dict:
    t0 = time.perf_counter()
    try:
        r = ask(base, model, case["prompt"], case["max_tokens"])
        err = None
    except urllib.error.HTTPError as e:
        return {"id": case["id"], "kind": case["kind"], "pass": False, "detail": f"HTTP {e.code}",
                "output": "", "wall_s": round(time.perf_counter() - t0, 2), "error": "http"}
    ok, detail = apply_check(case["check"], r["text"])
    return {"id": case["id"], "kind": case["kind"], "pass": ok, "detail": detail,
            "output": r["text"], "finish_reason": r["finish_reason"],
            "completion_tokens": (r["usage"] or {}).get("completion_tokens"),
            "wall_s": r["wall_s"], "error": err}


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--base", default="http://127.0.0.1:8731/v1")
    p.add_argument("--label", default="engine")
    p.add_argument("--out", default=None)
    p.add_argument("--only", default=None, help="comma separated case ids")
    p.add_argument("--phase", default=None, help="phase directory to record provenance into")
    p.add_argument("--digest", default=None, help="image digest of the engine under test")
    p.add_argument("--compare", nargs=2, default=None)
    a = p.parse_args()

    if a.compare:
        rows = []
        for name in a.compare:
            doc = json.loads(Path(name).read_text())
            rows.append(doc)
        ids = [c["id"] for c in CASES]
        print(f"{'case':<18}{'kind':<12}" + "".join(f"{d['label']:>12}" for d in rows))
        for cid in ids:
            cells = []
            for d in rows:
                r = next((x for x in d["runs"] if x["id"] == cid), None)
                cells.append("PASS" if r and r["pass"] else "FAIL")
            kind = next(c["kind"] for c in CASES if c["id"] == cid)
            print(f"{cid:<18}{kind:<12}" + "".join(f"{c:>12}" for c in cells))
        print()
        for d in rows:
            n = len(d["runs"])
            k = sum(1 for x in d["runs"] if x["pass"])
            print(f"{d['label']:>14}: {k}/{n} passed")
        return

    model = model_of(a.base)
    print(f"{a.label}: {a.base} model={model}, {len(CASES)} cases")
    runs = []
    for case in CASES:
        if a.only and case["id"] not in a.only.split(","):
            continue
        r = run_case(a.base, model, case)
        runs.append(r)
        print(f"  {'PASS' if r['pass'] else 'FAIL'}  {r['id']:<18} {r['detail'][:90]}")
    doc = {"label": a.label, "base": a.base, "model": model, "kind": "quality", "runs": runs,
           "provenance": {"phase": a.phase, "digest": a.digest}}
    passed = sum(1 for r in runs if r["pass"])
    doc["summary"] = {"cases": len(runs), "passed": passed, "failed": len(runs) - passed,
                      "failure_rate": round((len(runs) - passed) / max(1, len(runs)), 3)}
    if a.out:
        Path(a.out).parent.mkdir(parents=True, exist_ok=True)
        Path(a.out).write_text(json.dumps(doc, ensure_ascii=False, indent=2))
        print(f"saved {a.out}")
    # A quality run is a phase like any other: it gets a directory holding the record of
    # which image produced it, so the summary never has to borrow a digest from elsewhere.
    if a.phase and a.digest:
        phase_dir = Path(a.out or ".").resolve().parent.parent / "runs" / a.phase
        phase_dir.mkdir(parents=True, exist_ok=True)
        env = phase_dir / "env.txt"
        if not env.is_file():
            env.write_text(
                f"timestamp {time.strftime('%Y-%m-%dT%H:%M:%S%z')}\n"
                f"quality_digest {a.digest}\n"
                f"quality_label {a.label}\n"
                f"quality_results {a.out}\n")
            print(f"recorded provenance in {env}")
    print(f"{passed}/{len(runs)} passed")


if __name__ == "__main__":
    main()
