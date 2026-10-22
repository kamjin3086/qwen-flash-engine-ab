#!/usr/bin/env python3
"""The published tree has to work as a tree, not just as an output.

Two claims about the export had no test, and both were false:

- ADR-0003 calls the export idempotent. In the published copy, `python3 report/build.py`
  exited 1: the privacy check scrubbed its own forbidden slug into a placeholder and then
  fired on the placeholder, in the file that defines the rule. The tree could not rebuild
  itself, which is the one thing a reader is told to do.
- the allowlist is what makes the tree readable. `docs/artifacts.md` was named by the
  README and denied by the export, so the README linked to a file that was not there.

These tests export the real repository, then treat the result as a repository and export
it again. The guard is checked for liveness too: a published tree that silently stopped
catching host paths would pass a "second export works" test for the wrong reason.

    python3 -m unittest discover -s tests
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "tests"))
sys.path.insert(0, str(REPO / "report"))
from test_readme import local_paths  # noqa: E402  the same link reader, one definition
import privacy  # noqa: E402  the URL and the check, one definition each


def export(repo: Path, dest: Path) -> subprocess.CompletedProcess:
    """Run the exporter *that lives in `repo`*, so the published copy's own module runs.

    Running the working repository's exporter against the published tree would test the
    wrong privacy constants: the published copy's are scrubbed, which is the whole point.
    """
    return subprocess.run([sys.executable, "report/export.py", "--repo", str(repo),
                           "--dest", str(dest), "--check"],
                          cwd=repo, capture_output=True, text=True,
                          env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"})


class ExportedTreeTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp())
        cls.pub = cls.tmp / "pub"
        p = export(REPO, cls.pub)
        if p.returncode != 0:
            raise AssertionError(f"the export of the working repository failed:\n{p.stderr}")

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_benchmark_script_stays_executable_after_export(self):
        self.assertTrue(os.access(self.pub / "bench.sh", os.X_OK))
        syntax = subprocess.run(["bash", "-n", str(self.pub / "bench.sh")],
                                capture_output=True, text=True)
        self.assertEqual(syntax.returncode, 0, syntax.stderr)
        second = self.tmp / "executable-again"
        p = export(self.pub, second)
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertTrue(os.access(second / "bench.sh", os.X_OK))

    def test_the_published_tree_can_export_itself(self):
        second = self.tmp / "second"
        p = export(self.pub, second)
        self.assertEqual(p.returncode, 0, f"a reader cannot rebuild the tree they were given:\n{p.stderr}")
        self.assertTrue((second / "MANIFEST.json").is_file())
        self.assertTrue((second / "README.md").is_file())

    def test_the_published_tree_re_exports_to_the_same_bytes(self):
        # ADR-0003 calls the export idempotent; a second export of the published tree has
        # to reproduce it exactly, not merely succeed
        second = self.tmp / "same-bytes"
        p = export(self.pub, second)
        self.assertEqual(p.returncode, 0, p.stderr)
        def tree(root: Path) -> dict[str, bytes]:
            return {str(x.relative_to(root)): x.read_bytes() for x in root.rglob("*")
                    if x.is_file() and "__pycache__" not in x.parts and "build" not in x.parts}
        first, again = tree(self.pub), tree(second)
        self.assertEqual(first, again)

    def test_the_published_tree_still_catches_a_host_path(self):
        # the published copy cannot check for the two strings it no longer contains; what
        # it must still catch is a host path and a container outside the comparison
        copy = self.tmp / "guarded"
        shutil.copytree(self.pub, copy)
        findings = copy / "results" / "findings.md"
        findings.write_text(findings.read_text() + "\nleak: /home/someone/apps/x\n")
        p = export(copy, self.tmp / "refused")
        self.assertNotEqual(p.returncode, 0, "the published tree's guard is inert")
        self.assertIn("absolute home path", p.stderr)

    def test_the_published_tree_still_catches_an_unrelated_container(self):
        copy = self.tmp / "guarded-stats"
        shutil.copytree(self.pub, copy)
        (copy / "runs" / "halogen" / "leak.txt").write_text(
            "NAME  MEM USAGE / LIMIT  MEM %\nsome-service  1.57GiB / 124.9GiB  1.26%\n")
        p = export(copy, self.tmp / "refused-stats")
        self.assertNotEqual(p.returncode, 0, "the published tree publishes any container row")
        self.assertIn("outside this comparison", p.stderr)

    @unittest.skipUnless(privacy.PRIVATE_SLUG and not privacy.PRIVATE_SLUG.startswith("<"),
                         "published copy: the slug is a placeholder")
    def test_the_private_slug_does_not_survive(self):
        for path in self.pub.rglob("*"):
            if path.is_file():
                self.assertNotIn(privacy.PRIVATE_SLUG, path.read_text(errors="replace"),
                                 f"{path} names the private working repository")

    def test_the_operator_account_appears_only_inside_the_public_url(self):
        for path in self.pub.rglob("*"):
            if not path.is_file() or path.name == "privacy.py":
                continue  # the module holds the constants the check is made of
            text = path.read_text(errors="replace")
            for url in privacy.PUBLIC_URLS:
                text = text.replace(url, "")
            self.assertNotIn(privacy.OPERATOR_ACCOUNT, text,
                             f"{path} names the operator's account outside the public repository URL")

    def test_every_readme_link_resolves_inside_the_published_tree(self):
        readme = (self.pub / "README.md").read_text()
        for target in local_paths(readme):
            if "*" in target:
                self.assertTrue(list(self.pub.glob(target)), f"published README names {target}, nothing matches")
            else:
                self.assertTrue((self.pub / target).exists(), f"published README names {target}, which is missing")

    def test_the_site_root_has_a_way_in(self):
        # a project site is served from /<repo>/, where the tree has no page of its own; the
        # report lives at docs/index.html and must be reachable from the site root
        index = (self.pub / "index.html").read_text()
        self.assertIn("url=docs/index.html", index)
        self.assertTrue((self.pub / "docs" / "index.html").is_file())

    def test_jekyll_is_disabled(self):
        # Pages would otherwise process the tree and drop what it does not recognise
        self.assertTrue((self.pub / ".nojekyll").is_file())

    def test_the_licenses_are_published(self):
        self.assertTrue((self.pub / "LICENSE").is_file(), "README promises MIT, no LICENSE is published")
        self.assertTrue((self.pub / "LICENSE-CC-BY-4.0").is_file(),
                        "README promises CC-BY-4.0, no license text is published")

    def test_the_method_notes_the_readme_cites_are_published(self):
        self.assertTrue((self.pub / "docs" / "artifacts.md").is_file(),
                        "README cites docs/artifacts.md; the export denies it")

    def test_the_manifest_lists_every_published_file(self):
        manifest = json.loads((self.pub / "MANIFEST.json").read_text())
        listed = {f["path"] for f in manifest["files"]}
        on_disk = {str(p.relative_to(self.pub)) for p in self.pub.rglob("*")
                   if p.is_file() and p.name != "MANIFEST.json"}
        self.assertEqual(listed, on_disk)


if __name__ == "__main__":
    unittest.main()
