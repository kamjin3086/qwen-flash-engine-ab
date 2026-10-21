#!/usr/bin/env python3
"""One command: summary, report page, issue body, published tree.

The four surfaces come from one run so that they cannot disagree about what exists.

    python3 report/build.py                 # into results/, docs/ and build/publish
    python3 report/build.py --dest /tmp/x   # elsewhere
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent


def run(args: list[str]) -> None:
    print(f"$ {' '.join(args)}")
    p = subprocess.run(args, cwd=REPO)
    if p.returncode != 0:
        sys.exit(f"step failed: {' '.join(args)}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", default="runs")
    ap.add_argument("--summary", default="results/summary.json")
    ap.add_argument("--docs", default="docs")
    ap.add_argument("--issue", default="results/issue-body.md")
    ap.add_argument("--dest", default="build/publish")
    ap.add_argument("--skip-export", action="store_true")
    a = ap.parse_args()

    py = sys.executable
    run([py, "report/summary.py", "--runs", a.runs, "--out", a.summary])
    run([py, "report/render.py", "--summary", a.summary, "--out", a.docs, "--issue", a.issue])
    if not a.skip_export:
        run([py, "report/export.py", "--dest", a.dest, "--check"])


if __name__ == "__main__":
    main()
