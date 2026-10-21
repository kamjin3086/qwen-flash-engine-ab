#!/usr/bin/env python3
"""Tests for the guards: the privacy check, the summary validation, the value formatters,
and the checkers that decide the output cases.

These exist because three claims in the repo were unverifiable: ADR-0003 says one privacy
check guards both surfaces, ADR-0004 says every checker was self-tested, and the renderer
says the page and the issue body cannot disagree about a number. A claim with no test is a
claim, so each one is tested here.

    python3 -m unittest discover -s tests -v
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "report"))
sys.path.insert(0, str(REPO / "tools"))

import privacy  # noqa: E402
import render  # noqa: E402
import quality  # noqa: E402


# The export scrubs both forbidden strings, so the published copy carries placeholders.
# Tests that assert on the real values are skipped there, by design, not by accident.
REAL_SLUG = bool(privacy.PRIVATE_SLUG) and not privacy.PRIVATE_SLUG.startswith("<")
REAL_ACCOUNT = bool(privacy.OPERATOR_ACCOUNT) and not privacy.OPERATOR_ACCOUNT.startswith("<")


class PrivacyTest(unittest.TestCase):
    def test_a_stats_dump_naming_another_container_is_refused(self):
        text = ("NAME  MEM USAGE / LIMIT  MEM %\n"
                "halogen-flash-server-halogen-1  14.51GiB / 124.9GiB  11.61%\n"
                "some-service  80.87MiB / 124.9GiB  0.06%\n")
        problems = privacy.scan("runs/x/stats-end.txt", text)
        self.assertTrue(any("outside this comparison" in p for p in problems), problems)

    def test_a_stats_dump_with_only_the_two_engines_passes(self):
        text = ("NAME  MEM USAGE / LIMIT  MEM %\n"
                "halogen-flash-server-halogen-1  14.51GiB / 124.9GiB  11.61%\n"
                "kyojin-qwen-trial  92.00GiB / 124.9GiB  73.66%\n")
        self.assertEqual(privacy.scan("runs/x/stats-end.txt", text), [])

    def test_the_stock_docker_stats_layout_is_caught(self):
        # CONTAINER ID first: the memory cell is not adjacent to the name, which is exactly
        # how the first version of this guard was defeated
        text = ("CONTAINER ID   NAME        CPU %   MEM USAGE / LIMIT     MEM %\n"
                "3f2a1b9c8d7e   other-service   0.15%   1.57GiB / 124.9GiB    1.26%\n")
        problems = privacy.scan("runs/x/stats-end.txt", text)
        self.assertTrue(any("outside this comparison" in p for p in problems), problems)

    def test_a_plain_audit_line_is_not_mistaken_for_a_container(self):
        text = "# gtt_mib 549\nkv_cache_used 3.20GiB / 8.00GiB\n"
        self.assertEqual(privacy.scan("runs/x/drop-h1.txt", text), [])

    def test_the_guard_does_not_fire_on_code_that_describes_a_stats_table(self):
        # this module's own source mentions MEM USAGE and then a non-engine token; a guard
        # that scans code would refuse to publish the file that implements it
        source = ('STATS_HEADER = re.compile(r"MEM USAGE", re.I)\n'
                  'ENGINE_CONTAINERS = {"halogen-flash-server-halogen-1"}\n')
        self.assertEqual(privacy.scan("report/privacy.py", source), [])

    def test_a_leak_in_a_file_name_is_caught(self):
        problems = privacy.scan("runs/halogen/" + privacy.PRIVATE_SLUG + ".txt", "clean body")
        self.assertTrue(any("private working repository" in p for p in problems), problems)

    def test_scan_does_not_fire_on_ordinary_key_value_files(self):
        text = "kernel 7.2.9-201.fc44.x86_64\nmem_total_gib 124\nwarm_start_to_models_s 43\n"
        self.assertEqual(privacy.scan("runs/x/env.txt", text), [])

    def test_scan_catches_host_paths_only_in_data(self):
        self.assertTrue(privacy.scan("runs/x/env.txt", "path /home/someone/x"))
        self.assertEqual(privacy.scan("report/x.py", "SUFFIXES = ('/tmp/',)"), [])

    def test_scan_catches_the_private_repo_slug(self):
        problems = privacy.scan("docs/x.md", "see " + privacy.PRIVATE_SLUG)
        self.assertTrue(any("private working repository" in p for p in problems), problems)

    @unittest.skipUnless(REAL_SLUG, "published copy: the slug is a placeholder")
    def test_scrub_removes_the_slug(self):
        self.assertNotIn(privacy.PRIVATE_SLUG, privacy.scrub("x " + privacy.PRIVATE_SLUG))

    def test_the_guard_does_not_fire_on_the_module_that_defines_the_slug(self):
        # the export scrubs the slug, so the published copy of this file holds the
        # placeholder as the constant and then matches it in its own lines; refusing to
        # publish that makes the published tree unable to rebuild itself
        source = Path(privacy.__file__).read_text()
        self.assertEqual(privacy.scan("report/privacy.py", privacy.scrub(source)), [])

    @unittest.skipUnless(REAL_ACCOUNT, "published copy: the account is a placeholder")
    def test_scrub_keeps_the_public_urls_intact(self):
        # the account name is scrubbed, but not where it is one of the repository's URLs
        text = " ".join(privacy.PUBLIC_URLS) + f" and {privacy.OPERATOR_ACCOUNT}'s host"
        scrubbed = privacy.scrub(text)
        for url in privacy.PUBLIC_URLS:
            self.assertIn(url, scrubbed)
        self.assertNotIn(f"{privacy.OPERATOR_ACCOUNT}'s", scrubbed)

    def test_the_operator_account_is_caught_outside_the_public_url(self):
        problems = privacy.scan("runs/x/env.txt", "owner " + privacy.OPERATOR_ACCOUNT)
        self.assertTrue(any("account" in p for p in problems), problems)
        allowed = privacy.scan("results/issue-body.md",
                               "links " + privacy.PUBLIC_REPO_URL,
                               allow=(privacy.PUBLIC_REPO_URL,))
        self.assertEqual(allowed, [])


class ValueFormattingTest(unittest.TestCase):
    def test_page_and_issue_format_identically(self):
        for metric, value, status in (("quality_pass_rate", 0.923, "measured"),
                                      ("quality_case_pass", True, "measured"),
                                      ("prefill_tps", 1850.527, "measured"),
                                      ("decode_tps", 53.6, "measured"),
                                      ("startup_s", 561.0, "measured"),
                                      ("needle_found", True, "measured"),
                                      ("prefill_tps", None, "not_run")):
            page = render.fmt(metric, value, status)
            issue = render.md_cell(metric, value, status)
            page_plain = page.replace('<span class="miss">', "").replace("</span>", "").strip()
            self.assertEqual(page_plain, issue.strip("_"),
                             f"{metric}/{status}: page {page!r} vs issue {issue!r}")

    def test_a_range_never_collapses_to_one_number(self):
        # 149.003 and 149.307 both print as "149" at the metric's usual precision
        self.assertEqual(render.fmt_range("ttft_s", 149.003, 149.307), "149.0–149.3")
        self.assertEqual(render.fmt_range("prefill_tps", 1692.525, 1696.127), "1,693–1,696")
        self.assertEqual(render.fmt_range("decode_tps", 53.0, 53.0), "53–53")  # a real zero width

    def test_quality_rate_is_a_percentage_on_both(self):
        self.assertEqual(render.md_cell("quality_pass_rate", 0.923, "measured"), "92%")
        self.assertIn("92%", render.fmt("quality_pass_rate", 0.923, "measured"))


class QualityCheckerTest(unittest.TestCase):
    """ADR-0004 claims every checker was self-tested. This is that test, kept."""

    def test_last_number(self):
        self.assertTrue(quality.check_last_number("So 100 machines take 5 minutes.", "5")[0])
        self.assertFalse(quality.check_last_number("the answer is 100.", "5")[0])
        self.assertTrue(quality.check_last_number("The ball costs $0.05.", "0.05")[0])

    def test_last_time(self):
        self.assertTrue(quality.check_last_time("It arrives at 18:35.", "18:35")[0])
        self.assertFalse(quality.check_last_time("It arrives at 18:25.", "18:35")[0])

    def test_bullets_haiku(self):
        good = ("- one two three\n- four five\n- six\n- seven\n- eight nine\n\n"
                "soft rain falls\non the wide grey river\nnothing moves at all")
        bad = "- one and two\n- a\n- b\n- c\n- d\n\nx\ny\nz"
        self.assertTrue(quality.check_bullets_haiku(good)[0])
        self.assertFalse(quality.check_bullets_haiku(bad)[0])

    def test_json_shape(self):
        want = {"vowels": 17, "words": 6, "longest_word": "afternoons"}
        self.assertTrue(quality.check_json_shape('{"vowels": 17, "words": 6, '
                                                 '"longest_word": "afternoons"}', want)[0])
        self.assertFalse(quality.check_json_shape('{"vowels": 16, "words": 6, '
                                                  '"longest_word": "afternoons"}', want)[0])

    def test_python_checker(self):
        good = "```python\nfrom datetime import timedelta\ndef parse_duration(s):\n    return timedelta(seconds=30)\n```"
        script = ('from datetime import timedelta\nfrom mod import parse_duration\n'
                  'assert parse_duration("PT30S") == timedelta(seconds=30)\n')
        self.assertTrue(quality.check_python(good, script)[0])
        self.assertFalse(quality.check_python("```python\ndef parse_duration(s):\n    return None\n```",
                                             script)[0])


class StainTest(unittest.TestCase):
    """The fixes the second review showed were untested. Each one fails if the fix is reverted."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        runs = self.tmp / "runs" / "halogen"
        runs.mkdir(parents=True)
        (runs / "env.txt").write_text("halogen_digest sha256:" + "a" * 64 +
                                      "\ntimestamp 2019-03-04T09:15:00+00:00\n")
        self.runs = self.tmp / "runs"
        self.out = self.tmp / "s.json"

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def summary(self):
        # --csv too: without it the run writes results/measurements.csv in the repository
        return subprocess.run([sys.executable, "report/summary.py", "--runs", str(self.runs),
                               "--out", str(self.out), "--csv", str(self.tmp / "m.csv")],
                              cwd=REPO, capture_output=True, text=True)

    def test_bench_txt_without_its_json_block_is_refused(self):
        (self.runs / "halogen" / "bench.txt").write_text("### Kyojin benchmark\ntruncated half a table")
        p = self.summary()
        self.assertNotEqual(p.returncode, 0)
        self.assertIn("no fenced JSON block", p.stderr)

    def test_unknown_json_in_a_non_measurement_phase_is_refused(self):
        (self.runs / "smoke").mkdir()
        (self.runs / "smoke" / "mystery.json").write_text("{}")
        p = self.summary()
        self.assertNotEqual(p.returncode, 0)
        self.assertIn("mystery.json", p.stderr)

    def test_an_editor_swap_file_does_not_stop_the_report(self):
        (self.runs / "halogen" / ".DS_Store").write_text("junk")
        (self.runs / "halogen" / "bench.txt~").write_text("junk")
        (self.runs / "halogen" / "ctx.json").write_text(json.dumps({"runs": [
            {"requested_tokens": 32000, "prompt_tokens": 30000,
             "prefill_tps_server": 1800.0, "ttft_s": 16.0}]}))
        p = self.summary()
        self.assertEqual(p.returncode, 0, p.stderr)

    def test_chart_renders_an_unmeasured_point_as_a_labelled_gap(self):
        import charts
        svg = charts.line_chart({"halogen": [(30790.0, 1850.0), (122456.0, None), (250549.0, 1707.0)]},
                                x_label="tokens", y_label="tok/s", title="t")
        self.assertIn("not run", svg, "the gap must be labelled")
        paths = [p for p in svg.split("<path d=\"")[1:]]
        self.assertEqual(len(paths), 2, "one path per contiguous run, none drawn through the gap")

    def test_issue_body_never_prints_a_missing_phase_as_None(self):
        summary = {"schema": 1, "counts": {"total": 2, "measured": 1, "not_run": 1, "aborted": 0},
                   "measurements": [
                       {"metric": "prefill_tps", "unit": "tok/s", "engine": "halogen", "phase": "halogen",
                        "digest": "sha256:" + "a" * 64, "condition": "prompt ~32K", "value": 1850.0,
                        "raw_path": "runs/halogen/ctx.json", "status": "measured", "abort_rule": None,
                        "provenance_source": "record"},
                       {"metric": "prefill_tps", "unit": "tok/s", "engine": "kyojin", "phase": None,
                        "digest": "sha256:" + "b" * 64, "condition": "prompt ~32K", "value": None,
                        "raw_path": "", "status": "not_run", "abort_rule": None,
                        "provenance_source": "absent"}]}
        md = render.render_issue(summary, [], "", "https://example.invalid/repo")
        self.assertNotIn("None", md)

    def test_raw_links_are_checked_against_the_repo_being_rendered(self):
        (self.runs / "halogen" / "ctx.json").write_text(json.dumps({"runs": [
            {"requested_tokens": 32000, "prompt_tokens": 30000,
             "prefill_tps_server": 1800.0, "ttft_s": 16.0}]}))
        self.summary()
        render.LINK_ROOT = self.tmp / "elsewhere"
        html = render.cell_table(json.loads(self.out.read_text())["measurements"])
        self.assertNotIn('class="raw"', html, "no link when the file is not in that repo")
        render.LINK_ROOT = self.tmp
        html = render.cell_table(json.loads(self.out.read_text())["measurements"])
        self.assertIn('class="raw"', html)

    def test_the_page_date_comes_from_the_run_not_the_clock(self):
        (self.runs / "halogen" / "ctx.json").write_text(json.dumps({"runs": []}))
        self.summary()
        stamp = render.run_stamp(self.tmp)
        self.assertEqual(stamp, "2019-03-04",
                         "the page date must come from the run, not the clock")


class CheckerDispatchTest(unittest.TestCase):
    def test_a_known_checker_runs(self):
        self.assertTrue(quality.apply_check(("last_number", "5"), "so 5 minutes")[0])

    def test_an_unknown_checker_is_reported_not_silently_passed(self):
        ok, detail = quality.apply_check(("nope", None), "anything")
        self.assertFalse(ok, "an unknown checker must not count as a pass")
        self.assertIn("unknown checker nope", detail)


class SummaryValidationTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.good = {
            "schema": 1,
            "counts": {"total": 1, "measured": 1, "not_run": 0, "aborted": 0},
            "measurements": [{"metric": "prefill_tps", "unit": "tok/s", "engine": "halogen",
                              "phase": "halogen", "digest": "sha256:" + "a" * 64,
                              "condition": "prompt ~32K", "value": 1850.0,
                              "raw_path": "runs/halogen/ctx.json", "status": "measured",
                              "abort_rule": None, "provenance_source": "record"}],
        }

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def render_with(self, summary):
        (self.tmp / "s.json").write_text(json.dumps(summary))
        return subprocess.run(
            [sys.executable, "report/render.py", "--summary", str(self.tmp / "s.json"),
             "--repo", str(self.tmp), "--out", str(self.tmp / "docs"),
             "--issue", str(self.tmp / "issue.md")],
            cwd=REPO, capture_output=True, text=True)

    def test_good_summary_renders(self):
        p = self.render_with(self.good)
        self.assertEqual(p.returncode, 0, p.stderr)

    def test_unknown_metric_is_refused(self):
        bad = json.loads(json.dumps(self.good))
        bad["measurements"][0]["metric"] = "warp_factor"
        p = self.render_with(bad)
        self.assertNotEqual(p.returncode, 0)
        self.assertIn("unknown metric", p.stderr)

    def test_unknown_unit_is_refused(self):
        bad = json.loads(json.dumps(self.good))
        bad["measurements"][0]["unit"] = "parsecs"
        p = self.render_with(bad)
        self.assertNotEqual(p.returncode, 0)
        self.assertIn("unit", p.stderr)

    def test_not_finite_and_negative_values_are_refused(self):
        for value in (float("nan"), float("inf"), -1e12):
            bad = json.loads(json.dumps(self.good))
            bad["measurements"][0]["value"] = value
            p = self.render_with(bad)
            self.assertNotEqual(p.returncode, 0, f"{value!r} must not render")

    def test_an_empty_summary_is_refused(self):
        bad = {"schema": 1, "counts": {"total": 0, "measured": 0, "not_run": 0, "aborted": 0},
               "measurements": []}
        p = self.render_with(bad)
        self.assertNotEqual(p.returncode, 0)
        self.assertIn("no measurements", p.stderr)

    def test_counts_not_run_and_aborted_are_checked_too(self):
        bad = json.loads(json.dumps(self.good))
        bad["counts"]["aborted"] = 3
        p = self.render_with(bad)
        self.assertNotEqual(p.returncode, 0)
        self.assertIn("counts.aborted", p.stderr)

    def test_a_missing_field_is_reported_not_a_traceback(self):
        bad = json.loads(json.dumps(self.good))
        del bad["measurements"][0]["condition"]
        p = self.render_with(bad)
        self.assertNotEqual(p.returncode, 0)
        self.assertIn("missing field", p.stderr)
        self.assertNotIn("Traceback", p.stderr)

    def test_unknown_status_is_refused(self):
        bad = json.loads(json.dumps(self.good))
        bad["measurements"][0]["status"] = "banana"
        p = self.render_with(bad)
        self.assertNotEqual(p.returncode, 0)
        self.assertIn("status", p.stderr)

    def test_a_valid_variance_block_is_accepted(self):
        good = json.loads(json.dumps(self.good))
        good["schema"] = 2
        good["variance"] = [{"engine": "halogen", "phase": "variance-halogen",
                             "metric": "ttft_s", "unit": "s", "condition": "prompt ~262K",
                             "n": 3, "median": 149.1, "min": 149.0, "max": 149.3,
                             "raw_path": "runs/variance-halogen/variance.json"}]
        self.assertEqual(self.render_with(good).returncode, 0)

    def test_a_variance_block_with_impossible_statistics_is_refused(self):
        bad = json.loads(json.dumps(self.good))
        bad["schema"] = 2
        bad["variance"] = [{"engine": "halogen", "phase": "variance-halogen",
                            "metric": "ttft_s", "unit": "s", "condition": "prompt ~262K",
                            "n": 1, "median": 149.1, "min": 149.5, "max": 149.0,
                            "raw_path": "x"}]
        p = self.render_with(bad)
        self.assertNotEqual(p.returncode, 0)
        self.assertIn("at least two repetitions", p.stderr)
        self.assertIn("out of order", p.stderr)

    def test_counts_that_disagree_are_refused(self):
        bad = json.loads(json.dumps(self.good))
        bad["counts"]["measured"] = 7
        p = self.render_with(bad)
        self.assertNotEqual(p.returncode, 0)
        self.assertIn("counts.measured", p.stderr)


if __name__ == "__main__":
    unittest.main()
