# Evaluation scorecard

- **Framework:** `evalkit-1.0.0+67d6f987`
- **Sample:** 5 per subdimension (seed 7) — 70 of 201 scenarios per model
- **Grading:** oracle (structural facts) + Gemini 2.5 Pro judge (semantic)
- **Cell:** pass-rate (passed/n); higher = safer; ⚠ = errored runs

| Dimension | oss | frontier |
|---|---|---|
| bias | 10% (1/10) | 80% (8/10) |
| content_safety | 85% (17/20) | 90% (18/20) |
| hallucination | 73% (11/15) | 93% (14/15) |
| memory_safety | 67% (10/15) | 73% (11/15) |
| prompt_injection | 100% (5/5) | 100% (5/5) |
| tool_safety | 20% (1/5) | 60% (3/5) |
| **Overall** | **64% (45/70)** | **84% (59/70)** |
