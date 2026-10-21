#!/usr/bin/env python3
"""Inline SVG charts emitted from the summary, with no plotting dependency.

Every chart carries its numbers as text as well as geometry, so nothing is only in the
picture: with images disabled, or in the Markdown issue, the values are still readable.
A point that was not measured renders as a gap with a label, never as an interpolated
line through it.
"""
from __future__ import annotations

from html import escape

PALETTE = {"halogen": "#4f9dff", "kyojin": "#f0a03c"}
ENGINE_LABEL = {"halogen": "Halogen", "kyojin": "Kyojin"}


def _ticks(vmin: float, vmax: float, n: int = 4) -> list[float]:
    if vmax == vmin:
        return [vmin]
    step = (vmax - vmin) / n
    return [vmin + step * i for i in range(n + 1)]


def _fmt(v: float) -> str:
    if abs(v) >= 100:
        return f"{v:.0f}"
    if abs(v) >= 10:
        return f"{v:.1f}"
    return f"{v:.2f}".rstrip("0").rstrip(".")


def line_chart(series: dict[str, list[tuple[float, float | None]]], *,
               x_label: str, y_label: str, width: int = 720, height: int = 300,
               title: str = "") -> str:
    """series: engine -> [(x, y or None)]. A None y is an unmeasured point."""
    pad_l, pad_r, pad_t, pad_b = 62, 18, 26, 46
    xs = [x for pts in series.values() for x, _ in pts]
    ys = [y for pts in series.values() for _, y in pts if y is not None]
    if not xs or not ys:
        return f'<p class="muted">no data for {escape(title or y_label)}</p>'
    xmin, xmax = min(xs), max(xs)
    ymin = 0
    ymax = max(ys) * 1.12
    x = lambda v: pad_l + (v - xmin) / max(1e-9, xmax - xmin) * (width - pad_l - pad_r)
    y = lambda v: pad_t + (1 - (v - ymin) / max(1e-9, ymax - ymin)) * (height - pad_t - pad_b)

    parts = [f'<svg viewBox="0 0 {width} {height}" role="img" aria-label="{escape(title)}" '
             f'class="chart" xmlns="http://www.w3.org/2000/svg">']
    parts.append(f'<text x="{pad_l}" y="16" class="ct">{escape(title)}</text>')
    for t in _ticks(ymin, ymax):
        parts.append(f'<line x1="{pad_l}" y1="{y(t):.1f}" x2="{width - pad_r}" y2="{y(t):.1f}" class="grid"/>')
        parts.append(f'<text x="{pad_l - 8}" y="{y(t) + 4:.1f}" class="ax" text-anchor="end">{_fmt(t)}</text>')
    for t in _ticks(xmin, xmax, 3):
        parts.append(f'<text x="{x(t):.1f}" y="{height - pad_b + 18}" class="ax" text-anchor="middle">{_fmt(t)}</text>')
    parts.append(f'<text x="{(pad_l + width - pad_r) / 2:.0f}" y="{height - 8}" class="ax" '
                 f'text-anchor="middle">{escape(x_label)}</text>')
    parts.append(f'<text x="14" y="{pad_t + 4}" class="ax" transform="rotate(-90 14 {pad_t + 4})" '
                 f'text-anchor="end">{escape(y_label)}</text>')

    for i, (engine, pts) in enumerate(sorted(series.items())):
        colour = PALETTE.get(engine, "#999")
        # one path per contiguous run of measured points: a gap is never interpolated over
        segments: list[list[tuple[float, float]]] = []
        run: list[tuple[float, float]] = []
        for px, py in pts:
            if py is None:
                if run:
                    segments.append(run)
                    run = []
            else:
                run.append((px, py))
        if run:
            segments.append(run)
        for seg in segments:
            d = " ".join(("M" if j == 0 else "L") + f"{x(px):.1f},{y(py):.1f}"
                         for j, (px, py) in enumerate(seg))
            parts.append(f'<path d="{d}" fill="none" stroke="{colour}" stroke-width="2"/>')
        for px, py in pts:
            if py is None:
                parts.append(f'<text x="{x(px):.1f}" y="{height - pad_b - 6}" class="miss" '
                             f'text-anchor="middle">not run</text>')
            else:
                parts.append(f'<circle cx="{x(px):.1f}" cy="{y(py):.1f}" r="3.5" fill="{colour}"/>')
                parts.append(f'<text x="{x(px):.1f}" y="{y(py) - 9:.1f}" class="val" text-anchor="middle">'
                             f'{_fmt(py)}</text>')
        parts.append(f'<rect x="{pad_l + i * 130}" y="{height - pad_b + 26}" width="10" height="10" fill="{colour}"/>')
        parts.append(f'<text x="{pad_l + i * 130 + 15}" y="{height - pad_b + 35}" class="ax">'
                     f'{escape(ENGINE_LABEL.get(engine, engine))}</text>')
    parts.append("</svg>")
    return "".join(parts)


def bar_chart(groups: list[dict], *, y_label: str, width: int = 720, height: int = 280,
              title: str = "") -> str:
    """groups: [{"label": str, "values": {engine: (value or None)}}]"""
    pad_l, pad_r, pad_t, pad_b = 62, 18, 26, 58
    vals = [v for g in groups for v in g["values"].values() if v is not None]
    if not groups or not vals:
        return f'<p class="muted">no data for {escape(title or y_label)}</p>'
    ymax = max(vals) * 1.18
    engines = sorted({e for g in groups for e in g["values"]})
    y = lambda v: pad_t + (1 - v / max(1e-9, ymax)) * (height - pad_t - pad_b)
    slot = (width - pad_l - pad_r) / max(1, len(groups))
    bar_w = min(26, slot / (len(engines) + 1))

    parts = [f'<svg viewBox="0 0 {width} {height}" role="img" aria-label="{escape(title)}" '
             f'class="chart" xmlns="http://www.w3.org/2000/svg">']
    parts.append(f'<text x="{pad_l}" y="16" class="ct">{escape(title)}</text>')
    for t in _ticks(0, ymax):
        parts.append(f'<line x1="{pad_l}" y1="{y(t):.1f}" x2="{width - pad_r}" y2="{y(t):.1f}" class="grid"/>')
        parts.append(f'<text x="{pad_l - 8}" y="{y(t) + 4:.1f}" class="ax" text-anchor="end">{_fmt(t)}</text>')
    for gi, g in enumerate(groups):
        cx = pad_l + slot * gi + slot / 2
        parts.append(f'<text x="{cx:.1f}" y="{height - pad_b + 16}" class="ax" text-anchor="middle">'
                     f'{escape(g["label"])}</text>')
        for ei, engine in enumerate(engines):
            v = g["values"].get(engine)
            bx = cx - (len(engines) * bar_w) / 2 + ei * bar_w
            if v is None:
                parts.append(f'<text x="{bx + bar_w / 2:.1f}" y="{height - pad_b - 6}" class="miss" '
                             f'text-anchor="middle">n/a</text>')
                continue
            parts.append(f'<rect x="{bx:.1f}" y="{y(v):.1f}" width="{bar_w - 3:.1f}" '
                         f'height="{max(1, height - pad_b - y(v)):.1f}" fill="{PALETTE.get(engine, "#999")}"/>')
            parts.append(f'<text x="{bx + (bar_w - 3) / 2:.1f}" y="{y(v) - 6:.1f}" class="val" '
                         f'text-anchor="middle">{_fmt(v)}</text>')
    for i, engine in enumerate(engines):
        parts.append(f'<rect x="{pad_l + i * 130}" y="{height - 20}" width="10" height="10" '
                     f'fill="{PALETTE.get(engine, "#999")}"/>')
        parts.append(f'<text x="{pad_l + i * 130 + 15}" y="{height - 11}" class="ax">'
                     f'{escape(ENGINE_LABEL.get(engine, engine))}</text>')
    parts.append("</svg>")
    return "".join(parts)
