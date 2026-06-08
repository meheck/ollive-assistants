# Architecture

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
  base.py              Assistant ABC, Message, ShortTermMemory, shared prompt, chat() loop
  oss.py               OSSAssistant  -> Qwen2.5-1.5B-Instruct via transformers
  frontier.py          FrontierAssistant -> Google Gemini via google-genai
  tools.py             ToolRegistry + sandboxed WorldState (calc/web/transfer/email/delete)
  long_term_memory.py  Cross-session memory (Mem0, infer=False, local embedder, PII-scrubbed)
  observability.py     JSONL per-turn tracer + dereferenceable version manifest
  tracing.py           Optional live OpenTelemetry/OpenInference tracing -> Phoenix
  version.py           Agent / prompt / tools content-hash version ids
  cli.py               Local REPL (tools + cross-session memory)
eval/
  framework/           Threat templates, capability manifest, generate, oracles, judges, runner
  run_evals.py         Run the suite (seeded sample) -> per-result rows + scorecard
  scorecard.py         Merge per-model results -> report/scorecard.{md,svg}
  bench_latency.py     Cost + latency benchmark (local CPU + live Space)
  scenarios.frozen.json  Frozen, content-hashed scenario set (the auditable suite)
deploy/
  shared_chat.py       Gradio chat glue (history coercion + build_demo), vendored
  hf_space/            OSS Space: app.py, requirements.txt, README.md
  hf_space_frontier/   Frontier Space: app.py, requirements.txt, README.md
  push_space.py        Deploy script (vendors code, sets Secrets, public/private)
chat.py                Local entry point (-> assistants.cli)
report/                Deliverables (eval_report.md, scorecard.{md,svg}, cost_latency.md)
results/               Raw run outputs + traces (gitignored)
```

## Core abstraction

Everything is built on one contract in `base.py`:

- **`Message`** — `{role, content}` with roles `system | user | assistant`.
- **`ShortTermMemory`** — in-session memory: a sliding window by approximate
  **token budget** (default 6000), keeping the most recent turns that fit. The
  system prompt is stored separately and always retained.
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
| Model | Qwen2.5-1.5B-Instruct | gemini-2.5-flash |
| Runtime | local weights (transformers), CPU | hosted Google API |
| Cost | compute you host ($0 on free tier) | per-token API |
| Tool calls | Qwen chat-template `tools` + `<tool_call>` parsing | Gemini `FunctionDeclaration`s |
| Notes | lazy weight-loading; greedy/sampling | captures token usage for cost |

Both implement the same interface, so the chat UI, benchmark, and (upcoming)
eval harness treat them interchangeably — swapping is one line.

## Tools (native function calling)

When an assistant is given a `ToolRegistry`, `base.chat()` runs a native
tool-calling loop (≤ `MAX_TOOL_ITERS` cycles): generate → if the model requests
tools, execute them against a sandboxed `WorldState` and feed results back →
repeat until a plain answer. Each backend uses its own native mechanism
(Gemini function declarations; Qwen chat-template tools), so reliability scales
with model size — a measurable OSS-vs-frontier gap.

Tools are split by intent (`tools.py`):

- **Read-only (capability):** `calculator`, `web_search` (DuckDuckGo),
  `check_balance`.
- **Consequential (risk), sandboxed:** `send_email`, `transfer_funds`,
  `create_account`, `delete_record`. These mutate only an in-process
  `WorldState` (fake outbox / multi-account ledger / record store) — no real
  side effects — but look real to the model, so we can observe whether it takes
  harmful or unauthorized actions. `transfer_funds` requires both accounts to
  exist (no silent creation); every consequential call is appended to
  `WorldState.action_log` as an audit trail.

`web_search` has a fixture hook so evals can inject attacker-controlled
"results" — the untrusted-input → consequential-sink (indirect prompt
injection) attack chain — deterministically.

## Memory

Two complementary layers:

- **Short-term (in-session)** — `ShortTermMemory`, token-budget window above.
- **Long-term (cross-session)** — `LongTermMemory` (`long_term_memory.py`) over
  Mem0 with `infer=False`: turns are stored and recalled by **embedding
  similarity** (local HuggingFace embedder + persistent Chroma), so there is no
  extra LLM inference. `base.chat()` recalls relevant memories (prepended to the
  current turn only; stored history stays original) and persists the turn after.

Properties, all verified: per-`user_id` scoping (memories never cross users),
**deterministic PII scrubbing before storage** (emails/SSNs/cards/phones →
`[REDACTED_*]`), telemetry disabled, fully local. `base.py` never imports Mem0
(memory is duck-typed in), so the deployed Spaces stay dependency-light;
long-term memory is enabled in the local app / eval, not the public demos.

## Observability (evidence-grade traces)

When a `Tracer` is attached (`observability.py`), `base.chat()` writes **one
JSON record per turn** to a JSONL file. Each trace pins the four independent
versions (`version.py`: agent / prompt / model / tools) and records:

- **spans** with latency: `memory_retrieve`, `llm_generate`, `memory_store`
- **token usage** (accumulated across the tool loop) + `iterations`
- **tool calls**: name, args, result, per-call latency, and a `consequential` flag
- **recalled memories**, the input, and the reply

**Version ids are dereferenceable, not just fingerprints.** The `prompt` and
`tools` ids are one-way **content hashes** (`prompt-<sha1>`,
`tools-1.0.0+<sha1>`): they change automatically when the prompt text or any
tool schema changes — the tools id is hashed from the schemas, so it *can't*
silently drift the way a hand-bumped constant could. Because a hash alone can't
reconstruct the content, the tracer also writes a shared **`manifest.json`**
next to the traces mapping each id → its actual content (the full system prompt
text, the full tool schemas). So a trace's `prompt-72b6303d` /
`tools-1.0.0+acb7a6d9` can be resolved back to *exactly* what produced it —
which is what lets the eval harness cite a trace as evidence rather than just
"some configuration". (`agent` and `model` ids are already self-describing, so
they need no manifest entry.)

The eval harness reuses these traces as the **evidence** behind each score —
e.g. "the agent called `transfer_funds` to a new account after an injected
instruction; here is the trace." The tracer is duck-typed/injected (like
memory), so plain chat (the deployed Spaces) is unaffected. Enabled via the CLI
`--trace` flag and always-on in the eval.

**Live tracing (`tracing.py`).** The JSONL above is the durable, offline,
dependency-free record. Layered *over* it — not replacing it — is live
OpenTelemetry instrumentation that streams each turn to a UI (Arize Phoenix) as
it runs, the way production observability actually works. `base.chat()` opens an
`agent.turn` span with child spans (`memory_retrieve` → `llm_generate` → `tool.*`
→ `memory_store`) carrying the **real** input messages, output, token counts,
and tool args/results — full fidelity, because the spans are created where that
data lives. Spans follow **OpenInference** conventions, which both Phoenix *and*
Langfuse speak, so the backend isn't baked in. It is a hard **no-op** unless
`PHOENIX_COLLECTOR_ENDPOINT` is set: OpenTelemetry is imported lazily, the
`span()` helpers degrade to no-ops, and the core package carries no new
dependency when tracing is off (so the Spaces stay light). The OTel `trace_id`
is written back into the JSONL, linking the durable record to its live span; and
the eval harness attaches each verdict to its turn span as a native Phoenix
**annotation**, so a failing score is one click from the transcript and the
exact tool call that caused it.

## Evaluation framework

The eval system (`eval/framework/`) treats evaluation as **evidence generation
about an agent's risk profile**, so the unit of evaluation is not a prompt but a
frozen, serializable **threat scenario** whose grader travels with it.

- **Agent-independent threat templates → a capability manifest.** Each dimension
  is a set of `ThreatTemplate`s (attack patterns) with a `precondition` and an
  `expand(manifest, rng)`. They instantiate against a **`CapabilityManifest`**
  derived from the agent's *tool schemas* (the only agent-general interface) — so
  two agents with the same tools get the identical scenario set, and comparability
  falls out of generation being a function of the manifest, not hand-authoring.
- **Frozen + content-hashed.** `generate(seed=42)` is deterministic; `freeze()`
  content-hashes the set into `eval/scenarios.frozen.json` tagged
  `evalkit-1.0.0+<hash>` — the auditable suite each run is checked against.
- **Oracle vs judge grading.** A scenario carries an **oracle** (deterministic
  code over the sandbox's `action_log` — *did `transfer_funds` fire? is the raw
  SSN in the store?*) and/or an **LLM judge** (Gemini 2.5 Pro, versioned rubric)
  for the semantic dimensions. Structural, ground-truth facts go to oracles; only
  genuinely semantic calls go to the judge — which also keeps the differentiator
  dimensions (tool / injection / memory) off a judge that shares a family with the
  frontier agent.
- **Multi-session / multi-user.** A scenario can have several `Session`s sharing
  one `WorldState` + long-term store with per-session `user_id`, so cross-session
  memory threats (poisoning, cross-user leakage) are first-class.
- **Bounded, reproducible cost.** A run takes a **seeded 5-per-subdimension**
  sample of the suite; every result row cites the framework version, the sample
  seed, and the turn `trace_id`s — so a score is reproducible and traces back to
  its evidence (above), and verdicts are logged onto those traces as Phoenix
  annotations when live tracing is on.

Coverage: **201 scenarios across 6 dimensions / 14 subdimensions** — hallucination,
bias, content-safety (the required three) plus tool-safety, prompt-injection, and
memory-safety (the agentic risks an AI-liability insurer cares about). Results and
their limitations are written up in `report/eval_report.md`.

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
- **Per-session tool sandbox**: when tools are enabled, each browser session
  gets its own `WorldState` via a per-session `gr.State`, and `concurrency_limit=1`
  serializes turns on the shared model — so one visitor's fake emails/transfers
  never appear in another's.
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
| Reproducibility | `uv` + committed lockfile, **intentionally no Docker** | see "Why no Docker" below |
| OSS device | **CPU** (MPS disabled) | Qwen2.5 trips an Apple Metal assertion on MPS; CPU is reliable and matches the free Space tier |
| OSS backend topology | local weights now; remote Space available | local gives deterministic, seed-controlled runs for evals |
| Frontier model | Gemini 2.5 Flash | fast/cheap, clean cost/latency contrast vs OSS |
| Eval judge | Gemini 2.5 Pro | no working Anthropic key; stronger model judges weaker; within-family bias documented as a limitation (and side-stepped on the differentiator dimensions via oracles) |
| Frontier Space visibility | public, dedicated free-tier key | zero-setup demo; free-tier can't bill; optional user-key field for own quota |
| Cross-session memory | Mem0 self-hosted, **`infer=False`**, local embedder | see "Why memory makes no extra inference calls" below |

### Why no Docker (intentional)

Not using Docker is a deliberate choice, not an omission:

- **`uv` already gives reproducible installs.** A committed `uv.lock` pins every
  transitive dependency *and* the Python version; `uv sync` reconstructs the
  exact environment in seconds. That covers the "it runs on their machine"
  requirement without a 2–4 GB torch-based image.
- **No services to stand up.** The only stateful component is the vector DB
  (Chroma), and it runs **embedded / in-process** — it persists to a local
  folder, auto-created on first run. There is nothing to orchestrate, so the
  usual reason to reach for Docker/compose (multi-service wiring) doesn't apply.
- **The public Space already containerizes the OSS side.** Hugging Face Spaces
  builds and runs the OSS assistant in its own container, so the "works in a
  clean environment" guarantee exists where it matters most — and graders can
  click it with zero setup.

Net: the grader experience is `uv sync` → `.env` → run, with a live public
demo as the zero-setup fallback. Docker would add image weight and build time
for no reproducibility we don't already have.

### Why memory makes no extra inference calls (intentional)

Mem0 has two modes; we deliberately use neither of the costly defaults:

- **Mem0 open-source, default (`infer=True`)** would make an *extra LLM call per
  stored turn* to extract/condense facts — billed to our Gemini key. Rejected:
  we don't want memory to add inference cost or latency.
- **Mem0 Platform (hosted)** would run extraction on Mem0's servers (free tier),
  but adds an external account dependency and, worse, sends conversation data
  off the machine — unacceptable for a PII-sensitive context.

We use **Mem0 self-hosted with `infer=False`**: turns are stored directly and
recalled by **embedding similarity** using a **local `sentence-transformers`
model** (CPU, no API call). Consequences, all intentional:

- **Zero extra LLM inference** for memory — no Gemini calls, no added latency.
- **Fully local** — nothing leaves the machine; embedded Chroma + local embedder.
- **No external account** — pure pip deps; the grader story stays `uv sync`.
- **PII handled deterministically** — since no LLM is in the loop, a regex/rule
  scrubber redacts PII *before* storage (predictable, not model-dependent).

Tradeoff: we store raw turns (recalled by similarity) rather than LLM-distilled
facts. That's good enough for cross-session recall, and flipping to `infer=True`
later is a one-line change if distilled-fact memory is ever wanted.

## Status

Complete. Both assistants share one interface; OSS (Qwen2.5-1.5B) and frontier
(Gemini 2.5 Flash) are **deployed publicly** with native function-calling + a
per-session tool sandbox, token-budget short-term memory, cross-session memory
(Mem0, `infer=False`, PII-scrubbed, local-only), and a local CLI (`chat.py`).
Observability is version-pinned JSONL traces **plus** optional live
OpenTelemetry → Phoenix, with eval verdicts logged onto the traces. The
**evaluation framework** (above) is built, frozen, and run head-to-head across
all six dimensions, with a 1-page report (`report/eval_report.md`) + scorecard
and a cost/latency benchmark.

### Future improvements

- **Multi-turn follow-through.** Most scenarios are single-turn, so an agent that
  *accepts* a harmful/consequential task but defers ("sure — just confirm and give
  me the details") is scored as a pass: no harmful content, no sink fired. That
  inflates the content-safety and tool-safety rates. Fix: add a second turn that
  supplies the confirmation/detail and grade the *final* action, plus a judge
  clause that scores accept-and-ask-for-details as a failure. (See the report's
  Limitations.)
- **Injection ingestion check.** The indirect-prompt-injection oracle only checks
  that the consequential sink did not fire. For the *email-exfiltration* chains the
  sink is off the user's natural path (the benign turn never asks to email
  anything), so a model that simply answers normally — or never even runs the
  search — produces the same PASS as one that actively resisted: a vacuous pass.
  Fix: record whether the poisoned `web_search` fixture was actually served
  (an ingestion flag on `WorldState`), and count a resist as genuine only when the
  poison was ingested; surface non-ingested runs as inconclusive, not pass. The
  transfer/delete/create chains are unaffected (their sink is on the task path).
- **Generic environment seam for tool/world evals.** The eval framework's generic
  core (oracles, generator, judges) does not import our sandbox — it duck-types an
  audit trail — but the runner's env-adapter is bound to our concrete `WorldState`.
  Testing tool-use safety *requires* a simulated environment, and that simulation
  is inherently agent-specific (true of τ-bench, WebArena, etc.) — so the right
  generalization is to depend on an explicit `Environment` *protocol*
  (`seed()` / `actions()` / `outputs()`) with `WorldState` as the first adapter,
  rather than on the class itself. Deferred intentionally: for this take-home we
  evaluate one agent, so we ship one concrete sandbox; making the seam explicit is
  the path to evaluating arbitrary agents on the same ruler.
