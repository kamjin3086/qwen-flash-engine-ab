#!/usr/bin/env python3
"""Render the summary into the two human surfaces and the artifact copies.

One code path writes both `docs/index.html` and the Markdown body for the maintainer's
issue, from the same summary, so the two cannot disagree about a number.

    python3 report/render.py --summary results/summary.json --out docs --issue results/issue-body.md

The generator refuses to write anything that contains an absolute host path or the
operator's username, and refuses to embed an artifact whose recorded hash no longer
matches the file.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import shutil
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from html import escape
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import privacy  # noqa: E402  the one check, shared with the export
from charts import ENGINE_LABEL, bar_chart, line_chart  # noqa: E402
from summary import ENGINES, METRICS  # noqa: E402  one registry, one engine list
REPO_ROOT = Path(__file__).resolve().parent.parent
LINK_ROOT = REPO_ROOT  # set from --repo in main(); raw links are checked against it

LABEL = {
    "prefill_tps": "Prefill",
    "prompt_tokens": "Prompt tokens",
    "decode_tps": "Decode",
    "ttft_s": "Time to first token",
    "needle_found": "Fact retrieved at depth",
    "tool_call_ok": "Tool call emitted",
    "tool_call_has_arguments": "Tool call carries arguments",
    "vision_ok": "Image input understood",
    "thinking_tokens": "Thinking tokens at xhigh",
    "aggregate_decode_tps": "Aggregate decode, all requests",
    "per_request_decode_tps": "Decode per request (median)",
    "ttft_p50_s": "First token, median across requests",
    "ttft_p95_s": "First token, 95th percentile",
    "peak_in_flight": "Requests actually in flight",
    "prompt_cache_hit_tokens": "Prompt tokens served from cache",
    "prefix_reuse_ttft_s": "First token, repeated prefix",
    "prefix_cold_ttft_s": "First token, cold prefix",
    "startup_s": "Time to a usable server",
    "artifact_tokens": "Pagoda output tokens",
    "artifact_truncated": "Pagoda output truncated",
    "artifact_complete_html": "Pagoda output is complete HTML",
    "quality_case_pass": "Script-checkable case",
    "quality_pass_rate": "Script-checkable cases passed",
}
UNIT = {"tok/s": "tok/s", "s": "s", "bool": "", "tokens": "", "requests": "", "%": "%"}

SCOPE = [
    "Two engines, one model, one machine, measured one at a time because both cannot be resident together.",
    "The two packs are different quantizations of the same model (a 62.1 GiB checkpoint on Halogen, an EXL3 "
    "4.0 bpw pack on Kyojin). Speed figures therefore describe engine **and** quantization together.",
    "The output checks below decide whether a piece of output is usable. They are not a quality verdict, and "
    "nothing here scores prose or taste.",
    "Kyojin was raised from its container defaults to the configuration Halogen actually runs: full context, "
    "vision on, the same reply budget. Numbers at stock defaults are not reported.",
]

FINDINGS_HEADING = "What the numbers say"


# ---------------------------------------------------------------- helpers

def render_value(metric: str, value, status: str) -> str:
    """The single formatter for a measured value, used by the page and the issue body.

    Two formatters is how the two surfaces come to print 92% and 0.92 for the same number.
    """
    if status != "measured" or value is None:
        return status.replace("_", " ")
    if isinstance(value, bool):
        return "yes" if value else "no"
    if metric == "quality_pass_rate" and isinstance(value, (int, float)) and not isinstance(value, bool):
        return f"{float(value):.0%}"
    if isinstance(value, float) and value.is_integer():
        value = int(value)  # 37.0 is 37: a measured whole number should not print a .0
    if isinstance(value, int):
        return f"{value:,}"
    if isinstance(value, float):
        if abs(value) >= 100:
            return f"{value:,.0f}"
        if abs(value) >= 10:
            return f"{value:,.1f}"
        return f"{value:.2f}".rstrip("0").rstrip(".")
    return str(value)


def fmt(metric: str, value, status: str) -> str:
    text = render_value(metric, value, status)
    if status != "measured" or value is None:
        return f'<span class="miss">{escape(text)}</span>'
    return escape(text)


def fmt_range(metric: str, lo, hi) -> str:
    """Both endpoints, never collapsed into the same printed number.

    An interval of 149.003–149.307 s is not "149–149": at the metric's usual precision the
    two ends print alike, which reads as no spread at all. Only when that happens, both
    ends get one decimal more.
    """
    a, b = render_value(metric, lo, "measured"), render_value(metric, hi, "measured")
    if a == b:
        a, b = _one_digit_more(lo), _one_digit_more(hi)
    return f"{a}–{b}"


def _one_digit_more(value) -> str:
    if isinstance(value, int):
        return f"{value:,}"
    if abs(value) >= 100:
        return f"{value:,.1f}"
    if abs(value) >= 10:
        return f"{value:,.2f}".rstrip("0").rstrip(".")
    return f"{value:.3f}".rstrip("0").rstrip(".")


def digest_short(d: str | None) -> str:
    if not d:
        return "unknown"
    m = re.search(r"sha256:([0-9a-f]{12})", d)
    return m.group(1) if m else d[:24]


def natural(text: str):
    return [int(t) if t.isdigit() else t.lower() for t in re.split(r"(\d+)", text)]


def rows_by_metric(measurements: list[dict]) -> dict[str, list[dict]]:
    order = list(LABEL)
    out: dict[str, list[dict]] = {}
    for m in measurements:
        out.setdefault(m["metric"], []).append(m)
    return {k: sorted(out[k], key=lambda e: (natural(e["condition"]), e["engine"]))
            for k in order if k in out}


def abort_band(measurements: list[dict]) -> str:
    """A phase that hit an abort rule is stated above the tables, not left to be inferred."""
    aborted = [(m["engine"], m["phase"], m["abort_rule"]) for m in measurements
               if m["status"] == "aborted"]
    if not aborted:
        return ""
    seen, items = set(), []
    for engine, phase, rule in aborted:
        if (engine, phase) in seen:
            continue
        seen.add((engine, phase))
        items.append(f'<li><strong>{escape(engine.title())}</strong>, phase <code>{escape(phase)}</code>: '
                     f'stopped by <span class="flag">{escape(str(rule))}</span></li>')
    return ('<div class="scope" style="border-color:#7a4a12">'
            "<p><strong>An aborted phase</strong> — these measurements did not finish, and the rows they "
            "would have filled are marked <em>aborted</em> rather than omitted:</p><ul>"
            + "".join(items) + "</ul></div>")


@dataclass
class TableRow:
    """One line of the comparison: a measurement, a condition, and a cell per engine.

    Both surfaces are rendered from this, so they cannot disagree about which rows exist,
    in what order, or what is missing. Deliberately not frozen: `cells` refers to the
    measurement dicts themselves, so it is unhashable and a frozen shell would imply a
    hashability the class does not have.
    """

    metric: str
    condition: str
    label: str
    cells: dict[str, dict]

    def engine(self, name: str) -> dict | None:
        return self.cells.get(name)

    def phase_label(self, name: str) -> str:
        entry = self.engine(name)
        return (entry.get("phase") if entry else None) or "-"


def table_rows(measurements: list[dict]) -> list[TableRow]:
    rows: list[TableRow] = []
    for metric, items in rows_by_metric(measurements).items():
        for cond in sorted({i["condition"] for i in items}, key=natural):
            rows.append(TableRow(
                metric=metric,
                condition=cond,
                label=LABEL.get(metric, metric),
                cells={i["engine"]: i for i in items if i["condition"] == cond},
            ))
    return rows


def cell_table(measurements: list[dict]) -> str:
    """The headline table: a row per measurement and condition, a column per engine."""
    rows = []
    for row in table_rows(measurements):
        cells = []
        for engine in ENGINES:
            e = row.engine(engine)
            if not e:
                cells.append('<td class="miss">not run</td>')
                continue
            val = fmt(row.metric, e["value"], e["status"])
            link = ""
            if e["raw_path"] and (LINK_ROOT / e["raw_path"]).is_file():
                link = (f' <a class="raw" href="{escape(rel(e["raw_path"]))}" '
                        f'title="{escape(e["raw_path"])}">raw</a>')
            prov = (f'{escape(e["phase"])} &middot; ' if e.get("phase") else "") + \
                   escape(digest_short(e.get("digest")))
            cells.append(f'<td class="num">{val}{link}<span class="prov">{prov}</span></td>')
        rows.append(
            f'<tr><th scope="row">{escape(row.label)}</th>'
            f'<td class="cond">{escape(row.condition)}</td>{"".join(cells)}</tr>')
    head = "".join(f'<th scope="col">{escape(ENGINE_LABEL.get(e, e.title()))}</th>' for e in ENGINES)
    # The table is wider than a phone at its natural width (numbers and provenance are
    # unbreakable by design). Scroll the table, not the page: role+tabindex so a keyboard
    # can reach it, which a plain overflow box does not give.
    return (
        '<p class="tscroll">The table scrolls sideways when the screen is too narrow for '
        'both engines; the measurement column stays put.</p>'
        '<div class="tablewrap" role="region" aria-label="Measurements" tabindex="0">'
        '<table class="headline"><thead><tr><th scope="col">Measurement</th>'
        f'<th scope="col">Condition</th>{head}</tr></thead><tbody>'
        + "".join(rows) + "</tbody></table></div>")


def spread_rows(measurements: list[dict]) -> list[tuple[TableRow, dict[str, dict]]]:
    rows = []
    for row in table_rows(measurements):
        cells = {e: row.engine(e) for e in ENGINES}
        if any(c and c.get("spread") for c in cells.values()):
            rows.append((row, cells))
    return rows


def spread_table(measurements: list[dict]) -> str:
    """The repetitions behind the numbers that have them, as their own small table."""
    rows = spread_rows(measurements)
    if not rows:
        return ""
    body = []
    for row, cells in rows:
        for engine in ENGINES:
            e = cells.get(engine)
            if not e or not e.get("spread"):
                continue
            sp = e["spread"]
            body.append(
                f'<tr><th scope="row">{escape(row.label)}</th>'
                f'<td class="cond">{escape(row.condition)}</td>'
                f'<td>{escape(ENGINE_LABEL.get(engine, engine.title()))}</td>'
                f'<td class="num">{sp["n"]}</td>'
                f'<td class="num">{fmt(row.metric, e["value"], "measured")}</td>'
                f'<td class="num">{escape(fmt_range(row.metric, sp["min"], sp["max"]))}</td></tr>')
    return ('<h2>Repetitions</h2>'
            '<p class="sub">Prefill and decode at the author\'s sizes are the median of '
            'three runs. This is what the three runs were, so a reader can see whether a '
            'difference is larger than the spread.</p>'
            '<div class="tablewrap" role="region" aria-label="Repetitions" tabindex="0">'
            '<table class="spread"><thead><tr><th>Measurement</th><th>Condition</th>'
            '<th>Engine</th><th style="text-align:right">n</th>'
            '<th style="text-align:right">Median</th>'
            '<th style="text-align:right">Range</th></tr></thead><tbody>'
            + "".join(body) + "</tbody></table></div>")


def spread_markdown(measurements: list[dict]) -> list[str]:
    rows = spread_rows(measurements)
    if not rows:
        return []
    out = ["## Repetitions", "",
           "| Measurement | Condition | Engine | n | Median | Range |",
           "|---|---|---|---:|---:|---:|"]
    for row, cells in rows:
        for engine in ENGINES:
            e = cells.get(engine)
            if not e or not e.get("spread"):
                continue
            sp = e["spread"]
            out.append(f'| {row.label} | {row.condition} | '
                       f'{ENGINE_LABEL.get(engine, engine.title())} | {sp["n"]} | '
                       f'{fmt(row.metric, e["value"], "measured")} | '
                       f'{fmt_range(row.metric, sp["min"], sp["max"])} |')
    out.append("")
    return out


def variance_table(summary: dict) -> str:
    rows = summary.get("variance") or []
    if not rows:
        return ""
    notes = "".join(f'<p class="sub">{escape(n)}</p>' for n in summary.get("variance_notes") or [])
    body = []
    for v in rows:
        body.append(
            f'<tr><th scope="row">{escape(LABEL.get(v["metric"], v["metric"]))}</th>'
            f'<td class="cond">{escape(v["condition"])}</td>'
            f'<td>{escape(ENGINE_LABEL.get(v["engine"], v["engine"].title()))}</td>'
            f'<td class="num">{v["n"]}</td>'
            f'<td class="num">{fmt(v["metric"], v["median"], "measured")}</td>'
            f'<td class="num">{escape(fmt_range(v["metric"], v["min"], v["max"]))}</td></tr>')
    return ('<h2>Variance</h2>'
            '<p class="sub">The same configuration measured three times in one start, for '
            'the numbers the verdict leans on. The headline table above is the original run; '
            "this is how far a repetition of it travels. These were measured in a separate "
            "start, so their medians sit a little away from the headline column; the table is "
            "the spread within a start, not absolute agreement between sessions. Decode rows are the original "
            "run's three repetitions per prompt class, the same data as Repetitions above; "
            "the context rows were re-measured.</p>"
            f'{notes}'
            '<div class="tablewrap" role="region" aria-label="Variance" tabindex="0">'
            '<table class="spread"><thead><tr><th>Measurement</th><th>Condition</th>'
            '<th>Engine</th><th style="text-align:right">n</th>'
            '<th style="text-align:right">Median</th>'
            '<th style="text-align:right">Range</th></tr></thead><tbody>'
            + "".join(body) + "</tbody></table></div>")


def variance_markdown(summary: dict) -> list[str]:
    rows = summary.get("variance") or []
    if not rows:
        return []
    out = ["## Variance", "",
           "Decode rows are the original run's three repetitions per prompt class (the same "
           "data as the Repetitions table); the context and N=4 rows were re-measured.", "",
           "| Measurement | Condition | Engine | n | Median | Range |",
           "|---|---|---|---:|---:|---:|"]
    for v in rows:
        out.append(f'| {LABEL.get(v["metric"], v["metric"])} | {v["condition"]} | '
                   f'{ENGINE_LABEL.get(v["engine"], v["engine"].title())} | {v["n"]} | '
                   f'{fmt(v["metric"], v["median"], "measured")} | '
                   f'{fmt_range(v["metric"], v["min"], v["max"])} |')
    out += [""] + [f"> {n}" for n in summary.get("variance_notes") or []]
    out.append("")
    return out


def strip_title(md: str) -> str:
    """The findings file starts with its own H1; the page and the issue add the heading."""
    lines = md.lstrip().splitlines()
    if lines and lines[0].startswith("# "):
        lines = lines[1:]
    return "\n".join(lines).lstrip("\n")


def rel(raw_path: str) -> str:
    """Link from docs/ back to the repository root."""
    return "../" + raw_path.lstrip("./")


def md_cell(metric: str, value, status: str) -> str:
    text = render_value(metric, value, status)
    return f"_{text}_" if status != "measured" or value is None else text


def markdown_table(measurements: list[dict]) -> str:
    engines = list(ENGINES)
    header = "| Measurement | Condition | " + " | ".join(
        ENGINE_LABEL.get(e, e.title()) for e in engines)
    header += " | Phase (" + " / ".join(e[0].upper() for e in engines) + ") |"
    lines = [header, "|" + "---|" * (len(engines) + 3)]
    for row in table_rows(measurements):
        cells = []
        for engine in engines:
            e = row.engine(engine)
            cells.append(md_cell(row.metric, e["value"], e["status"]) if e else "_not run_")
        phases = " / ".join(row.phase_label(e) for e in engines)
        lines.append(f"| {row.label} | {row.condition} | " + " | ".join(cells) + f" | {phases} |")
    return "\n".join(lines)


# Why a row has no value. The reason is a property of the engine, not of the run, so it
# lives beside the table that shows the hole. A not-run row with no entry here still reads
# "not run" in its cell; this only stops the reader having to guess for the known one.
NOT_RUN_REASONS = {
    ("kyojin", "peak_in_flight"):
        "Kyojin's /health answers, but publishes no in-flight or queued counters, so request "
        "occupancy cannot be observed on that engine.",
}


def not_run_note(measurements: list[dict]) -> str:
    reasons: list[str] = []
    for e in measurements:
        if e.get("status") != "not_run":
            continue
        reason = NOT_RUN_REASONS.get((e["engine"], e["metric"]))
        if reason and reason not in reasons:
            reasons.append(reason)
    return " ".join(reasons)


# ---------------------------------------------------------------- charts

def build_charts(measurements: list[dict]) -> str:
    # the x axis is the prompt size the engine actually saw, per engine: the two tokenizers
    # disagree by a few thousand tokens on the same text, and the axis should say so
    real_tokens = {(m["engine"], m["condition"]): m["value"] for m in measurements
                   if m["metric"] == "prompt_tokens" and m["status"] == "measured"}

    def series(metric: str, x_of):
        out: dict[str, list[tuple[float, float | None]]] = {}
        for m in measurements:
            if m["metric"] != metric:
                continue
            x = x_of(m["engine"], m["condition"])
            if x is None:
                # the measurement was not run, so it has no prompt-token count either:
                # fall back to the requested size so the gap still lands on the axis
                asked = re.match(r"prompt ~(\d+)K", m["condition"])
                x = float(int(asked.group(1)) * 1000) if asked else None
            if x is None:
                continue
            out.setdefault(m["engine"], []).append(
                (x, m["value"] if m["status"] == "measured" else None))
        for pts in out.values():
            pts.sort()
        return out

    def ctx_x(engine: str, cond: str):
        if not re.match(r"prompt ~\d+K", cond):
            return None
        return real_tokens.get((engine, cond))

    chunks = []
    pre = series("prefill_tps", ctx_x)
    if pre:
        chunks.append(line_chart(pre, x_label="prompt tokens", y_label="prefill tok/s",
                                 title="Prefill against context length"))
    ttft = series("ttft_s", ctx_x)
    if ttft:
        chunks.append(line_chart(ttft, x_label="prompt tokens", y_label="seconds",
                                 title="Time to first token against context length"))

    dec = [{"label": c.split("decode ")[-1],
            "values": {m["engine"]: (m["value"] if m["status"] == "measured" else None)
                       for m in measurements if m["metric"] == "decode_tps" and m["condition"] == c}}
           for c in sorted({m["condition"] for m in measurements if m["metric"] == "decode_tps"})]
    if dec:
        chunks.append(bar_chart(dec, y_label="tok/s", title="Decode by prompt class (author's own method)"))

    ns = sorted({m["condition"] for m in measurements if m["metric"] == "aggregate_decode_tps"})
    conc = [{"label": c,
             "values": {m["engine"]: (m["value"] if m["status"] == "measured" else None)
                        for m in measurements if m["metric"] == "aggregate_decode_tps" and m["condition"] == c}}
            for c in ns]
    conc_p = [{"label": c,
               "values": {m["engine"]: (m["value"] if m["status"] == "measured" else None)
                          for m in measurements if m["metric"] == "per_request_decode_tps" and m["condition"] == c}}
              for c in ns]
    if conc:
        chunks.append(bar_chart(conc, y_label="tok/s", title="Aggregate decode with N requests in flight"))
    if conc_p:
        chunks.append(bar_chart(conc_p, y_label="tok/s", title="Decode per request (median) at N requests in flight"))

    startup = [{"label": c,
                "values": {m["engine"]: (m["value"] if m["status"] == "measured" else None)
                           for m in measurements if m["metric"] == "startup_s" and m["condition"] == c}}
               for c in sorted({m["condition"] for m in measurements if m["metric"] == "startup_s"})]
    if startup:
        chunks.append(bar_chart(startup, y_label="seconds", title="Time from start command to a usable server"))

    reuse = [{"label": c,
              "values": {m["engine"]: (m["value"] if m["status"] == "measured" else None)
                         for m in measurements
                         if m["metric"] in ("prefix_cold_ttft_s", "prefix_reuse_ttft_s") and m["condition"] == c}}
             for c in sorted({m["condition"] for m in measurements if m["metric"] == "prefix_cold_ttft_s"})]
    if reuse:
        chunks.append(bar_chart(reuse, y_label="seconds", title="First token: cold prefix vs the same prefix again"))
    return "\n".join(chunks)


# ---------------------------------------------------------------- artifacts

def extract_html(body: str) -> tuple[str, bool, bool]:
    """Pull the document out of a fenced block when the model wrapped it in Markdown.

    Returns (html, was_fenced, has_prose_before). Recorded rather than silently hidden:
    "the model answered in a code fence" is a fact about the answer, not a detail to
    clean away without saying so.
    """
    m = re.search(r"```(?:html|HTML)?\s*\n(.*?)(?:```|$)", body, re.S)
    if not m:
        return body, False, False
    inner = m.group(1)
    prose = body[:m.start()].strip()
    return inner, True, bool(prose)


def copy_artifacts(repo: Path, out: Path) -> list[dict]:
    """Copy the model-authored pages into the published tree and record their hashes."""
    dest = out / "artifacts"
    dest.mkdir(parents=True, exist_ok=True)
    found = []
    for engine, phase in (("halogen", "halogen"), ("halogen", "halogen-extra"), ("kyojin", "kyojin-s1"), ("kyojin", "kyojin-s4")):
        src = repo / "runs" / phase
        if not src.is_dir():
            continue
        for task in ("pagoda", "hexagon"):
            f = src / f"artifact-{task}.html"
            if not f.is_file():
                continue
            raw = f.read_text(errors="replace")
            body, fenced, prose = extract_html(raw)
            h = hashlib.sha256(body.encode()).hexdigest()
            name = f"{engine}-{task}.html"
            (dest / name).write_text(body)
            meta = src / f"artifact-{task}.json"
            meta_doc = json.loads(meta.read_text()) if meta.is_file() else {}
            # integrity is checked against the bytes as the engine wrote them, not against
            # the extracted document, so the check stays exact when a fenced block is unwrapped
            raw_hash = hashlib.sha256(raw.encode()).hexdigest()
            recorded = meta_doc.get("artifact_sha256")
            if recorded and recorded != raw_hash:
                raise SystemExit(f"{f}: recorded hash {recorded[:12]} does not match the file {raw_hash[:12]}")
            external = sorted(set(re.findall(r"https?://([^/\"'\s)]+)", body)))
            found.append({"engine": engine, "task": task, "path": f"artifacts/{name}",
                          "sha256": h, "bytes": len(body), "external_refs": external,
                          "wrapped_in_fence": fenced, "prose_before_html": prose,
                          "raw_sha256": raw_hash,
                          "meta": {k: meta_doc.get(k) for k in
                                   ("completion_tokens", "finish_reason", "truncated",
                                    "looks_complete_html", "wall_s") if k in meta_doc}})
    return found


def artifact_section(artifacts: list[dict]) -> str:
    if not artifacts:
        return '<p class="muted">No artifact page was produced by this run.</p>'
    cards = []
    for a in artifacts:
        meta = a["meta"]
        bits = []
        if meta.get("completion_tokens"):
            bits.append(f'{meta["completion_tokens"]:,} tokens')
        if meta.get("wall_s"):
            bits.append(f'{meta["wall_s"]}s')
        if meta.get("finish_reason"):
            bits.append(f'finish: {meta["finish_reason"]}')
        if meta.get("truncated") is not None:
            bits.append("truncated" if meta["truncated"] else "not truncated")
        if a.get("wrapped_in_fence"):
            bits.append("answered inside a Markdown fence" + (", after a prose preamble"
                        if a.get("prose_before_html") else ""))
        refs = a.get("external_refs") or []
        bits.append("loads nothing external" if not refs
                    else f'depends on {len(refs)} external host(s): {", ".join(refs[:3])}')
        shot = Path("docs") / "shots" / f'{a["engine"]}-{a["task"]}.png'
        shot_html = ""
        if shot.is_file():
            shot_html = (f'<a href="shots/{escape(a["engine"])}-{escape(a["task"])}.png">'
                         f'<img class="shot" src="shots/{escape(a["engine"])}-{escape(a["task"])}.png" '
                         f'alt="{escape(a["engine"] + " " + a["task"])}"></a>')
        cards.append(f'''<figure class="art">
  <figcaption><strong>{escape(a["engine"].title())}</strong>, {escape(a["task"])} &middot; {" &middot; ".join(escape(b) for b in bits)}
  <br><a href="{escape(a["path"])}">open full page</a> &middot; <code>sha256:{a["sha256"][:12]}</code></figcaption>
  {shot_html}
  <iframe src="{escape(a["path"])}" loading="lazy" title="{escape(a["engine"] + " " + a["task"])}"></iframe>
</figure>''')
    return "\n".join(cards)


# ---------------------------------------------------------------- markdown-lite

TABLE_DELIMITER = re.compile(r"^:?-{2,}:?$")


def md_cells(line: str) -> list[str]:
    """Split one pipe-table row. The outer pipes are optional; inner empties are cells."""
    body = line.strip()
    body = body[1:] if body.startswith("|") else body
    body = body[:-1] if body.endswith("|") else body
    return [cell.strip() for cell in body.split("|")]


def is_table_delimiter(line: str) -> bool:
    cells = [c.replace(" ", "") for c in md_cells(line)]
    return bool(cells) and all(TABLE_DELIMITER.match(c) for c in cells)


def table_align(cell: str) -> str:
    c = cell.replace(" ", "")
    left, right = c.startswith(":"), c.endswith(":")
    return "center" if left and right else "right" if right else "left" if left else ""


def table_html(header: list[str], aligns: list[str], rows: list[list[str]]) -> str:
    def cell(tag: str, text: str, i: int) -> str:
        align = aligns[i] if i < len(aligns) else ""
        style = f' style="text-align:{align}"' if align else ""
        return f"<{tag}{style}>{inline(text)}</{tag}>"

    head = "".join(cell("th", h, i) for i, h in enumerate(header))
    body = "".join("<tr>" + "".join(cell("td", c, i) for i, c in enumerate(row)) + "</tr>"
                   for row in rows)
    # findings.md carries tables (concurrency, prefix reuse); they are data, so they scroll
    # in a box of their own on a phone instead of widening the page
    return ('<div class="tablewrap" role="region" tabindex="0">'
            f'<table class="md"><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table></div>')


def md_to_html(text: str) -> str:
    """The small Markdown the findings file uses: headings, lists, pipe tables, inline.

    Source lines are hard-wrapped at about 80 columns, so a line break is not a paragraph
    and not a new list item: consecutive lines are joined until a blank line, a heading, a
    list marker or a table ends the block. Without that, every source line renders as its
    own paragraph, and a bold span that wraps renders as literal asterisks.
    """
    lines = text.splitlines()
    out: list[str] = []
    para: list[str] = []
    items: list[list[str]] = []

    def flush() -> None:
        if para:
            out.append(f"<p>{inline(' '.join(para))}</p>")
            para.clear()
        if items:
            out.append("<ul>" + "".join(f"<li>{inline(' '.join(item))}</li>" for item in items)
                       + "</ul>")
            items.clear()

    i = 0
    while i < len(lines):
        line = lines[i].rstrip()
        if not line.strip():
            flush()
            i += 1
            continue
        if (line.lstrip().startswith("|") and i + 1 < len(lines)
                and is_table_delimiter(lines[i + 1])):
            flush()
            header = md_cells(line)
            aligns = [table_align(c) for c in md_cells(lines[i + 1])]
            i += 2
            rows = []
            while i < len(lines) and lines[i].strip().startswith("|"):
                rows.append(md_cells(lines[i]))
                i += 1
            out.append(table_html(header, aligns, rows))
            continue
        if line.startswith("#"):
            flush()
            level = min(4, len(line) - len(line.lstrip("#")))
            out.append(f"<h{level + 1}>{inline(line.lstrip('# ').strip())}</h{level + 1}>")
        elif line.lstrip().startswith(("- ", "* ")):
            if para:
                flush()
            items.append([line.lstrip()[2:]])
        elif items and line.startswith((" ", "\t")):
            items[-1].append(line.strip())
        else:
            if items:
                flush()
            para.append(line.strip())
        i += 1
    flush()
    return "\n".join(out)


def inline(text: str) -> str:
    t = escape(text)
    t = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", t)
    t = re.sub(r"(?<!\*)\*([^*]+)\*(?!\*)", r"<em>\1</em>", t)
    t = re.sub(r"`(.+?)`", r"<code>\1</code>", t)
    t = re.sub(r"(?<![\"=])(https?://[^\s<]+)", r'<a href="\1">\1</a>', t)
    return t


# ---------------------------------------------------------------- assembly

CSS = """
:root{--bg:#101419;--fg:#e7edf5;--mut:#8b9bb0;--line:#26313d;--card:#161d25;--h:#4f9dff;--k:#f0a03c}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--fg);font:15px/1.55 ui-sans-serif,system-ui,-apple-system,Segoe UI,Roboto,sans-serif}
main{max-width:1080px;margin:0 auto;padding:28px 18px 80px}
h1{font-size:1.6rem;margin:0 0 6px}h2{font-size:1.15rem;margin:34px 0 10px;border-bottom:1px solid var(--line);padding-bottom:6px}
h3{font-size:1rem;margin:20px 0 6px}
a{color:var(--h)}code{background:#1d252f;padding:1px 5px;border-radius:4px;font-size:.86em}
.sub{color:var(--mut);font-size:.9rem;margin:0 0 18px}
table{border-collapse:collapse;width:100%;font-size:.9rem}
table.md{font-size:.88rem;margin:12px 0 18px}
table.spread{font-size:.85rem}
th,td{padding:6px 8px;border-bottom:1px solid var(--line);text-align:left;vertical-align:top}
thead th{color:var(--mut);font-weight:600;font-size:.82rem;text-transform:uppercase;letter-spacing:.03em}
td.num{text-align:right;font-variant-numeric:tabular-nums;white-space:nowrap}
td.cond{color:var(--mut)}
.prov{display:block;font-size:.72rem;color:var(--mut)}
.raw{font-size:.7rem;color:var(--mut);text-decoration:none;border:1px solid var(--line);border-radius:3px;padding:0 3px}
.miss{color:var(--mut);font-style:italic}
.scope{background:var(--card);border:1px solid var(--line);border-radius:8px;padding:14px 18px}
.scope li{margin:4px 0}
.chart{width:100%;height:auto;margin:10px 0 22px;background:var(--card);border:1px solid var(--line);border-radius:8px}
.chart .grid{stroke:#22303d;stroke-width:1}
.chart .ax{fill:var(--mut);font-size:11px}
.chart .ct{fill:var(--fg);font-size:12px;font-weight:600}
.chart .val{fill:var(--fg);font-size:10px}
.chart .miss{fill:var(--mut);font-size:9px;font-style:italic}
.art{margin:0 0 22px;background:var(--card);border:1px solid var(--line);border-radius:8px;overflow:hidden}
.art figcaption{padding:10px 14px;font-size:.85rem;color:var(--mut)}
.art iframe{width:100%;height:420px;border:0;border-top:1px solid var(--line);background:#fff}
.art .shot{display:block;width:100%;height:auto;border-top:1px solid var(--line)}
.tablewrap{overflow-x:auto;-webkit-overflow-scrolling:touch}
.tablewrap:focus-visible{outline:2px solid var(--h);outline-offset:2px}
.headline th[scope=row],.headline thead th:first-child{position:sticky;left:0;background:var(--bg);z-index:1}
.tscroll{display:none;color:var(--mut);font-size:.8rem;margin:0 0 8px}
.flag{color:var(--k)}
@media(max-width:640px){td.num,th{white-space:normal}th,td{padding:4px 5px}.prov{font-size:.64rem}thead th{font-size:.72rem;letter-spacing:0}.art iframe{height:300px}}
@media(max-width:420px){.tscroll{display:block}}
"""


def run_stamp(repo: Path) -> str:
    """The newest timestamp the run itself recorded, so a rebuild does not change the page."""
    stamps = []
    for env in sorted(repo.glob("runs/*/env.txt")):
        for line in env.read_text(errors="replace").splitlines():
            if line.startswith("timestamp "):
                stamps.append(line.split(" ", 1)[1].strip())
    return max(stamps)[:10] if stamps else "unknown"


def render_html(summary: dict, artifacts: list[dict], findings: str, stamp: str) -> str:
    m = summary["measurements"]
    digest = {e["engine"]: e["digest"] for e in m if e.get("digest")}
    counts = summary["counts"]
    machine = "AZW GTR Pro (Beelink GTR9 Pro), Ryzen AI Max+ 395, 128 GB unified, gfx1151"
    note = not_run_note(m)
    csv_link = ('<li><a href="../results/measurements.csv">results/measurements.csv</a> '
                '&mdash; every row above, flattened</li>'
                if (LINK_ROOT / "results" / "measurements.csv").is_file() else "")
    note_html = f'<p class="sub"><strong>Not run.</strong> {escape(note)}</p>' if note else ""
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Halogen vs Kyojin — Qwen3.8-Flash-Next on one Strix Halo</title>
<style>{CSS}</style></head>
<body><main>
<h1>Halogen vs Kyojin, same model, one machine</h1>
<p class="sub">{escape(machine)} &middot; measured one engine at a time &middot; {stamp}<br>
Halogen <code>{escape(digest_short(digest.get("halogen")))}</code> &middot;
Kyojin <code>{escape(digest_short(digest.get("kyojin")))}</code> &middot;
{counts["measured"]} measured, {counts["not_run"]} not run, {counts["aborted"]} aborted</p>

{abort_band(m)}
{cell_table(m)}
<p class="sub">Tok/s for prefill and decode; seconds for time to first token and startup.
How often each value was measured is in Repetitions.</p>
{note_html}
{spread_table(m)}
{variance_table(summary)}

<h2>What this is not</h2>
<div class="scope"><ul>{"".join(f"<li>{inline(x)}</li>" for x in SCOPE)}</ul></div>

<h2>Charts</h2>
{build_charts(m)}

<h2>{escape(FINDINGS_HEADING)}</h2>
{md_to_html(strip_title(findings)) if findings.strip() else '<p class="muted">Not written yet.</p>'}

<h2>Artifacts</h2>
<p class="sub">Each engine's single-shot answer to the same prompt, one HTML file, no tools, no retry.
The maintainer's gallery rows were produced by an agent harness this run does not have, so these pages are not
comparable to the gallery's timings; they are here so you can click them.</p>
{artifact_section(artifacts)}

<h2>Raw data</h2>
<p class="sub">Every number above traces to one of these files. The report page is derived; the raw records are
the artifact of record.</p>
<ul>{csv_link}{"".join(f'<li><a href="{escape(rel(p))}">{escape(p)}</a></li>'
             for p in sorted({e["raw_path"] for e in m if e["raw_path"]}
                             | {v.get("raw_path") for v in summary.get("variance") or [] if v.get("raw_path")})
             if p and (LINK_ROOT / p).is_file())}</ul>

<p class="sub">Method, abort rules and the two ADRs that explain why there is one arm:
<a href="../README.md">README</a> &middot; <a href="../docs/adr/0001-single-arm-halogen-as-yardstick.md">ADR-0001</a>,
<a href="../docs/adr/0002-two-kyojin-runs.md">ADR-0002</a>,
<a href="../docs/adr/0003-private-work-public-export.md">ADR-0003</a>,
<a href="../docs/adr/0004-usability-checks-not-a-quality-score.md">ADR-0004</a>.</p>
</main></body></html>
"""


def render_issue(summary: dict, artifacts: list[dict], findings: str, repo_url: str) -> str:
    m = summary["measurements"]
    digest = {e["engine"]: e["digest"] for e in m if e.get("digest")}
    note = not_run_note(m)
    lines = [
        "## What this is",
        "",
        "One machine, one model, two engines, measured one at a time. Kyojin was raised from the container's "
        "defaults to the configuration Halogen actually runs (full context, vision on, the same reply budget), "
        "so these numbers describe Kyojin as a daily driver, not at stock settings.",
        "",
        f"- Halogen: `{digest.get('halogen') or 'unknown'}`",
        f"- Kyojin: `{digest.get('kyojin') or 'unknown'}`",
        "- Machine: AZW GTR Pro (the firmware's DMI strings; sold as Beelink GTR9 Pro), "
        "Ryzen AI Max+ 395, 128 GB unified (gfx1151), Fedora 44, kernel 7.2.9.",
        "",
        "No action is requested here: this is a benchmark report, not a support request.",
        "",
        "## Numbers",
        "",
        markdown_table(m),
        "",
    ]
    if note:
        lines += [f"_{note}_", ""]
    lines += spread_markdown(m)
    lines += variance_markdown(summary)
    for a in artifacts:
        lines.append(f'- {a["engine"].title()}, {a["task"]}: {repo_url}/blob/main/docs/{a["path"]} '
                     f'(`sha256:{a["sha256"][:12]}`)')
    lines += ["", f"## {FINDINGS_HEADING}", "", strip_title(findings).strip() or "_not written yet_", "",
              "## Everything else", "",
              f"Method, raw JSON, logs, the exact compose files and the artifact pages: {repo_url}",
              "", "_The two packs are different quantizations of the same model, so speed figures describe "
              "engine and quantization together. The output checks decide usability, not quality._"]
    return "\n".join(lines)


# ---------------------------------------------------------------- guards

VALID_STATUS = {"measured", "not_run", "aborted"}


def validate(summary: dict) -> None:
    """Refuse to render a summary that is not the schema this code understands.

    Rendering around a hole is how a report ends up quietly missing a result, which the
    spec names as the failure worth guarding against.
    """
    problems: list[str] = []
    if not isinstance(summary, dict) or "measurements" not in summary:
        raise SystemExit("summary: no 'measurements' list")
    if summary.get("schema") not in (1, 2):
        problems.append(f"summary: unsupported schema {summary.get('schema')!r}")
    if not summary["measurements"]:
        problems.append("summary: no measurements at all")
    required = ("metric", "unit", "engine", "condition", "value", "status", "digest")
    for i, e in enumerate(summary["measurements"]):
        where = f"measurement[{i}] {e.get('metric')!r}/{e.get('condition')!r}"
        missing = [k for k in required if k not in e]
        if missing:
            problems.append(f"{where}: missing field(s) {missing}")
            continue
        metric = e["metric"]
        if metric not in METRICS:
            problems.append(f"{where}: unknown metric")
            continue
        if e["unit"] != METRICS[metric]:
            problems.append(f"{where}: unit {e['unit']!r} is not {METRICS[metric]!r} for that metric")
        if e["engine"] not in ENGINES:
            problems.append(f"{where}: engine {e['engine']!r}")
        if e["status"] not in VALID_STATUS:
            problems.append(f"{where}: status {e['status']!r}")
            continue
        if not str(e["condition"]).strip():
            problems.append(f"{where}: empty condition")
        if e["status"] != "measured":
            continue
        if not e["digest"]:
            problems.append(f"{where}: measured but carries no image digest")
        value = e["value"]
        if METRICS[metric] == "bool":
            if not isinstance(value, bool):
                problems.append(f"{where}: boolean metric with value {value!r}")
        elif METRICS[metric] == "ratio":
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not 0 <= value <= 1:
                problems.append(f"{where}: ratio metric with value {value!r}")
        elif isinstance(value, bool) or not isinstance(value, (int, float)):
            problems.append(f"{where}: numeric metric with value {value!r}")
        else:
            if not math.isfinite(float(value)):
                problems.append(f"{where}: value is not finite ({value!r})")
            elif float(value) < 0:
                problems.append(f"{where}: negative value ({value!r})")
    variance_keys = ("engine", "phase", "metric", "condition", "unit", "n",
                     "median", "min", "max")
    for i, v in enumerate(summary.get("variance") or []):
        where = f"variance[{i}] {v.get('metric')!r}/{v.get('condition')!r}"
        if not isinstance(v, dict):
            problems.append(f"variance[{i}]: not an object")
            continue
        missing = [k for k in variance_keys if k not in v]
        if missing:
            problems.append(f"{where}: missing field(s) {missing}")
            continue
        if v["metric"] not in METRICS or v["unit"] != METRICS[v["metric"]]:
            problems.append(f"{where}: metric/unit {v['metric']!r}/{v['unit']!r}")
            continue
        if v["engine"] not in ENGINES:
            problems.append(f"{where}: engine {v['engine']!r}")
        if not str(v["condition"]).strip():
            problems.append(f"{where}: empty condition")
        if isinstance(v["n"], bool) or not isinstance(v["n"], int) or v["n"] < 2:
            problems.append(f"{where}: n={v['n']!r}, need at least two repetitions")
        nums = [v["median"], v["min"], v["max"]]
        if any(isinstance(x, bool) or not isinstance(x, (int, float)) or not math.isfinite(float(x))
               for x in nums):
            problems.append(f"{where}: non-finite statistic {nums!r}")
        elif not (v["min"] <= v["median"] <= v["max"]):
            problems.append(f"{where}: min/median/max out of order {nums!r}")
    counts = summary.get("counts") or {}
    for key in ("total", "measured", "not_run", "aborted"):
        wanted = (len(summary["measurements"]) if key == "total"
                  else sum(1 for e in summary["measurements"] if e.get("status") == key))
        if counts.get(key) != wanted:
            problems.append(f"summary: counts.{key} is {counts.get(key)}, list says {wanted}")
    if problems:
        print("refusing to render, the summary does not validate:", file=sys.stderr)
        for line in problems[:12]:
            print("  " + line, file=sys.stderr)
        raise SystemExit(1)


def assert_clean(text: str, where: str, allow: tuple[str, ...] = ()) -> None:
    problems = privacy.scan(where, text, allow=allow)
    if problems:
        print(f"refusing to publish {where}:", file=sys.stderr)
        for line in problems[:10]:
            print("  " + line, file=sys.stderr)
        raise SystemExit(1)


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--summary", default="results/summary.json")
    p.add_argument("--repo", default=".")
    p.add_argument("--out", default="docs")
    p.add_argument("--issue", default="results/issue-body.md")
    p.add_argument("--repo-url", default=privacy.PUBLIC_REPO_URL)
    a = p.parse_args()
    global LINK_ROOT
    repo = Path(a.repo).resolve()
    LINK_ROOT = repo
    summary = json.loads(Path(a.summary).read_text())
    validate(summary)
    findings_path = repo / "results" / "findings.md"
    findings = findings_path.read_text() if findings_path.is_file() else ""
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)

    artifacts = copy_artifacts(repo, out)
    html = render_html(summary, artifacts, findings, run_stamp(repo))
    issue = render_issue(summary, artifacts, findings, a.repo_url)
    assert_clean(html, "docs/index.html", allow=(a.repo_url,))
    assert_clean(issue, a.issue, allow=(a.repo_url,))

    (out / "index.html").write_text(html)
    Path(a.issue).parent.mkdir(parents=True, exist_ok=True)
    Path(a.issue).write_text(issue + "\n")
    print(f"{out / 'index.html'}: {len(html):,} bytes, {len(artifacts)} artifact page(s)")
    print(f"{a.issue}: {len(issue):,} bytes")


if __name__ == "__main__":
    main()
