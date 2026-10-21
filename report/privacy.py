#!/usr/bin/env python3
"""The one privacy check, shared by the report and the export.

ADR-0003 claims "the same privacy assertion guards the report and the export, because
they are one check in one place". This module is that place. A second copy of the rule is
how the two surfaces drift apart, and drift here means publishing something private.

What counts as a leak:

- an absolute host path (`/home/`, `/tmp/`), in data files always, in code only when it is
  *this* machine's home directory;
- the operator's account name, except as part of the public repository URL;
- the slug of the private working repository, on any surface a reader can reach;
- a `docker stats` row naming a container that is not one of the two engines.
"""
from __future__ import annotations

import re
from pathlib import Path

# data files may not name any concrete host path at all
DATA_SUFFIXES = {".md", ".json", ".txt", ".log", ".yml", ".html"}
DATA_FORBIDDEN = [("/home/", "absolute home path"), ("/tmp/", "absolute temp path")]

PRIVATE_SLUG = "<private-repo>"
OPERATOR_ACCOUNT = "<operator>"
# Literals, not built from the account: the export protects these strings and scrubs the
# account, so the published copy keeps the real URLs and loses only the bare name.
PUBLIC_REPO_URL = "https://github.com/kamjin3086/qwen-flash-engine-ab"
PAGES_URL = "https://kamjin3086.github.io/qwen-flash-engine-ab"
PUBLIC_URLS = (PUBLIC_REPO_URL, PAGES_URL)

# The module that defines the two forbidden strings cannot be judged by them: the export
# scrubs both, so the published copy holds the placeholders as constants and would then
# match them in its own lines, refusing to publish itself. This one file is skipped for
# those two checks only, never for host paths or container rows, and it is what makes the
# published tree able to rebuild itself.
SELF = Path(__file__).resolve()


def is_this_module(path: str) -> bool:
    """True for this module in this tree, never for a stray file that shares its name."""
    p = Path(path)
    return p.name == SELF.name and p.parent.name == SELF.parent.name


# A docker-stats dump announces itself with this column header. The container check is
# scoped to files that contain it: matching "name followed by a memory cell" anywhere
# leaks on any output format that puts another column first, and mis-fires on audit lines
# such as `kv_cache_used 3.20GiB / 8.00GiB`.
STATS_HEADER = re.compile(r"MEM USAGE", re.I)
ENGINE_CONTAINERS = {"halogen-flash-server-halogen-1", "kyojin-qwen-trial"}
TABLE_HEADER_TOKENS = {"NAME", "CONTAINER"}


def container_rows(problems: list[str], path: str, text: str) -> None:
    """Every data row of a docker-stats table must name one of the two engines."""
    in_table = False
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if STATS_HEADER.search(stripped):
            in_table = True
            continue
        if not in_table:
            continue
        first = stripped.split()[0]
        if first in ENGINE_CONTAINERS or first.upper() in TABLE_HEADER_TOKENS:
            continue
        problems.append(f"{path}: names a container outside this comparison: {first[:40]}")
        return


def scrub(text: str, home: str | None = None) -> str:
    """Remove what must not be published, so a file that documents it is fixed, not refused."""
    home = home or str(Path.home())
    text = text.replace(home, "~")
    text = text.replace("<temp>", "<temp>")
    text = text.replace(PRIVATE_SLUG, "<private-repo>")
    # the account name is public only as part of the URLs it owns: protect them, scrub the
    # name, put them back
    kept = {}
    for i, url in enumerate(PUBLIC_URLS):
        token = f"\x00public-url-{i}\x00"
        if url in text:
            text = text.replace(url, token)
            kept[token] = url
    text = text.replace(OPERATOR_ACCOUNT, "<operator>")
    for token, url in kept.items():
        text = text.replace(token, url)
    return text


def scan(path: str, text: str, *, allow: tuple[str, ...] = ()) -> list[str]:
    """Return the leaks in one file, as human-readable problems."""
    problems: list[str] = []
    scanned = text
    for ok in allow:
        scanned = scanned.replace(ok, "<public-repo>")

    home = str(Path.home())
    if home in scanned:
        problems.append(f"{path}: this machine's home path")
    self_file = is_this_module(path)
    # a leaked name can arrive as a file name as easily as as a line of content
    if PRIVATE_SLUG and PRIVATE_SLUG in path:
        problems.append(f"{path}: names the private working repository")
    elif PRIVATE_SLUG and not self_file and PRIVATE_SLUG in scanned:
        problems.append(f"{path}: names the private working repository")
    if OPERATOR_ACCOUNT and not self_file and OPERATOR_ACCOUNT in scanned:
        problems.append(f"{path}: names the operator's account outside the public repository URL")

    if Path(path).suffix in DATA_SUFFIXES:
        for needle, why in DATA_FORBIDDEN:
            if needle in scanned:
                line = next((l for l in scanned.splitlines() if needle in l), "")
                problems.append(f"{path}: {why}: {line.strip()[:100]}")

    # code may discuss a stats table (this module does); only data may contain one
    if Path(path).suffix in DATA_SUFFIXES:
        container_rows(problems, path, scanned)
    return problems
