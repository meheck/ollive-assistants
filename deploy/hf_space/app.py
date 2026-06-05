"""Gradio chat UI for the open-source assistant (Qwen2.5-0.5B-Instruct).

This file is the entrypoint for both:
  * local runs  -- `PYTHONPATH=src uv run python deploy/hf_space/app.py`
  * the public Hugging Face Space (the deploy script vendors `assistants/`
    next to this file so the Space is self-contained).

It deliberately stays UI-only; all model/memory logic lives in the shared
`assistants` package so the deployed Space and the local app cannot drift.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

# Make the shared package importable whether running from the repo (src/ on
# path) or from the Space (assistants/ vendored beside this file). On the Space
# app.py sits at /app/app.py, so the repo-relative src/ path may not exist --
# guard against that.
sys.path.insert(0, str(Path(__file__).parent))
try:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
except IndexError:
    pass

import gradio as gr  # noqa: E402

from assistants.oss import DEFAULT_SYSTEM_PROMPT, OSSAssistant  # noqa: E402

MODEL_NAME = os.getenv("OSS_MODEL", "Qwen/Qwen2.5-0.5B-Instruct")

# One assistant instance per process; Gradio state holds per-session history so
# the model itself (expensive to load) is shared across users on the Space.
_assistant = OSSAssistant(model_name=MODEL_NAME, system_prompt=DEFAULT_SYSTEM_PROMPT)


def _respond(message: str, history: list[dict]):
    """Gradio ChatInterface callback.

    Gradio passes per-session `history` (a list of {role, content} dicts in the
    default messages format). We rebuild the assistant's short-term memory from
    it so concurrent users on the Space don't share conversational context even
    though they share one loaded model.
    """
    _assistant.reset()
    for turn in history:
        role, content = turn["role"], turn["content"]
        if role == "user":
            _assistant.memory.add_user(content)
        elif role == "assistant":
            _assistant.memory.add_assistant(content)
    return _assistant.chat(message)


demo = gr.ChatInterface(
    fn=_respond,
    title="Ollive — Open-Source Assistant (Qwen2.5-0.5B-Instruct)",
    description=(
        "A lightweight personal assistant running an open-source model on CPU. "
        "Multi-turn with short-term conversational memory."
    ),
    examples=[
        "What can you help me with?",
        "Explain the difference between TCP and UDP in two sentences.",
        "My name is Sam — remember it. What's my name?",
    ],
)


if __name__ == "__main__":
    demo.launch(server_name="0.0.0.0", server_port=int(os.getenv("PORT", "7860")))
