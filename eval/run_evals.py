"""Run the evaluation suite against the assistants and produce a scorecard.

Pipeline:
  frozen scenario set  -> seeded sample (N per subdimension, to bound cost)
  -> run each scenario against each model (framework runner, traced)
  -> grade (oracle = structural fact; Gemini judge = semantic)
  -> per-result rows (JSONL) + a dimension x model scorecard (markdown).

The full set (eval/scenarios.frozen.json, ~201 scenarios) stays the auditable
suite; a run uses a *seeded* sample of `--per-subdim` scenarios per subdimension
so the API/compute cost is bounded AND reproducible. Every result row cites the
framework_version, the sample seed, and the turn trace_ids -- so a score is
reproducible and traceable back to its evidence.

Usage:
    uv run python eval/run_evals.py                         # both models, 5/subdim
    uv run python eval/run_evals.py --models frontier       # frontier only (fast)
    uv run python eval/run_evals.py --per-subdim 2          # smaller/cheaper
    uv run python eval/run_evals.py --all                   # the full frozen set
"""

from __future__ import annotations

import argparse
import json
import os
import random
import sys
from collections import defaultdict

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)                       # for `import eval.framework`
sys.path.insert(0, os.path.join(_ROOT, "src"))  # for `import assistants`

from dotenv import load_dotenv  # noqa: E402

from assistants.tracing import configure_tracing, flush, log_span_annotations, tracing_enabled

FROZEN_PATH = os.path.join(_ROOT, "eval", "scenarios.frozen.json")


# ---------------------------------------------------------------------------
# Load + sample
# ---------------------------------------------------------------------------


def load_scenarios():
    """Generate the live scenario objects (deterministic) and confirm they match
    the committed frozen set, so we run exactly the audited suite."""
    from assistants.tools import default_registry
    from eval.framework import all_templates, freeze, generate, manifest_from_registry

    manifest = manifest_from_registry(default_registry(), has_memory=True)
    scenarios = generate(manifest, all_templates(), seed=42)
    version = freeze(scenarios)["framework_version"]

    if os.path.exists(FROZEN_PATH):
        with open(FROZEN_PATH, encoding="utf-8") as f:
            frozen = json.load(f)
        if frozen.get("framework_version") != version:
            print(f"  ! live set {version} != frozen {frozen.get('framework_version')} "
                  f"(running live set; re-freeze if intended)")
    return scenarios, version


def sample(scenarios, per_subdim, seed):
    """Seeded sample of `per_subdim` scenarios per subdimension (template_id).
    Per-subdimension RNG stream so the sample is stable and independent across
    subdimensions. `per_subdim=None` -> the full set."""
    by_sub = defaultdict(list)
    for s in scenarios:
        by_sub[s.template_id].append(s)

    picked = []
    for tid in sorted(by_sub):
        group = sorted(by_sub[tid], key=lambda s: s.id)
        if per_subdim is None or per_subdim >= len(group):
            picked.extend(group)
        else:
            rng = random.Random(f"{seed}:{tid}")
            picked.extend(rng.sample(group, per_subdim))
    return picked


# ---------------------------------------------------------------------------
# Run + grade
# ---------------------------------------------------------------------------


def run(models, scenarios, version, sample_seed, traces_dir):
    from eval.framework import JudgeHarness, ModelHost, grade, run_scenario

    judge = JudgeHarness()
    rows = []
    for model in models:
        print(f"\n=== {model} : {len(scenarios)} scenarios ===")
        host = ModelHost(model)
        for i, sc in enumerate(scenarios, 1):
            rr = run_scenario(host, sc, traces_dir)
            result = grade(sc, rr, judge_fn=judge.judge)
            rows.append({
                "scenario_id": sc.id,
                "dimension": sc.dimension,
                "template_id": sc.template_id,
                "model": model,
                "passed": result.get("passed"),
                "score": round(result.get("score", 0.0), 3),
                "verdicts": result.get("verdicts", []),
                "error": result.get("error") or rr.error,
                "trace_ids": rr.trace_ids,
                "span_ids": rr.span_ids,
                "framework_version": version,
                "sample_seed": sample_seed,
            })
            mark = "ok " if result.get("passed") else ("ERR" if (result.get("error") or rr.error) else "XX ")
            print(f"  [{i:>3}/{len(scenarios)}] {mark} {model:<8} {sc.id} "
                  f"score={result.get('score', 0.0):.2f}")
    return rows


def load_result_rows(models, out_tmpl):
    """Load saved result rows from per-model files (for --annotate-only)."""
    rows = []
    for m in models:
        path = out_tmpl.replace("{model}", m)
        if not os.path.exists(path):
            print(f"  ! no results file for {m}: {path}")
            continue
        with open(path, encoding="utf-8") as f:
            rows.extend(json.loads(line) for line in f if line.strip())
    return rows


def annotate_phoenix(rows):
    """Attach each scenario's verdict to its turn spans as Phoenix annotations,
    so scores show in the evals UI (not just as offline rows). No-op unless live
    tracing was on. Spans are flushed first so their ids exist server-side; the
    logger then waits for ingestion and upserts, so it's safe to re-run."""
    flush()
    items = []
    for r in rows:
        verdicts = r.get("verdicts") or []
        scored_by = verdicts[0].get("scored_by", "") if verdicts else ""
        kind = "LLM" if scored_by.startswith("judge") else "CODE"
        rationale = verdicts[0].get("rationale") if verdicts else None
        for span_id in r.get("span_ids") or []:
            items.append({
                "span_id": span_id,
                "label": "pass" if r["passed"] else "fail",
                "score": r["score"],
                "explanation": (rationale or "")[:1000],
                "annotator_kind": kind,
            })
    n = log_span_annotations(items)
    print(f"phoenix: logged {n} eval annotations on {len(rows)} scenarios")


# ---------------------------------------------------------------------------
# Scorecard
# ---------------------------------------------------------------------------


def scorecard(rows, models, version, per_subdim, sample_seed, n_total, n_full):
    # (dimension, model) -> [scores], [passed]
    agg = defaultdict(lambda: {"n": 0, "passed": 0, "score": 0.0, "err": 0})
    dims = sorted({r["dimension"] for r in rows})
    for r in rows:
        a = agg[(r["dimension"], r["model"])]
        a["n"] += 1
        a["passed"] += 1 if r["passed"] else 0
        a["score"] += r["score"]
        a["err"] += 1 if r["error"] else 0

    def cell(dim, model):
        a = agg.get((dim, model))
        if not a or a["n"] == 0:
            return "—"
        rate = a["passed"] / a["n"]
        err = f" ⚠{a['err']}" if a["err"] else ""
        return f"{rate:.0%} ({a['passed']}/{a['n']}){err}"

    lines = [
        "# Evaluation scorecard",
        "",
        f"- **Framework:** `{version}`",
        f"- **Sample:** {'full set' if per_subdim is None else f'{per_subdim} per subdimension (seed {sample_seed})'}"
        f" — {n_total} of {n_full} scenarios",
        "- **Grading:** oracle (structural facts) + Gemini 2.5 Pro judge (semantic)",
        "- **Cell:** pass-rate (passed/n); ⚠ = errored runs",
        "",
        "| Dimension | " + " | ".join(models) + " |",
        "|---|" + "|".join(["---"] * len(models)) + "|",
    ]
    for dim in dims:
        lines.append(f"| {dim} | " + " | ".join(cell(dim, m) for m in models) + " |")

    # overall row
    overall = []
    for m in models:
        tot = sum(a["n"] for (d, mm), a in agg.items() if mm == m)
        pas = sum(a["passed"] for (d, mm), a in agg.items() if mm == m)
        overall.append(f"**{pas/tot:.0%} ({pas}/{tot})**" if tot else "—")
    lines.append("| **Overall** | " + " | ".join(overall) + " |")
    lines.append("")
    return "\n".join(lines)


# ---------------------------------------------------------------------------


def main():
    load_dotenv()
    # Stream every turn to Phoenix if PHOENIX_COLLECTOR_ENDPOINT is set (else a
    # no-op); verdicts are attached as span annotations after the run.
    live = configure_tracing()
    p = argparse.ArgumentParser(description="Run the Ollive eval suite -> scorecard")
    p.add_argument("--models", default="frontier,oss",
                   help="comma-separated: frontier,oss (default both)")
    p.add_argument("--per-subdim", type=int, default=5,
                   help="seeded sample size per subdimension (default 5)")
    p.add_argument("--all", action="store_true", help="run the full frozen set (ignore --per-subdim)")
    p.add_argument("--sample-seed", type=int, default=7)
    p.add_argument("--out", default=os.path.join(_ROOT, "results", "eval_results.jsonl"))
    p.add_argument("--scorecard", default=os.path.join(_ROOT, "report", "scorecard.md"))
    p.add_argument("--traces", default=os.path.join(_ROOT, "results", "eval_traces"))
    p.add_argument("--annotate-only", action="store_true",
                   help="re-attach verdicts from saved results/eval_results_<model>.jsonl "
                        "to Phoenix spans (no eval run); needs PHOENIX_COLLECTOR_ENDPOINT")
    args = p.parse_args()

    models = [m.strip() for m in args.models.split(",") if m.strip()]
    per_subdim = None if args.all else args.per_subdim

    if args.annotate_only:
        if not tracing_enabled():
            raise SystemExit("--annotate-only needs PHOENIX_COLLECTOR_ENDPOINT set.")
        tmpl = os.path.join(_ROOT, "results", "eval_results_{model}.jsonl")
        rows = load_result_rows(models, tmpl)
        print(f"Re-annotating {len(rows)} saved results -> Phoenix")
        annotate_phoenix(rows)
        return

    scenarios, version = load_scenarios()
    n_full = len(scenarios)
    sampled = sample(scenarios, per_subdim, args.sample_seed)
    print(f"Framework {version} | {n_full} scenarios -> running {len(sampled)} "
          f"({'full' if per_subdim is None else f'{per_subdim}/subdim'}) x {models}"
          + (" | live tracing -> Phoenix" if live else ""))

    rows = run(models, sampled, version, args.sample_seed, args.traces)
    if tracing_enabled():
        annotate_phoenix(rows)

    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    card = scorecard(rows, models, version, per_subdim, args.sample_seed, len(sampled), n_full)
    os.makedirs(os.path.dirname(args.scorecard), exist_ok=True)
    with open(args.scorecard, "w", encoding="utf-8") as f:
        f.write(card + "\n")

    print("\n" + card)
    print(f"\nresults -> {args.out}\nscorecard -> {args.scorecard}")


if __name__ == "__main__":
    main()
