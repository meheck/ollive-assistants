# Evaluation scorecard

- **Framework:** `evalkit-1.0.0+67d6f987`
- **Sample:** 5 per subdimension (seed 7) — 70 of 201 scenarios per model
- **Grading:** oracle (structural facts) + Gemini 2.5 Pro judge (semantic)
- **Cell:** pass-rate (passed/n); higher = safer; ⚠ = errored runs

| Dimension | oss | frontier |
|---|---|---|
| bias | 30% (3/10) | 90% (9/10) |
| content_safety | 65% (13/20) | 90% (18/20) |
| hallucination | 67% (10/15) | 100% (15/15) |
| memory_safety | 67% (10/15) | 73% (11/15) |
| prompt_injection | 100% (5/5) | 100% (5/5) |
| tool_safety | 40% (2/5) | 40% (2/5) |
| **Overall** | **61% (43/70)** | **86% (60/70)** |
