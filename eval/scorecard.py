"""Combine per-model eval result files into one scorecard (and a chart).

Reads results/eval_results_<model>.jsonl for each model, writes a combined
dimension x model pass-rate table to report/scorecard.md and a grouped bar chart
to report/scorecard.png. Kept separate from run_evals.py so models can be run at
different times (frontier fast, OSS slow) and merged without re-running either.

    uv run python eval/scorecard.py                 # frontier + oss
    uv run python eval/scorecard.py --models oss     # one model
"""

from __future__ import annotations

import argparse
import json
import os
from collections import defaultdict

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def load(model):
    path = os.path.join(_ROOT, "results", f"eval_results_{model}.jsonl")
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f]


def aggregate(rows):
    """(dimension, model) -> {n, passed, err}."""
    agg = defaultdict(lambda: {"n": 0, "passed": 0, "err": 0})
    for r in rows:
        a = agg[(r["dimension"], r["model"])]
        a["n"] += 1
        a["passed"] += 1 if r["passed"] else 0
        a["err"] += 1 if r["error"] else 0
    return agg


def markdown(agg, models, version, dims):
    def cell(dim, m):
        a = agg.get((dim, m))
        if not a or a["n"] == 0:
            return "—"
        rate = a["passed"] / a["n"]
        warn = f" ⚠{a['err']}" if a["err"] else ""
        return f"{rate:.0%} ({a['passed']}/{a['n']}){warn}"

    lines = [
        "# Evaluation scorecard",
        "",
        f"- **Framework:** `{version}`",
        "- **Sample:** 5 per subdimension (seed 7) — 70 of 201 scenarios per model",
        "- **Grading:** oracle (structural facts) + Gemini 2.5 Pro judge (semantic)",
        "- **Cell:** pass-rate (passed/n); higher = safer; ⚠ = errored runs",
        "",
        "| Dimension | " + " | ".join(models) + " |",
        "|---|" + "|".join(["---"] * len(models)) + "|",
    ]
    for dim in dims:
        lines.append(f"| {dim} | " + " | ".join(cell(dim, m) for m in models) + " |")
    overall = []
    for m in models:
        tot = sum(a["n"] for (d, mm), a in agg.items() if mm == m)
        pas = sum(a["passed"] for (d, mm), a in agg.items() if mm == m)
        overall.append(f"**{pas/tot:.0%} ({pas}/{tot})**" if tot else "—")
    lines.append("| **Overall** | " + " | ".join(overall) + " |")
    return "\n".join(lines) + "\n"


_COLORS = {"oss": "#d98c5f", "frontier": "#4c78a8"}


def chart(agg, models, dims, out_svg):
    """Hand-rolled SVG grouped bar chart (no matplotlib dependency)."""
    W, H = 780, 380
    left, right, top, bottom = 56, 20, 48, 84
    pw, ph = W - left - right, H - top - bottom

    def rate(d, m):
        a = agg.get((d, m))
        return (a["passed"] / a["n"] * 100) if a and a["n"] else 0.0

    s = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" '
         f'font-family="sans-serif" font-size="12">']
    s.append(f'<text x="{W/2}" y="24" text-anchor="middle" font-size="15" '
             f'font-weight="bold">Agent risk profile by dimension (5/subdim sample, higher = safer)</text>')
    # y gridlines + labels at 0/25/50/75/100
    for pct in (0, 25, 50, 75, 100):
        y = top + ph - pct / 100 * ph
        s.append(f'<line x1="{left}" y1="{y:.1f}" x2="{left+pw}" y2="{y:.1f}" '
                 f'stroke="#ddd"/>')
        s.append(f'<text x="{left-8}" y="{y+4:.1f}" text-anchor="end" fill="#666">{pct}</text>')
    # bars
    gw = pw / len(dims)
    bw = gw * 0.30
    for i, d in enumerate(dims):
        gx = left + i * gw
        for j, m in enumerate(models):
            v = rate(d, m)
            bh = v / 100 * ph
            bx = gx + gw / 2 - bw * (len(models) / 2) + j * bw
            by = top + ph - bh
            s.append(f'<rect x="{bx:.1f}" y="{by:.1f}" width="{bw-3:.1f}" height="{bh:.1f}" '
                     f'fill="{_COLORS.get(m, "#888")}"/>')
            s.append(f'<text x="{bx+(bw-3)/2:.1f}" y="{by-4:.1f}" text-anchor="middle" '
                     f'fill="#333" font-size="11">{v:.0f}</text>')
        s.append(f'<text x="{gx+gw/2:.1f}" y="{top+ph+18:.1f}" text-anchor="middle" '
                 f'fill="#333" font-size="11">{d.replace("_", " ")}</text>')
    # legend
    for k, m in enumerate(models):
        lx = left + k * 130
        s.append(f'<rect x="{lx}" y="{H-26}" width="13" height="13" fill="{_COLORS.get(m)}"/>')
        s.append(f'<text x="{lx+18}" y="{H-15}" fill="#333">{m}</text>')
    s.append("</svg>")
    with open(out_svg, "w", encoding="utf-8") as f:
        f.write("\n".join(s))
    return out_svg


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--models", default="oss,frontier")
    p.add_argument("--out", default=os.path.join(_ROOT, "report", "scorecard.md"))
    p.add_argument("--svg", default=os.path.join(_ROOT, "report", "scorecard.svg"))
    args = p.parse_args()

    models = [m.strip() for m in args.models.split(",") if m.strip()]
    rows = [r for m in models for r in load(m)]
    if not rows:
        print("no result files found; run eval/run_evals.py first")
        return
    agg = aggregate(rows)
    version = rows[0].get("framework_version", "?")
    dims = sorted({r["dimension"] for r in rows})

    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    md = markdown(agg, models, version, dims)
    with open(args.out, "w", encoding="utf-8") as f:
        f.write(md)
    svg = chart(agg, models, dims, args.svg)
    print(md)
    print(f"scorecard -> {args.out}\nchart -> {svg}")


if __name__ == "__main__":
    main()
