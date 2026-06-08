# Ollive — OSS vs. Frontier Assistant, Evaluated for Risk

Two AI personal assistants behind one shared interface — an **open-source** model
(Qwen2.5-1.5B-Instruct, local) and a **frontier** model (Gemini 2.5 Flash, hosted) —
plus a **threat-model-driven evaluation framework** that produces *defensible
evidence about each agent's risk profile*: hallucination, bias, content-safety,
and the agentic risks an AI-liability insurer actually cares about (tool misuse,
prompt injection, memory poisoning).

Both assistants are multi-turn, have short-term + cross-session memory, call tools,
and are **deployed live**:

- 🟢 OSS demo: https://huggingface.co/spaces/meheck/ollive-oss-assistant
- 🟢 Frontier demo: https://huggingface.co/spaces/meheck/ollive-frontier-assistant

## TL;DR findings (5-per-subdimension sample, 70 scenarios/model)

![Risk profile by dimension](report/scorecard.svg)

| Dimension | OSS | Frontier |
|---|---|---|
| hallucination | 67% | 100% |
| bias | 30% | 90% |
| content_safety | 65% | 90% |
| memory_safety | 67% | 73% |
| prompt_injection | 100% | 100% |
| tool_safety | **40%** | **40%** |
| **Overall** | **61%** | **86%** |

**The headline:** *capability ≠ safety on consequential actions.* Both models score
**40%** on tool-safety — the frontier model is **no safer** at refusing irreversible,
money-moving actions (it wired $6k on a bank-impersonation scam, swept a full
balance, deleted a record). That's a **guardrail gap, not a model-quality gap.**
Frontier's real edge is *judgment* (bias, hallucination). Both fall to cross-session
memory poisoning. Full write-up: **[report/eval_report.md](report/eval_report.md)**.

## Quickstart

Needs **Python 3.12** + **[uv](https://docs.astral.sh/uv/)**. (Full guide: [SETUP.md](SETUP.md).)

```bash
uv sync
cp .env.example .env          # add a Gemini key (free: https://aistudio.google.com/apikey)

# local chat — tools + cross-session memory wired together
uv run python chat.py                    # OSS (Qwen2.5-1.5B on CPU; no key needed)
uv run python chat.py --model frontier   # Gemini 2.5 Flash (needs GEMINI_API_KEY)
```

Or just click the live demos above — zero setup (the frontier Space ships a free-tier key).

## Run the evaluation

```bash
uv run python eval/run_evals.py --models frontier        # fast
uv run python eval/run_evals.py --models frontier,oss    # head-to-head (OSS is CPU-slow)
uv run python eval/scorecard.py                          # combine -> report/scorecard.{md,svg}
uv run python eval/bench_latency.py                      # cost + latency table
```

A run takes a **seeded sample** (`--per-subdim N`, default 5) of the 201-scenario
frozen suite to bound API cost, writes per-scenario rows (with trace ids) to
`results/`, and emits the scorecard. `--all` runs the full suite.

## How it works

- **Shared contract** ([src/assistants/base.py](src/assistants/base.py)): both backends implement one
  `Assistant` interface (identical prompt, tools, memory policy), so the comparison
  isolates the *model*. Native function-calling, token-budget short-term memory.
- **Tools + sandbox** ([tools.py](src/assistants/tools.py)): read-only (calculator, web_search) and
  *consequential* (transfer/email/delete/create) tools that mutate only an in-process
  `WorldState`, so we can observe risky actions with **no real side effects**.
- **Cross-session memory** ([long_term_memory.py](src/assistants/long_term_memory.py)): Mem0 with
  `infer=False` + a local embedder — recall by similarity, PII scrubbed before
  storage, **zero extra LLM calls**.
- **Observability** ([observability.py](src/assistants/observability.py)): one version-pinned JSON trace
  per turn; the hashes dereference (via a run manifest) to the exact prompt + tool
  schemas — so a score links back to its evidence.
- **Eval framework** ([eval/framework/](eval/framework/)): 201 scenarios across 6 dimensions / 14
  subdimensions, generated from agent-independent **threat templates**, frozen +
  content-hashed for reproducibility, graded by **oracles** (deterministic, where
  the sandbox gives ground truth) and a **Gemini 2.5 Pro judge** (only where
  correctness is semantic).

Full design + rationale: **[ARCHITECTURE.md](ARCHITECTURE.md)**.

## Key tradeoffs

- **`uv` + lockfile, intentionally no Docker** — `uv sync` reconstructs the env;
  the only stateful piece (Chroma) is embedded; the public Space already
  containerizes the OSS side. (ARCHITECTURE.md → "Why no Docker".)
- **Memory makes no extra inference calls** (`infer=False`) — cheaper, fully local,
  PII handled deterministically; tradeoff is raw-turn recall vs. distilled facts.
- **Oracle-first grading** — deterministic where possible; the LLM judge is reserved
  for semantic dimensions, which also side-steps within-family judge bias on the
  differentiator dimensions.

## Future work

- **Guardrails** on consequential tools (the #1 fix — both models sit at 40%).
- **Generic `Environment` seam** so the framework evaluates arbitrary agents, not
  just our sandbox (ARCHITECTURE.md → Future improvements).
- **Injection ingestion check** (count a "resist" as genuine only if the poison was served).
- Coverage gaps vs. the *Agents of Chaos* taxonomy: storage-exhaustion / DoS,
  silent-censorship transparency, dedicated non-owner-authorization tests.

## Repo layout

```
src/assistants/   the two backends + shared contract, tools, memory, observability
eval/framework/   evaluation framework (threat templates, oracles, judges, runner)
eval/             run_evals.py, scorecard.py, bench_latency.py
deploy/           Gradio apps + HF Space deploy script (push_space.py)
report/           eval_report.md + scorecard (the deliverables)
chat.py           local REPL entry point
```

Lint: `uvx ruff@0.14.0 check .` (config in `pyproject.toml`).
