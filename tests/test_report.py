#!/usr/bin/env python3
"""Tests at the one seam the report has: a summary goes in, files come out.

They assert what a reader sees — the values, the provenance, the not-run rows, the abort
band, the privacy guard — not how the generator is organised. Nothing here needs an
engine: the fixtures are hand-written summaries.

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


def measured(engine, metric, condition, value, unit="tok/s", phase="halogen", digest=None):
    return {"metric": metric, "unit": unit, "engine": engine, "phase": phase,
            "digest": digest or f"ghcr.io/x@{'a' * 64}", "condition": condition,
            "value": value, "raw_path": f"runs/{phase}/ctx.json", "status": "measured",
            "abort_rule": None, "provenance_source": "phase env.txt"}


def missing(engine, metric, condition, unit="tok/s", status="not_run", rule=None):
    return {"metric": metric, "unit": unit, "engine": engine, "phase": "not run",
            "digest": None, "condition": condition, "value": None, "raw_path": "",
            "status": status, "abort_rule": rule, "provenance_source": "absent"}


FIXTURE = {
    "schema": 1, "phases": ["halogen"], "engines": ["halogen", "kyojin"],
    "counts": {"total": 6, "measured": 3, "not_run": 2, "aborted": 1},
    "measurements": [
        measured("halogen", "prefill_tps", "prompt ~32K", 1850.527, digest="ghcr.io/h@sha256:" + "1" * 64),
        missing("kyojin", "prefill_tps", "prompt ~32K"),
        measured("halogen", "decode_tps", "decode chat", 53.6),
        missing("kyojin", "decode_tps", "decode chat", status="aborted", rule="A2: GTT still held"),
        measured("halogen", "startup_s", "first start", 37.0, unit="s"),
        missing("kyojin", "startup_s", "first start", unit="s"),
    ],
}


class ReportTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.summary_path = self.tmp / "summary.json"
        self.summary_path.write_text(json.dumps(FIXTURE))

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def render(self, **kw):
        out = self.tmp / "docs"
        issue = self.tmp / "issue.md"
        args = [sys.executable, "report/render.py", "--summary", str(self.summary_path),
                "--out", str(out), "--issue", str(issue), "--repo", str(self.tmp)]
        p = subprocess.run(args, cwd=REPO, capture_output=True, text=True)
        return p, out, issue

    def test_values_and_provenance_appear(self):
        p, out, issue = self.render()
        self.assertEqual(p.returncode, 0, p.stderr)
        html = (out / "index.html").read_text()
        self.assertIn("1,851", html, "the prefill value is rendered")
        self.assertIn(">53.6<", html, "the decode value is rendered")
        self.assertIn("halogen", html)
        self.assertIn('class="prov"', html, "each cell carries a provenance line")
        self.assertIn("prompt ~32K", html)
        md = issue.read_text()
        self.assertIn("| Prefill | prompt ~32K | 1,851 | _not run_ |", md)

    def test_aborted_is_visible_as_aborted(self):
        p, out, issue = self.render()
        self.assertEqual(p.returncode, 0, p.stderr)
        html = (out / "index.html").read_text()
        self.assertIn("A2: GTT still held", html, "the abort rule is named on the page")
        self.assertIn("aborted", html)
        self.assertIn("_aborted_", issue.read_text())

    def test_a_known_not_run_row_says_why(self):
        # three rows in the real run are "not run" only because Kyojin publishes no
        # occupancy counters; a bare "not run" cell makes that look like missing work
        fixture = json.loads(json.dumps(FIXTURE))
        fixture["measurements"].append({
            "metric": "peak_in_flight", "unit": "requests", "engine": "kyojin",
            "phase": "kyojin-s4", "digest": None, "condition": "N=4", "value": None,
            "raw_path": "runs/kyojin-s4/conc4.json", "status": "not_run",
            "abort_rule": None, "provenance_source": "phase env.txt"})
        fixture["counts"] = {"total": 7, "measured": 3, "not_run": 3, "aborted": 1}
        self.summary_path.write_text(json.dumps(fixture))
        p, out, issue = self.render()
        self.assertEqual(p.returncode, 0, p.stderr)
        for text in ((out / "index.html").read_text(), issue.read_text()):
            self.assertIn("occupancy cannot be observed", text)

    def test_issue_and_page_agree(self):
        p, out, issue = self.render()
        self.assertEqual(p.returncode, 0, p.stderr)
        html, md = (out / "index.html").read_text(), issue.read_text()
        for value in ("1,851", "53.6", "37"):
            self.assertIn(value, html)
            self.assertIn(value, md)

    def test_pipe_tables_in_the_findings_become_tables(self):
        # findings.md holds the concurrency and prefix-reuse tables; the page used to emit
        # them as literal pipe paragraphs, which reads as broken Markdown
        (self.tmp / "results").mkdir(exist_ok=True)
        (self.tmp / "results" / "findings.md").write_text(
            "Four requests at once:\n\n"
            "| | wall | first token |\n"
            "|---|---:|---:|\n"
            "| Halogen | 10.1 s | 4.3 s |\n"
            "| Kyojin | 12.3 s | 5.8 s |\n"
            "\nAfter the table.\n")
        p, out, issue = self.render()
        self.assertEqual(p.returncode, 0, p.stderr)
        html = (out / "index.html").read_text()
        self.assertIn('<table class="md">', html)
        self.assertIn('<th style="text-align:right">wall</th>', html)
        self.assertIn("<td>Halogen</td>", html)
        self.assertNotIn("| Halogen |", html, "the pipe row is still being printed as text")
        self.assertIn("After the table.", html)
        # the report page embeds the same table as markdown for GitHub; it stays markdown
        self.assertIn("| Halogen |", issue.read_text())

    def test_wrapped_prose_becomes_one_paragraph(self):
        # findings.md is hard-wrapped at ~80 columns; each source line is not a paragraph
        (self.tmp / "results").mkdir(exist_ok=True)
        (self.tmp / "results" / "findings.md").write_text(
            "one line\nsecond line of the same paragraph\n\n- a bullet\n- another\n\nnew para\n")
        p, out, issue = self.render()
        self.assertEqual(p.returncode, 0, p.stderr)
        html = (out / "index.html").read_text()
        self.assertIn("<p>one line second line of the same paragraph</p>", html)
        self.assertIn("<li>a bullet</li>", html)
        self.assertIn("<p>new para</p>", html)

    def test_a_wrapped_list_item_stays_one_item(self):
        (self.tmp / "results").mkdir(exist_ok=True)
        (self.tmp / "results" / "findings.md").write_text(
            "- Kyojin reported stop and **stopped in the middle\n"
            "  of a function** with no closing tags.\n"
            "- second\n\nAfter.\n")
        p, out, issue = self.render()
        self.assertEqual(p.returncode, 0, p.stderr)
        html = (out / "index.html").read_text()
        self.assertEqual(html.count("<li>Kyojin reported"), 1)
        self.assertIn("<li>Kyojin reported stop and <strong>stopped in the middle "
                      "of a function</strong> with no closing tags.</li>", html)
        self.assertNotIn("**", html)

    def test_a_broken_table_is_left_as_text(self):
        (self.tmp / "results").mkdir(exist_ok=True)
        (self.tmp / "results" / "findings.md").write_text(
            "| not a table | just a line |\nno delimiter follows\n")
        p, out, issue = self.render()
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertNotIn('<table class="md">', (out / "index.html").read_text())

    def test_the_raw_section_links_the_csv_when_it_exists(self):
        (self.tmp / "results").mkdir(exist_ok=True)
        (self.tmp / "results" / "measurements.csv").write_text("engine\n")
        p, out, issue = self.render()
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertIn("results/measurements.csv", (out / "index.html").read_text())

    def test_a_measurement_with_repetitions_gets_its_own_table(self):
        fixture = json.loads(json.dumps(FIXTURE))
        for e in fixture["measurements"]:
            if e["metric"] == "prefill_tps" and e["engine"] == "halogen":
                e["spread"] = {"n": 3, "min": 1563.4, "max": 1663.2}
        self.summary_path.write_text(json.dumps(fixture))
        p, out, issue = self.render()
        self.assertEqual(p.returncode, 0, p.stderr)
        html = (out / "index.html").read_text()
        self.assertIn("<h2>Repetitions</h2>", html)
        self.assertIn("1,563–1,663", html)
        self.assertIn("| Halogen | 3 |", issue.read_text())

    def test_bench_repetitions_become_a_spread(self):
        runs = self.tmp / "runs" / "halogen"
        runs.mkdir(parents=True)
        (runs / "env.txt").write_text("halogen_digest x\n")
        bench = {"prefill": {"tok_s": 1600.7, "prompt_tokens": 2737,
                             "runs": [1600.7, 1563.4, 1663.2]},
                 "decode": {"chat": {"tok_s": 53.6, "runs": [53.6, 54.7, 51.1]}}}
        (runs / "bench.txt").write_text(
            "### benchmark\n\n```json\n" + json.dumps(bench) + "\n```\n")
        out = self.tmp / "s.json"
        subprocess.run([sys.executable, "report/summary.py", "--runs", str(self.tmp / "runs"),
                        "--out", str(out), "--csv", str(self.tmp / "m.csv")],
                       cwd=REPO, capture_output=True, check=True)
        doc = json.loads(out.read_text())
        spreads = {(e["metric"], e["condition"]): e["spread"]
                   for e in doc["measurements"] if e.get("spread")}
        self.assertEqual(spreads[("prefill_tps", "bench.py method")],
                         {"n": 3, "min": 1563.4, "max": 1663.2})
        self.assertEqual(spreads[("decode_tps", "decode chat")],
                         {"n": 3, "min": 51.1, "max": 54.7})

    def test_variance_rows_render_as_a_table(self):
        fixture = json.loads(json.dumps(FIXTURE))
        fixture["schema"] = 2
        fixture["variance"] = [
            {"engine": "halogen", "phase": "variance-halogen", "metric": "decode_tps",
             "unit": "tok/s", "condition": "decode chat", "n": 3, "median": 53.6,
             "min": 51.1, "max": 54.7, "raw_path": "runs/variance-halogen/variance.json"},
            {"engine": "halogen", "phase": "variance-halogen", "metric": "ttft_s",
             "unit": "s", "condition": "prompt ~262K", "n": 3, "median": 149.1,
             "min": 149.003, "max": 149.307, "raw_path": "runs/variance-halogen/variance.json"},
        ]
        self.summary_path.write_text(json.dumps(fixture))
        p, out, issue = self.render()
        self.assertEqual(p.returncode, 0, p.stderr)
        html, md = (out / "index.html").read_text(), issue.read_text()
        self.assertIn("<h2>Variance</h2>", html)
        self.assertIn("149.0–149.3", html)
        self.assertIn("| Decode | decode chat | Halogen | 3 |", md)

    def test_privacy_guard_refuses_a_host_path(self):
        (self.tmp / "results").mkdir(exist_ok=True)
        (self.tmp / "results" / "findings.md").write_text("the log lives in /home/someone/apps\n")
        p, out, issue = self.render()
        self.assertNotEqual(p.returncode, 0, "a host path in the findings must stop the render")
        self.assertIn("refusing to publish", p.stderr)

    def test_unknown_metric_is_an_error_not_a_row(self):
        runs = self.tmp / "runs" / "halogen"
        runs.mkdir(parents=True)
        (runs / "env.txt").write_text("halogen_digest x\n")
        (runs / "startup.txt").write_text("first_start_to_models_s 37\n")
        (runs / "ctx.json").write_text(json.dumps({"runs": [{"requested_tokens": 32000,
                                                            "prompt_tokens": 30000,
                                                            "prefill_tps_server": 1800,
                                                            "ttft_s": 16.0}]}))
        p = subprocess.run([sys.executable, "report/summary.py", "--runs", str(self.tmp / "runs"),
                            "--out", str(self.tmp / "s.json"), "--csv", str(self.tmp / "m.csv")], cwd=REPO, capture_output=True, text=True)
        self.assertEqual(p.returncode, 0, p.stderr)
        doc = json.loads((self.tmp / "s.json").read_text())
        metrics = {e["metric"] for e in doc["measurements"]}
        self.assertIn("prefill_tps", metrics)
        self.assertTrue(all(m in {
            "prefill_tps", "prompt_tokens", "decode_tps", "ttft_s", "needle_found", "tool_call_ok",
            "tool_call_has_arguments", "vision_ok", "thinking_tokens", "aggregate_decode_tps",
            "per_request_decode_tps", "ttft_p50_s", "ttft_p95_s", "peak_in_flight",
            "prompt_cache_hit_tokens", "prefix_reuse_ttft_s", "prefix_cold_ttft_s", "startup_s",
            "artifact_tokens", "artifact_truncated", "artifact_complete_html", "quality_pass",
        } for m in metrics), metrics)

    def test_phase_without_env_is_rejected(self):
        runs = self.tmp / "runs" / "halogen"
        runs.mkdir(parents=True)
        (runs / "ctx.json").write_text(json.dumps({"runs": []}))
        p = subprocess.run([sys.executable, "report/summary.py", "--runs", str(self.tmp / "runs"),
                            "--out", str(self.tmp / "s.json"), "--csv", str(self.tmp / "m.csv")], cwd=REPO, capture_output=True, text=True)
        self.assertNotEqual(p.returncode, 0)
        self.assertIn("env.txt is missing", p.stderr)

    def test_record_provenance_wins_over_the_phase_capture(self):
        runs = self.tmp / "runs" / "halogen"
        runs.mkdir(parents=True)
        (runs / "env.txt").write_text("halogen_digest phase-level-digest\n")
        (runs / "ctx.json").write_text(json.dumps({
            "provenance": {"phase": "halogen", "digest": "digest-from-the-record"},
            "runs": [{"requested_tokens": 32000, "prompt_tokens": 30000,
                      "prefill_tps_server": 1800, "ttft_s": 16.0}]}))
        subprocess.run([sys.executable, "report/summary.py", "--runs", str(self.tmp / "runs"),
                        "--out", str(self.tmp / "s.json"), "--csv", str(self.tmp / "m.csv")], cwd=REPO, capture_output=True, check=True)
        doc = json.loads((self.tmp / "s.json").read_text())
        prefill = [e for e in doc["measurements"] if e["metric"] == "prefill_tps"
                   and e["engine"] == "halogen"]
        self.assertTrue(prefill)
        self.assertEqual(prefill[0]["digest"], "digest-from-the-record")
        self.assertEqual(prefill[0]["provenance_source"], "record")

    def test_aborted_phase_survives_into_the_summary(self):
        runs = self.tmp / "runs" / "halogen"
        runs.mkdir(parents=True)
        (runs / "env.txt").write_text("halogen_digest d\n")
        (runs / "WATCHDOG-KILL.txt").write_text("WATCHDOG 2026-10-21: MemAvailable 8GiB\n")
        (runs / "startup.txt").write_text("first_start_to_models_s 37\n")
        subprocess.run([sys.executable, "report/summary.py", "--runs", str(self.tmp / "runs"),
                        "--out", str(self.tmp / "s.json"), "--csv", str(self.tmp / "m.csv")], cwd=REPO, capture_output=True, check=True)
        doc = json.loads((self.tmp / "s.json").read_text())
        aborted = [e for e in doc["measurements"] if e["status"] == "aborted"]
        self.assertTrue(aborted, "an aborted phase must leave rows behind")
        self.assertTrue(all(e["abort_rule"] for e in aborted))
        self.assertTrue(any("WATCHDOG" in str(e["abort_rule"]) for e in aborted))

    def test_summary_is_idempotent(self):
        runs = self.tmp / "runs" / "halogen"
        runs.mkdir(parents=True)
        (runs / "env.txt").write_text("halogen_digest x\n")
        (runs / "ctx.json").write_text(json.dumps({"runs": [{"requested_tokens": 32000,
                                                            "prompt_tokens": 30000,
                                                            "prefill_tps_server": 1800,
                                                            "ttft_s": 16.0}]}))
        out = self.tmp / "s.json"
        for _ in range(2):
            subprocess.run([sys.executable, "report/summary.py", "--runs", str(self.tmp / "runs"),
                            "--out", str(out), "--csv", str(self.tmp / "m.csv")],
                           cwd=REPO, capture_output=True, check=True)
        first = out.read_bytes()
        subprocess.run([sys.executable, "report/summary.py", "--runs", str(self.tmp / "runs"),
                        "--out", str(out), "--csv", str(self.tmp / "m.csv")],
                       cwd=REPO, capture_output=True, check=True)
        self.assertEqual(first, out.read_bytes(), "same input, same bytes")


if __name__ == "__main__":
    unittest.main()
