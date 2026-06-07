# Setup & running

There are three ways to use this project. Most people only need the first two.

| Mode | Setup | Gemini key? |
|---|---|---|
| **A. Just try it** | none — click the live links | no |
| **B. Run the code locally** | `uv sync` + a key in `.env` | yes (any key works) |
| **C. Host your own copy** | deploy to HF Spaces | your own |

---

## A. Just try it (no setup)

Open the public Spaces in a browser:

- OSS assistant: https://huggingface.co/spaces/meheck/ollive-oss-assistant
- Frontier assistant: https://huggingface.co/spaces/meheck/ollive-frontier-assistant

The frontier Space already includes a free-tier Gemini key, so it just works.
It also has an optional "your API key" field if you'd rather use your own quota
— still no deploy or local setup needed.

---

## B. Run the code locally

For running the assistants/eval harness on your machine.

### Prerequisites
- **Python 3.12** and **[uv](https://docs.astral.sh/uv/)**
- A **Google Gemini API key** — needed only for the *frontier* assistant and
  the eval judge. Get one free at https://aistudio.google.com/apikey. (The OSS
  assistant needs no key.)

### 1. Install
```bash
uv sync          # creates .venv and installs the locked dependencies
```

### 2. Configure
```bash
cp .env.example .env
```
Edit `.env`:
```
GEMINI_API_KEY=...        # any Gemini key (your own, or the demo key)
```
> The frontier code reads this from the environment because, unlike the live
> Space, a local process has no key baked in. `HF_TOKEN` is only needed for
> mode C below.

### 3a. Local assistant CLI (tools + cross-session memory)
The fullest local experience — tools and persistent cross-session memory wired
together:
```bash
uv run python chat.py                    # OSS model (Qwen2.5-1.5B; no key needed)
uv run python chat.py --model frontier   # Gemini (needs GEMINI_API_KEY in .env)
```
Options: `--user <id>` (memory scope; defaults to `$OLLIVE_USER_ID`/OS user),
`--memory-dir <path>`, `--no-tools`, `--no-memory`, `--trace` (write a
version-pinned JSON trace per turn to `results/traces/`). In-chat commands:
`/world` (inspect the tool sandbox), `/memories`, `/reset`, `/help`, `/exit`.
Run it again later with the same `--user` and it remembers earlier sessions.

### 3b. Chat UIs (same apps as the deployed Spaces)
Gradio apps with tools + per-session sandbox (no long-term memory — that's
local/CLI only). Open the printed local URL.
```bash
# Open-source assistant (Qwen2.5-1.5B on CPU; first run downloads ~3 GB; no key)
uv run python deploy/hf_space/app.py

# Frontier assistant (Gemini; needs GEMINI_API_KEY in .env)
uv run python deploy/hf_space_frontier/app.py
```
Each serves on http://localhost:7860 (set `PORT` to change).

### 4. Cost + latency benchmark
```bash
uv run python eval/bench_latency.py                                  # local only
uv run python eval/bench_latency.py --space meheck/ollive-oss-assistant   # + live Space
```
Writes `results/latency_raw.json` and `report/cost_latency.md`.

---

## C. Host your own copy (optional / maintainer)

You do **not** need this to run or evaluate the project — it only publishes your
own Spaces. Requires a Hugging Face account and a **write** `HF_TOKEN` in `.env`.

```bash
# OSS assistant (public)
uv run python deploy/push_space.py --space-id <user>/ollive-oss-assistant

# Frontier assistant (public)
uv run python deploy/push_space.py \
  --space-id <user>/ollive-frontier-assistant \
  --source hf_space_frontier --vendor frontier.py \
  --secret GEMINI_API_KEY
```

Notes:
- `--secret GEMINI_API_KEY` stores the key currently in your environment as the
  Space's Secret — that key is what visitors use by default. To publish a
  *demo* key rather than your personal one, prefix the command with it:
  `GEMINI_API_KEY='<demo-key>' uv run python deploy/push_space.py ...`
- Add `--private` to make a Space owner-only.
- The script vendors the shared code into each Space, so Spaces are
  self-contained and never drift from the repo.

---

## Troubleshooting

- **`GEMINI_API_KEY` not set** — the frontier app raises on startup; check `.env`.
- **Slow first OSS response** — weights load lazily on the first message
  (~4 s locally; longer on a cold Space).
- **MPS / Metal error on Apple Silicon** — the OSS model runs on CPU by design;
  override with `OSS_DEVICE=mps` only if your setup supports it.
