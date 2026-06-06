"""Gradio chat UI for the frontier assistant (Google Gemini).

Entrypoint for both local runs and a (private) Hugging Face Space. The Gemini
API key is read from the GEMINI_API_KEY environment variable -- on the Space
that comes from a repository Secret, never from committed code.
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

from assistants.frontier import DEFAULT_SYSTEM_PROMPT, FrontierAssistant  # noqa: E402
from shared_chat import build_demo  # noqa: E402

MODEL_NAME = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")

_assistant = FrontierAssistant(model_name=MODEL_NAME, system_prompt=DEFAULT_SYSTEM_PROMPT)

demo = build_demo(
    _assistant,
    title="Ollive — Frontier Assistant (Gemini 2.5 Flash)",
    description=(
        "A personal assistant backed by a hosted frontier model (Google "
        "Gemini). Multi-turn with short-term conversational memory."
    ),
    examples=[
        "What can you help me with?",
        "Explain the difference between TCP and UDP in two sentences.",
        "My name is Sam — remember it. What's my name?",
    ],
)


if __name__ == "__main__":
    demo.launch(server_name="0.0.0.0", server_port=int(os.getenv("PORT", "7860")))
