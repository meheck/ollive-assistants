"""Cost + latency benchmark for the open-source deployment.

Measures the OSS assistant (Qwen2.5-1.5B-Instruct by default) two ways:
  1. Local in-process (transformers on CPU): cold-load time, warm per-turn
     latency, and generation throughput (tokens/sec).
  2. The live Hugging Face Space (end-to-end round-trip incl. network/queue).

Emits raw measurements to results/latency_raw.json and a human-readable table
to report/cost_latency.md. Cost is reported from the deployment tier (free CPU
= $0) with paid-tier references for context.

Usage:
    uv run python eval/bench_latency.py                 # local only
    uv run python eval/bench_latency.py --space meheck/ollive-oss-assistant
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from pathlib import Path

from gradio_client import Client

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from assistants.oss import OSSAssistant  # noqa: E402

# A fixed, representative prompt set. Short answers + a couple that force longer
# generation, so the table reflects both latency floor and throughput.
PROMPTS = [
    "What is the capital of France?",
    "What is 17 times 23?",
    "Give me three tips for writing clean code.",
    "Explain how TCP differs from UDP in two sentences.",
    "Write a short haiku about the ocean.",
]
RUNS_PER_PROMPT = 3


def _median(xs: list[float]) -> float:
    return round(statistics.median(xs), 3)


def bench_local() -> dict:
    """Cold load + warm latency + tokens/sec for the in-process model (CPU)."""
    assistant = OSSAssistant(temperature=0.0)  # greedy -> stable, reproducible

    # Cold load: time the first generation, which triggers weight loading.
    t0 = time.perf_counter()
    assistant.chat(PROMPTS[0])
    cold_load_s = round(time.perf_counter() - t0, 3)

    tok = assistant._tokenizer  # already loaded after first call
    latencies: list[float] = []
    throughputs: list[float] = []
    for prompt in PROMPTS:
        for _ in range(RUNS_PER_PROMPT):
            assistant.reset()
            t = time.perf_counter()
            reply = assistant.chat(prompt)
            dt = time.perf_counter() - t
            n_out = len(tok(reply)["input_ids"])
            latencies.append(dt)
            if dt > 0:
                throughputs.append(n_out / dt)

    return {
        "device": assistant.device,
        "model": assistant.model_name,
        "cold_load_s": cold_load_s,
        "warm_latency_s_median": _median(latencies),
        "warm_latency_s_min": round(min(latencies), 3),
        "warm_latency_s_max": round(max(latencies), 3),
        "throughput_tok_per_s_median": _median(throughputs),
        "n_measurements": len(latencies),
    }


def bench_space(space_id: str) -> dict:
    """End-to-end round-trip latency against the live HF Space."""
    client = Client(space_id, verbose=False)
    latencies: list[float] = []
    for prompt in PROMPTS:
        for _ in range(RUNS_PER_PROMPT):
            t = time.perf_counter()
            client.predict(message=prompt, api_name="/_respond")
            latencies.append(time.perf_counter() - t)

    return {
        "space_id": space_id,
        "url": f"https://{space_id.replace('/', '-')}.hf.space/",
        "roundtrip_latency_s_median": _median(latencies),
        "roundtrip_latency_s_min": round(min(latencies), 3),
        "roundtrip_latency_s_max": round(max(latencies), 3),
        "n_measurements": len(latencies),
    }


def render_markdown(local: dict, space: dict | None) -> str:
    lines = [
        "# OSS Deployment — Cost & Latency",
        "",
        f"Model: **{local['model']}**  ·  Prompt set: {len(PROMPTS)} prompts × "
        f"{RUNS_PER_PROMPT} runs (greedy decoding).",
        "",
        "## Latency & throughput",
        "",
        "| Metric | Local (CPU, in-process) | HF Space (free CPU, end-to-end) |",
        "|---|---|---|",
    ]
    sp = lambda k: (space[k] if space else "—")  # noqa: E731
    lines += [
        f"| Cold model load | {local['cold_load_s']} s | (included in build/first request) |",
        f"| Warm latency — median | {local['warm_latency_s_median']} s | "
        f"{sp('roundtrip_latency_s_median')}{' s' if space else ''} |",
        f"| Warm latency — min / max | {local['warm_latency_s_min']} / {local['warm_latency_s_max']} s | "
        + (f"{space['roundtrip_latency_s_min']} / {space['roundtrip_latency_s_max']} s |" if space else "— |"),
        f"| Throughput (median) | {local['throughput_tok_per_s_median']} tok/s | n/a (round-trip) |",
    ]
    lines += [
        "",
        "> Local = pure generation time on this machine's CPU. HF Space = full "
        "client round-trip (network + Gradio queue + generation) and so is the "
        "more realistic user-facing number. The free 2-vCPU Space is far slower "
        "than a modern laptop CPU and generates up to 512 tokens, so longer "
        "answers dominate its latency — the $0-for-latency tradeoff a paid "
        "CPU/GPU tier would close.",
        "",
        "## Cost",
        "",
        "| Tier | Hardware | Price | Notes |",
        "|---|---|---|---|",
        "| **Deployed (current)** | HF Space free CPU (2 vCPU, 16 GB) | **$0** | Sleeps after ~48 h idle; cold-starts on next visit |",
        "| CPU upgrade | 8 vCPU, 32 GB | ~$0.03 / hr | Lower latency, no sleep (verify current HF pricing) |",
        "| GPU (T4 small) | 16 GB VRAM | ~$0.40 / hr | Only needed for larger models; not required here |",
        "",
        f"At free tier the marginal cost per request is **$0**. {local['model']} "
        "fits in a CPU container, so no GPU is required — that is the core "
        "cost advantage of a small OSS model for this use case.",
        "",
    ]
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--space", help="HF Space id, e.g. meheck/ollive-oss-assistant")
    args = parser.parse_args()

    print("Benchmarking local in-process model (CPU)...")
    local = bench_local()
    print(json.dumps(local, indent=2))

    space = None
    if args.space:
        print(f"\nBenchmarking live Space {args.space} (end-to-end)...")
        space = bench_space(args.space)
        print(json.dumps(space, indent=2))

    (REPO_ROOT / "results").mkdir(exist_ok=True)
    (REPO_ROOT / "report").mkdir(exist_ok=True)
    raw = {"local": local, "space": space}
    (REPO_ROOT / "results" / "latency_raw.json").write_text(json.dumps(raw, indent=2))
    md = render_markdown(local, space)
    (REPO_ROOT / "report" / "cost_latency.md").write_text(md)
    print("\nWrote results/latency_raw.json and report/cost_latency.md")


if __name__ == "__main__":
    main()
