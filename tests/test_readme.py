#!/usr/bin/env python3
"""The README is a surface, so its numbers are tested like one.

README.md is the first thing a reader of the published tree opens, and it was the last
hand-written surface with no guard: it said "105 measurements" while the summary said 111, and it
named Kyojin 1.5 while the digest it printed belonged to the image the run actually
measured (1.6). Nothing checked it, because nothing looked.

The rule this file enforces is the same one `test_findings.py` enforces for the prose:
if the data changes, the sentence next to it has to change too. It also checks that every
local path the README points at exists, so the published tree cannot ship a dead link.

    python3 -m unittest discover -s tests
"""
from __future__ import annotations

import json
import re
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
README = REPO / "README.md"
SUMMARY = REPO / "results" / "summary.json"

# A path named in the README, in a Markdown link or in an inline code span. Tokens with a
# space are commands (`python3 report/build.py`), not paths, and are skipped.
LINK = re.compile(r"\[[^\]]*\]\(([^)#\s]+)\)")
SPAN = re.compile(r"`([^`\s]+)`")
PATH_SUFFIXES = {".md", ".py", ".json", ".html", ".sh", ".txt", ".png"}


def local_paths(text: str) -> list[str]:
    found = []
    for match in LINK.finditer(text):
        target = match.group(1)
        if "://" in target or target.startswith("mailto:"):
            continue
        found.append(target)
    for match in SPAN.finditer(text):
        token = match.group(1)
        if "/" not in token or "@" in token or ":" in token or "://" in token:
            continue
        # `cache/` and `models/` are directories inside the engines, not paths in this repo
        if token.endswith("/") and "/" not in token.rstrip("/"):
            continue
        if Path(token).suffix in PATH_SUFFIXES or token.endswith("/"):
            found.append(token)
    return sorted(set(found))


class ReadmeDriftTest(unittest.TestCase):
    """What the README says about the run has to be what the run recorded."""

    @classmethod
    def setUpClass(cls):
        cls.summary = json.loads(SUMMARY.read_text())
        cls.readme = README.read_text()
        cls.digest: dict[str, str] = {}
        for e in cls.summary["measurements"]:
            if e.get("status") == "measured" and e.get("digest"):
                cls.digest.setdefault(e["engine"], e["digest"])

    def test_the_status_line_quotes_the_summary_counts(self):
        counts = self.summary["counts"]
        line = next(l for l in self.readme.splitlines()
                    if "measurements" in l and "not run" in l and "aborted" in l)
        self.assertIn(f"{counts['measured']} measurements", line)
        self.assertIn(f"{counts['not_run']} not run", line)
        self.assertIn(f"{counts['aborted']} aborted", line)

    def test_each_engine_row_quotes_the_digest_that_was_measured(self):
        for engine, digest in self.digest.items():
            self.assertIn(digest[:8], self.readme,
                          f"README does not carry the {engine} digest the run recorded")
        self.assertIn("halogen-flash-server", self.readme)
        self.assertIn("kyojin-qwen", self.readme)

    def test_the_kyojin_tag_is_the_one_whose_digest_was_measured(self):
        wanted = self.digest["kyojin"].split("sha256:", 1)[-1]
        tags = {}
        for env in sorted(REPO.glob("runs/*/env.txt")):
            for line in env.read_text(errors="replace").splitlines():
                parts = line.split()
                if len(parts) == 3 and parts[0] == "kyojin_local_tag":
                    tags[parts[2].removeprefix("sha256:")] = parts[1]
        tag = tags.get(wanted)
        self.assertIsNotNone(tag, "no recorded local tag carries the measured Kyojin digest")
        self.assertIn(f"kyojin-qwen:{tag}", self.readme)

    def test_the_halogen_version_is_the_one_the_image_printed(self):
        log = (REPO / "runs" / "halogen" / "docker-startup.log").read_text(errors="replace")
        version = re.search(r"halogen-flash-server ([0-9][0-9.]*)", log).group(1)
        self.assertIn(version, self.readme)

    def test_every_local_path_the_readme_names_exists(self):
        for target in local_paths(self.readme):
            if "*" in target:
                self.assertTrue(list(REPO.glob(target)), f"README names {target}, nothing matches")
            else:
                self.assertTrue((REPO / target).exists(), f"README names {target}, which does not exist")

    def test_the_license_claims_point_at_licenses_that_exist(self):
        self.assertIn("LICENSE", self.readme)
        self.assertIn("MIT", self.readme)
        self.assertIn("CC-BY-4.0", self.readme)
        self.assertTrue((REPO / "LICENSE").is_file())
        self.assertTrue((REPO / "LICENSE-CC-BY-4.0").is_file())


if __name__ == "__main__":
    unittest.main()
