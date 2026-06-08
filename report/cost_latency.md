# OSS Deployment — Cost & Latency

Model: **Qwen/Qwen2.5-1.5B-Instruct**  ·  Prompt set: 5 prompts × 3 runs (greedy decoding).

## Latency & throughput

| Metric | Local (CPU, in-process) | HF Space (free CPU, end-to-end) |
|---|---|---|
| Cold model load | 8.586 s | (included in build/first request) |
| Warm latency — median | 1.616 s | 61.738 s |
| Warm latency — min / max | 0.876 / 7.836 s | 28.713 / 137.369 s |
| Throughput (median) | 10.729 tok/s | n/a (round-trip) |

> Local = pure generation time on this machine's CPU. HF Space = full client round-trip (network + Gradio queue + generation) and so is the more realistic user-facing number. The free 2-vCPU Space is far slower than a modern laptop CPU and generates up to 512 tokens, so longer answers dominate its latency — the $0-for-latency tradeoff a paid CPU/GPU tier would close.

## Cost

| Tier | Hardware | Price | Notes |
|---|---|---|---|
| **Deployed (current)** | HF Space free CPU (2 vCPU, 16 GB) | **$0** | Sleeps after ~48 h idle; cold-starts on next visit |
| CPU upgrade | 8 vCPU, 32 GB | ~$0.03 / hr | Lower latency, no sleep (verify current HF pricing) |
| GPU (T4 small) | 16 GB VRAM | ~$0.40 / hr | Only needed for larger models; not required here |

At free tier the marginal cost per request is **$0**. Qwen/Qwen2.5-1.5B-Instruct fits in a CPU container, so no GPU is required — that is the core cost advantage of a small OSS model for this use case.
