# Architecture (so far)

A comparison of two personal assistants — one open-source, one frontier —
sharing a single interface so they can be evaluated head-to-head. Built for the
Ollive take-home.

## Goal

Build two multi-turn assistants with short-term memory (one OSS model from
Hugging Face, one hosted frontier model), deploy them, and evaluate them on
hallucination, bias/harm, and content safety. Bonus: public deployment,
cost/latency, observability, evals, guardrails, memory/tools.

## Repo layout

```
src/assistants/        Core library (the two backends + shared contract)
  base.py              Assistant ABC, Message type, ShortTermMemory, system prompt
  oss.py               OSSAssistant  -> Qwen2.5-0.5B-Instruct via transformers
  frontier.py          FrontierAssistant -> Google Gemini via google-genai
deploy/
  shared_chat.py       Gradio chat glue (history coercion + build_demo), vendored
  hf_space/            OSS Space: app.py, requirements.txt, README.md
  hf_space_frontier/   Frontier Space: app.py, requirements.txt, README.md
  push_space.py        Deploy script (vendors code, sets Secrets, public/private)
eval/
  bench_latency.py     Cost + latency benchmark (local CPU + live Space)
report/                Generated artifacts (cost_latency.md, eval report)
results/               Raw run outputs (gitignored)
```

## Core abstraction

Everything is built on one contract in `base.py`:

- **`Message`** — `{role, content}` with roles `system | user | assistant`.
- **`ShortTermMemory`** — in-session memory: a sliding window over the last N
  messages (default 16). The system prompt is stored separately and always
  retained; only the user/assistant exchange is windowed.
- **`Assistant` (ABC)** — handles memory bookkeeping in `chat()`; subclasses
  implement only `_generate(messages) -> str`. This guarantees both backends
  get an identical context-construction policy, so the comparison isolates the
  *model*, not the harness.
- **`DEFAULT_SYSTEM_PROMPT`** — one shared persona used by both backends.

```
user turn -> memory.add_user -> _generate(system + windowed history) -> memory.add_assistant -> reply
```

## Backends

| | OSS | Frontier |
|---|---|---|
| Class | `OSSAssistant` | `FrontierAssistant` |
| Model | Qwen2.5-0.5B-Instruct | gemini-2.5-flash |
| Runtime | local weights (transformers), CPU | hosted Google API |
| Cost | compute you host ($0 on free tier) | per-token API |
| Notes | lazy weight-loading; greedy/sampling | captures token usage for cost |

Both implement the same interface, so the chat UI, benchmark, and (upcoming)
eval harness treat them interchangeably — swapping is one line.

## Deployment

Each assistant is a **Gradio app** that doubles as a **Hugging Face Space**.
The same `app.py` runs locally and on the Space.

- **Vendoring**: `push_space.py` assembles a *self-contained* Space — it copies
  `shared_chat.py` and the needed `assistants/` modules into the upload, so the
  Space never depends on the rest of the repo, yet the code is edited in exactly
  one place (no drift).
- **Shared chat glue** (`shared_chat.py`): `build_demo()` wraps a single shared
  assistant instance in a `ChatInterface`. The model loads once per process;
  each turn the assistant is reset and rebuilt from *that session's* history, so
  concurrent users never share context. History content is coerced to text to
  survive Gradio's string-or-list content format.
- **Secrets**: the frontier Space reads `GEMINI_API_KEY` from a Space Secret
  (set via the deploy script), never from committed code.

Deployed Spaces:
- OSS (public): https://huggingface.co/spaces/meheck/ollive-oss-assistant
- Frontier (public): https://huggingface.co/spaces/meheck/ollive-frontier-assistant

The frontier Space ships with a dedicated **free-tier** Gemini key (a Secret),
so visitors can try it with zero setup, and exposes an **optional "your API
key" field** — if a user pastes their own key it is used (per-key assistant
cache); a bad/exhausted key falls back to the demo key so chat stays usable.

## Key decisions & tradeoffs

| Decision | Choice | Why |
|---|---|---|
| Reproducibility | `uv` + committed lockfile, **no Docker** | torch makes Docker images huge; uv pins deps+Python and the public Space already containerizes the OSS side |
| OSS device | **CPU** (MPS disabled) | Qwen2.5 trips an Apple Metal assertion on MPS; CPU is reliable and matches the free Space tier |
| OSS backend topology | local weights now; remote Space available | local gives deterministic, seed-controlled runs for evals |
| Frontier model | Gemini 2.5 Flash | fast/cheap, clean cost/latency contrast vs OSS |
| Eval judge | Gemini 2.5 Pro (planned) | no working Anthropic key; stronger model judges weaker; within-family bias documented as a limitation |
| Frontier Space visibility | public, dedicated free-tier key | zero-setup demo; free-tier can't bill; optional user-key field for own quota |

## Status

Done: both assistants + shared interface; OSS deployed (public) and frontier
deployed (private); cost+latency benchmark.

Pending: eval framework (hallucination / bias / content safety with
dimension-specific judges), observability/tracing, tool use, cross-session
memory (Mem0), Streamlit demo UI, README + 1-page report.
