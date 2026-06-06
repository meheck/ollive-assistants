"""Gradio chat UI for the open-source assistant (Qwen2.5-0.5B-Instruct).

Entrypoint for both local runs and the public Hugging Face Space. UI-only; the
model/memory logic lives in the shared `assistants` package and the chat glue
in `shared_chat`, both vendored beside this file at deploy time so the Space is
self-contained and cannot drift from the repo.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

# Make vendored modules importable on the Space, and src/ importable locally.
sys.path.insert(0, str(Path(__file__).parent))
try:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
except IndexError:
    pass

from assistants.oss import DEFAULT_MODEL, DEFAULT_SYSTEM_PROMPT, OSSAssistant  # noqa: E402
from assistants.tools import default_registry  # noqa: E402
from shared_chat import build_demo  # noqa: E402

MODEL_NAME = os.getenv("OSS_MODEL", DEFAULT_MODEL)

# One shared model instance per process (loading is expensive); per-session
# history is replayed into it each turn, and each session gets its own tool
# sandbox (WorldState) via shared_chat.
_assistant = OSSAssistant(
    model_name=MODEL_NAME, system_prompt=DEFAULT_SYSTEM_PROMPT, tools=default_registry()
)

demo = build_demo(
    _assistant,
    title="Ollive — Open-Source Assistant (Qwen2.5-1.5B-Instruct)",
    description=(
        "A personal assistant running an open-source model on CPU. Multi-turn "
        "with short-term memory and tools (calculator, web search, and sandboxed "
        "email/transfer/delete actions). Each session has its own sandbox."
    ),
    examples=[
        "What can you help me with?",
        "Explain the difference between TCP and UDP in two sentences.",
        "My name is Sam — remember it. What's my name?",
    ],
)


if __name__ == "__main__":
    demo.launch(server_name="0.0.0.0", server_port=int(os.getenv("PORT", "7860")))
