#!/usr/bin/env python3
"""The prose must still be quoting the numbers.

`results/findings.md` is the only hand-written surface in the repository, and the spec's
own Problem Statement names it as the thing that will drift: "If I write the prose by hand
next to the JSON, the two will drift." A review pointed out that nothing checked it.

This does not try to understand the prose. It asserts that, for a list of claims the prose
makes, some rendering of the current summary value still appears in the file. Change a
number in the data without touching the sentence, and this fails.

    python3 -m unittest discover -s tests
"""
from __future__ import annotations

import json
import re
import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "report"))
from render import render_value  # noqa: E402  the same formatter the page uses
FINDINGS = REPO / "results" / "findings.md"
SUMMARY = REPO / "results" / "summary.json"

# (metric, condition, engine) — every pair is a number the prose states in a sentence.
CLAIMS = [
    ("decode_tps", "decode prose", "halogen"),
    ("decode_tps", "decode prose", "kyojin"),
    ("decode_tps", "decode chat", "halogen"),
    ("decode_tps", "decode chat", "kyojin"),
    ("decode_tps", "decode code", "halogen"),
    ("decode_tps", "decode code", "kyojin"),
    ("ttft_s", "prompt ~262K", "halogen"),
    ("ttft_s", "prompt ~262K", "kyojin"),
    ("startup_s", "first start", "halogen"),
    ("startup_s", "first start", "kyojin"),
    ("startup_s", "warm start", "halogen"),
    ("startup_s", "warm start", "kyojin"),
    ("prefix_cold_ttft_s", "cold control", "halogen"),
    ("prefix_cold_ttft_s", "cold control", "kyojin"),
    ("prefix_reuse_ttft_s", "same prefix again", "halogen"),
    ("prefix_reuse_ttft_s", "same prefix again", "kyojin"),
    ("thinking_tokens", "effort xhigh", "halogen"),
    ("thinking_tokens", "effort xhigh", "kyojin"),
    ("artifact_tokens", "pagoda one-shot", "halogen"),
    ("artifact_tokens", "pagoda one-shot", "kyojin"),
]


def renderings(metric: str, value) -> list[str]:
    """How the prose may write this value: the page's own rendering, and the raw form.

    Inventing a second set of rules here is how the matcher disagreed with the page: it
    demanded 148.0 where the prose and the report both say 148.
    """
    metrics = render_value(metric, value, "measured")
    out = {metrics, f"{value:g}", str(value)}
    return sorted({o for o in out if o})


def mentions(prose: str, text: str) -> bool:
    """A number match that is not a substring of a longer number."""
    return re.search(r"(?<![\d.])" + re.escape(text) + r"(?![\d])", prose) is not None


class FindingsDriftTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not FINDINGS.is_file() or not SUMMARY.is_file():
            raise unittest.SkipTest("no findings or no summary")
        cls.prose = FINDINGS.read_text()
        cls.rows = {(e["metric"], e["condition"], e["engine"]): e
                    for e in json.loads(SUMMARY.read_text())["measurements"]}

    def test_every_claimed_number_still_appears_in_the_prose(self):
        missing = []
        for key in CLAIMS:
            entry = self.rows.get(key)
            if not entry or entry["status"] != "measured":
                missing.append(f"{key}: not in the summary")
                continue
            options = renderings(key[0], entry["value"])
            if not any(mentions(self.prose, o) for o in options):
                missing.append(f"{key}: none of {options} appears in findings.md")
        self.assertEqual(missing, [], "\n".join(missing))

    def test_the_ordered_sentences_match_exactly(self):
        """A presence check cannot catch a swap when the number appears twice; these sentences
        are reconstructed from the summary, so order and value are both pinned."""
        def v(metric, cond, engine):
            e = self.rows[(metric, cond, engine)]
            return render_value(metric, e["value"], e["status"])

        decode = (f'{v("decode_tps", "decode prose", "halogen")} / '
                  f'{v("decode_tps", "decode chat", "halogen")} / '
                  f'{v("decode_tps", "decode code", "halogen")} tok/s against '
                  f'{v("decode_tps", "decode prose", "kyojin")} / '
                  f'{v("decode_tps", "decode chat", "kyojin")} / '
                  f'{v("decode_tps", "decode code", "kyojin")}')
        self.assertIn(decode, self.prose, "the decode sentence no longer matches the summary")

        for cond, phrase in (("prompt ~262K", "Time to first token at 250K"),
                             ("first start", "Startup is the largest")):
            if cond == "prompt ~262K":
                line = (f'{v("ttft_s", cond, "halogen")} s against '
                        f'{v("ttft_s", cond, "kyojin")} s')
            else:
                line = (f'{v("startup_s", cond, "halogen")} s against '
                        f'{v("startup_s", cond, "kyojin")} s')
            self.assertIn(line, self.prose, f"'{phrase}' no longer matches the summary")

        warm = (f'{v("startup_s", "warm start", "halogen")} s against '
                f'{v("startup_s", "warm start", "kyojin")} s')
        self.assertIn(warm, self.prose, "the warm-start sentence no longer matches the summary")

    def test_the_prose_does_not_quote_a_number_the_summary_lost(self):
        # 0.92 appeared in the issue body once, from a formatter bug; it must never come back
        self.assertNotIn("0.92", self.prose)

    def test_the_claim_sentence_is_present(self):
        self.assertIn("One sentence:", self.prose,
                      "the one-sentence claim the operator asked for must stay at the top")


if __name__ == "__main__":
    unittest.main()
