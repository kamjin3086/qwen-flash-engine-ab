"""The two surfaces must be built from one row model, so they cannot disagree."""
import json, sys, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "report"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import render

SAMPLE = [
    {"metric": "prefill_tps", "unit": "tok/s", "engine": "halogen", "phase": "halogen",
     "digest": "ghcr.io/x@sha256:" + "1" * 64, "condition": "prompt ~262K", "value": 1706.9,
     "raw_path": "runs/halogen/ctx.json", "status": "measured", "abort_rule": None,
     "provenance_source": "record"},
    {"metric": "prefill_tps", "unit": "tok/s", "engine": "kyojin", "phase": "kyojin-s1",
     "digest": "ghcr.io/y@sha256:" + "2" * 64, "condition": "prompt ~262K", "value": None,
     "raw_path": "runs/kyojin-s1/ctx.json", "status": "not_run", "abort_rule": None,
     "provenance_source": "absent"},
    {"metric": "prefill_tps", "unit": "tok/s", "engine": "halogen", "phase": "halogen",
     "digest": "ghcr.io/x@sha256:" + "1" * 64, "condition": "prompt ~32K", "value": 1850.5,
     "raw_path": "runs/halogen/ctx.json", "status": "measured", "abort_rule": None,
     "provenance_source": "record"},
    {"metric": "prefill_tps", "unit": "tok/s", "engine": "halogen", "phase": "halogen",
     "digest": "ghcr.io/x@sha256:" + "1" * 64, "condition": "prompt ~128K", "value": 1796.0,
     "raw_path": "runs/halogen/ctx.json", "status": "measured", "abort_rule": None,
     "provenance_source": "record"},
]


class RowModelTest(unittest.TestCase):
    def test_both_surfaces_cover_the_same_rows_in_the_same_order(self):
        rows = render.table_rows(SAMPLE)
        html = render.cell_table(SAMPLE)
        md = render.markdown_table(SAMPLE)
        conditions = [r.condition for r in rows]
        self.assertEqual(conditions, ["prompt ~32K", "prompt ~128K", "prompt ~262K"],
                         "conditions are ordered naturally, not lexicographically")
        positions = [html.index(c) for c in conditions]
        self.assertEqual(positions, sorted(positions), "the page uses the row model's order")
        positions = [md.index(c) for c in conditions]
        self.assertEqual(positions, sorted(positions), "the issue body uses the row model's order")

    def test_a_missing_engine_is_the_same_row_on_both(self):
        rows = {r.condition: r for r in render.table_rows(SAMPLE)}
        row = rows["prompt ~262K"]
        self.assertEqual(row.cells["kyojin"]["status"], "not_run")
        self.assertEqual(row.cells["halogen"]["value"], 1706.9)
        html, md = render.cell_table(SAMPLE), render.markdown_table(SAMPLE)
        self.assertIn("not run", html)
        self.assertIn("_not run_", md)
        self.assertIn("prompt ~262K", html)
        self.assertIn("prompt ~262K", md)

    def test_label_and_phase_are_the_same_on_both_surfaces(self):
        rows = {r.condition: r for r in render.table_rows(SAMPLE)}
        row = rows["prompt ~32K"]
        html, md = render.cell_table(SAMPLE), render.markdown_table(SAMPLE)
        self.assertIn(row.label, html)
        self.assertIn(row.label, md)
        # the composite, not each half: "-" alone matches the separator row and makes this
        # assertion vacuous
        self.assertIn(f"{row.phase_label('halogen')} / {row.phase_label('kyojin')}", md,
                      "the Phase (H / K) column must name both phases on the issue surface")
        self.assertNotIn("- / -", md)
        self.assertIn('class="prov"', html)

    def test_a_third_engine_gets_a_column_instead_of_a_fabricated_gap(self):
        saved = render.ENGINES
        try:
            render.ENGINES = ("halogen", "kyojin", "glm")
            sample = [dict(m, engine=e) for m in SAMPLE[:1] for e in render.ENGINES]
            html, md = render.cell_table(sample), render.markdown_table(sample)
            self.assertEqual(html.count('<th scope="col">'), 5, "two label columns plus three engines")
            self.assertEqual(md.count("| Glm |"), 1, "the third engine has its own column")
            self.assertNotIn("_not run_", md, "a measured value must never be reported as a gap")
        finally:
            render.ENGINES = saved
