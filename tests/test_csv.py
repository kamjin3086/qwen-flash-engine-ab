#!/usr/bin/env python3
"""The CSV is the same rows as the summary, not a second record.

A flat file that is written by hand drifts from the JSON the moment a measurement is added.
This asserts one row per measurement, the same values, and that the committed file is what
the generator produces from the committed summary.

    python3 -m unittest discover -s tests
"""
from __future__ import annotations

import csv
import io
import json
import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "report"))
import summary  # noqa: E402

CSV_PATH = REPO / "results" / "measurements.csv"
SUMMARY = REPO / "results" / "summary.json"


class CsvTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.doc = json.loads(SUMMARY.read_text())
        cls.text = CSV_PATH.read_text()
        cls.rows = list(csv.DictReader(io.StringIO(cls.text)))
        cls.measurements = cls.doc["measurements"]

    def test_one_row_per_measurement(self):
        self.assertEqual(len(self.rows), self.doc["counts"]["total"])
        self.assertEqual(tuple(self.rows[0].keys()), summary.CSV_COLUMNS)

    def test_the_values_are_the_json_values(self):
        for row, e in zip(self.rows, self.measurements):
            for key in ("engine", "phase", "metric", "unit", "condition", "status"):
                self.assertEqual(row[key], str(e[key]), f"{key} of {e['metric']}/{e['condition']}")
            if e["value"] is None:
                self.assertEqual(row["value"], "")
            elif isinstance(e["value"], bool):
                self.assertEqual(row["value"], "true" if e["value"] else "false")
            else:
                self.assertEqual(row["value"], str(e["value"]))

    def test_it_is_generated_not_hand_written(self):
        self.assertEqual(self.text, summary.csv_text(self.doc))

    def test_not_run_rows_are_present_and_empty(self):
        not_run = [r for r in self.rows if r["status"] == "not_run"]
        self.assertTrue(not_run, "the CSV should carry the not-run rows too")
        self.assertTrue(all(r["value"] == "" for r in not_run))


if __name__ == "__main__":
    unittest.main()
