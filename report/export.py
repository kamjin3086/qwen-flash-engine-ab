#!/usr/bin/env python3
"""Produce the published tree from the working repository.

The working repository stays private permanently (ADR-0003). What gets published is this
allowlisted copy, with the operator's home paths removed and a scan that refuses to emit
anything still containing one. It is a curated snapshot, never a mirror of history.

    python3 report/export.py --dest /tmp/publish            # build the tree
    python3 report/export.py --dest /tmp/publish --check     # build and fail on a leak
"""
from __future__ import annotations

import argparse
import fnmatch
import hashlib
import json
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import privacy  # noqa: E402  the one check, shared with the report

# Everything a reader needs. A file that is not matched here is not published.
ALLOW = [
    "README.md",
    "GLOSSARY.md",
    "LICENSE",
    "LICENSE-CC-BY-4.0",
    "bench.sh",
    "docs/index.html",
    "docs/adr/*.md",
    "docs/artifacts.md",
    "docs/artifacts/*.html",
    "docs/shots/*.png",
    "docs/prompts/*.txt",
    "report/*.py",
    "tools/*.py",
    "results/summary.json",
    "results/issue-body.md",
    "results/findings.md",
    "results/quality/*.json",
    "runs/*/*.json",
    "runs/*/*.txt",
    "runs/*/*.log",
    "runs/*/*.yml",
    "runs/*/*.html",
    "runs/_incident-freeze/*",
]

# Working notes, scaffolding and dead ends: never published. Matched with fnmatch, where
# `*` crosses directory separators, because these patterns are about whole subtrees.
DENY = [
    "AGENTS.md",
    "docs/agents/*",
    "docs/ISSUE-DRAFTS.md",
    "vendor/*",
    "runs/_attempt*",
    "runs/_interrupted*",
    "runs/*/WATCHDOG-KILL.txt",
    "runs/*/env.txt.bak",
    # a docker-stats dump lists every other service on the machine and nothing in the
    # report cites it; the memory evidence is in drop-*.txt and stop-state.txt
    "runs/*/stats-*.txt",
]

TEXT_SUFFIXES = {".md", ".json", ".txt", ".log", ".yml", ".py", ".sh", ".html"}

# Files the tree needs to be served that are not copied from the working repository: a
# project site is served from /<repo>/, the report lives at docs/index.html and its links
# are root-relative, so the site root needs a way in. `.nojekyll` stops Pages from running
# the tree through Jekyll, which would rewrite the HTML and drop files it does not know.
GENERATED = {
    "index.html": (
        "<!doctype html>\n<meta charset=\"utf-8\">\n"
        "<title>Halogen vs Kyojin, one model, one machine</title>\n"
        "<meta http-equiv=\"refresh\" content=\"0; url=docs/index.html\">\n"
        "<p><a href=\"docs/index.html\">The report</a></p>\n"),
    ".nojekyll": "",
}


def is_denied(rel: Path) -> bool:
    """One rule for "this subtree is not published", used by the copy and by the report."""
    text = str(rel)
    return any(fnmatch.fnmatch(text, d) or fnmatch.fnmatch(text + "/x", d) for d in DENY)


def gather(repo: Path) -> list[tuple[Path, Path]]:
    files: list[tuple[Path, Path]] = []
    for pattern in ALLOW:
        for src in sorted(repo.glob(pattern)):
            if not src.is_file():
                continue
            rel = src.relative_to(repo)
            if is_denied(rel):
                continue
            files.append((src, rel))
    # a file matched by two patterns must not be copied twice
    seen, uniq = set(), []
    for src, rel in files:
        if rel in seen:
            continue
        seen.add(rel)
        uniq.append((src, rel))
    return uniq


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--repo", default=".")
    p.add_argument("--dest", required=True)
    p.add_argument("--check", action="store_true",
                   help="say what was scanned on success; a leak fails the export either way")
    a = p.parse_args()
    repo = Path(a.repo).resolve()
    dest = Path(a.dest)
    home = str(Path.home())

    files = gather(repo)
    if not files:
        sys.exit("nothing matched the allowlist")
    denied = sorted({src.relative_to(repo).parts[1] for src in repo.glob("runs/*")
                     if src.is_dir() and is_denied(src.relative_to(repo))})
    if denied:
        print(f"excluded dead ends: {', '.join(denied)}")

    problems: list[str] = []
    staging = dest.with_suffix(".staging")
    if staging.exists():
        shutil.rmtree(staging)
    staging.mkdir(parents=True)

    manifest = []
    for src, rel in files:
        target = staging / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        if src.suffix in TEXT_SUFFIXES:
            text = privacy.scrub(src.read_text(errors="replace"), home)
            problems.extend(privacy.scan(str(rel), text, allow=privacy.PUBLIC_URLS))
            target.write_text(text)
            digest = hashlib.sha256(text.encode()).hexdigest()
        else:
            shutil.copy2(src, target)
            digest = hashlib.sha256(target.read_bytes()).hexdigest()
        manifest.append({"path": str(rel), "bytes": target.stat().st_size, "sha256": digest})

    for name, body in GENERATED.items():
        (staging / name).write_text(body)
        manifest.append({"path": name, "bytes": len(body.encode()),
                         "sha256": hashlib.sha256(body.encode()).hexdigest()})

    (staging / "MANIFEST.json").write_text(json.dumps(
        {"files": manifest, "count": len(manifest)}, indent=2, sort_keys=True))

    if problems:
        print("refusing to publish, host paths survived the scrub:", file=sys.stderr)
        for line in problems[:20]:
            print("  " + line, file=sys.stderr)
        shutil.rmtree(staging)
        sys.exit(1)

    if dest.exists():
        shutil.rmtree(dest)
    staging.rename(dest)
    total = sum(f["bytes"] for f in manifest)
    print(f"{dest}: {len(manifest)} files, {total / 1024 / 1024:.1f} MiB")
    if a.check:
        print("scan: no absolute host path, no operator account name")


if __name__ == "__main__":
    main()
