# Setup & running

How to run everything locally and (re)deploy the Spaces.

## Prerequisites

- **Python 3.12** and **[uv](https://docs.astral.sh/uv/)** (manages the venv,
  deps, and Python version)
- A **Google Gemini API key** (free at https://aistudio.google.com/apikey) —
  needed for the frontier assistant
- *(Deploy only)* a **Hugging Face account** + a **write token**
  (https://huggingface.co/settings/tokens)

The OSS model (Qwen2.5-0.5B-Instruct) is public and downloads automatically on
first run — no HF token needed just to run it.

## 1. Install

```bash
uv sync          # creates .venv and installs the locked dependencies
```

## 2. Configure secrets

```bash
cp .env.example .env
```

Edit `.env`:

```
GEMINI_API_KEY=...        # required for the frontier assistant
HF_TOKEN=hf_...           # only needed to deploy to Hugging Face Spaces
```

> The `ANTHROPIC_API_KEY` that may already exist in your shell is Claude Code's
> own token and is **not** a usable API key — ignore it.

## 3. Run the assistants locally

Both are Gradio apps (open the printed local URL in a browser).

```bash
# Open-source assistant (Qwen2.5-0.5B on CPU; first run downloads ~1 GB)
PYTHONPATH=src uv run python deploy/hf_space/app.py

# Frontier assistant (Gemini; needs GEMINI_API_KEY in .env)
PYTHONPATH=src uv run python deploy/hf_space_frontier/app.py
```

Each serves on http://localhost:7860 by default (set `PORT` to change).

## 4. Cost + latency benchmark

```bash
# Local only
uv run python eval/bench_latency.py

# Also benchmark the live public Space (end-to-end round-trip)
uv run python eval/bench_latency.py --space meheck/ollive-oss-assistant
```

Writes `results/latency_raw.json` and `report/cost_latency.md`.

## 5. Deploy to Hugging Face Spaces (optional)

Requires `HF_TOKEN` (write) in `.env`.

```bash
# OSS assistant (public)
uv run python deploy/push_space.py --space-id <user>/ollive-oss-assistant

# Frontier assistant (public; the key set as a Space Secret is what visitors
# use by default). Pass the demo key via env so THAT key is stored, not your
# personal .env key:
GEMINI_API_KEY='<free-tier-demo-key>' uv run python deploy/push_space.py \
  --space-id <user>/ollive-frontier-assistant \
  --source hf_space_frontier --vendor frontier.py \
  --secret GEMINI_API_KEY

# (add --private to keep a Space owner-only)
```

The frontier Space also has an optional "your API key" field so a visitor can
use their own quota instead of the shared demo key.

The deploy script vendors the shared code into the Space, so each Space is
self-contained.

## Live demos

- OSS (public): https://huggingface.co/spaces/meheck/ollive-oss-assistant
- Frontier (public): https://huggingface.co/spaces/meheck/ollive-frontier-assistant

## Troubleshooting

- **`GEMINI_API_KEY` not set** — the frontier app raises on startup; check `.env`.
- **Slow first OSS response** — model weights load lazily on the first message
  (~4 s locally; longer on a cold Space).
- **MPS / Metal error on Apple Silicon** — the OSS model runs on CPU by design;
  override with `OSS_DEVICE=mps` only if your setup supports it.
