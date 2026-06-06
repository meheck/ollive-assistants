# OSS Deployment — Cost & Latency

Model: **Qwen/Qwen2.5-0.5B-Instruct**  ·  Prompt set: 5 prompts × 3 runs (greedy decoding).

## Latency & throughput

| Metric | Local (CPU, in-process) | HF Space (free CPU, end-to-end) |
|---|---|---|
| Cold model load | 3.883 s | (included in build/first request) |
| Warm latency — median | 0.975 s | 6.028 s |
| Warm latency — min / max | 0.256 / 2.184 s | 2.298 / 17.963 s |
| Throughput (median) | 37.936 tok/s | n/a (round-trip) |

> Local = pure generation time on this machine's CPU. HF Space = full client round-trip (network + Gradio queue + generation) and so is the more realistic user-facing number.

## Cost

| Tier | Hardware | Price | Notes |
|---|---|---|---|
| **Deployed (current)** | HF Space free CPU (2 vCPU, 16 GB) | **$0** | Sleeps after ~48 h idle; cold-starts on next visit |
| CPU upgrade | 8 vCPU, 32 GB | ~$0.03 / hr | Lower latency, no sleep (verify current HF pricing) |
| GPU (T4 small) | 16 GB VRAM | ~$0.40 / hr | Only needed for larger models; overkill for 0.5B |

At free tier the marginal cost per request is **$0**. The 0.5B model fits in a CPU container, so no GPU is required — that is the core cost advantage of a small OSS model for this use case.
