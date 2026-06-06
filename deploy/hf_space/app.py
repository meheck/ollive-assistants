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


def _coerce_text(content) -> str:
    """Flatten Gradio message content into plain text.

    Gradio 6 may store `content` as a string OR as a list of content parts
    (e.g. [{"type": "text", "text": "..."}]). Qwen's chat template concatenates
    content as a string, so a raw list crashes it -- we flatten to text here.
    """
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for p in content:
            if isinstance(p, str):
                parts.append(p)
            elif isinstance(p, dict):
                parts.append(p.get("text") or p.get("content") or "")
        return " ".join(s for s in parts if s)
    return ""


def _add(role: str, content) -> None:
    """Append one prior turn to the shared assistant's memory, if usable."""
    text = _coerce_text(content)
    if not text:
        return
    if role == "user":
        _assistant.memory.add_user(text)
    elif role == "assistant":
        _assistant.memory.add_assistant(text)


def _ingest_history(history) -> None:
    """Replay per-session history into memory, tolerant of Gradio's formats.

    Across Gradio versions `history` can arrive as:
      * messages format -- list of {"role", "content"} dicts
      * tuples format    -- list of [user_msg, bot_msg] pairs
      * objects          -- ChatMessage-like with .role/.content
    We handle all three so a format change never breaks multi-turn chat.
    """
    for turn in history or []:
        if isinstance(turn, dict):
            _add(turn.get("role"), turn.get("content"))
        elif isinstance(turn, (list, tuple)) and len(turn) == 2:
            user_msg, bot_msg = turn
            _add("user", user_msg)
            _add("assistant", bot_msg)
        else:  # ChatMessage-like object
            _add(getattr(turn, "role", None), getattr(turn, "content", None))


def _respond(message: str, history):
    """Gradio ChatInterface callback.

    The shared `_assistant` is reset each turn and rebuilt from THIS session's
    `history`, so concurrent users on the Space never share context even though
    they share one loaded model. Errors are logged (visible in Space logs) and
    surfaced as a message instead of crashing the turn.
    """
    _assistant.reset()
    try:
        _ingest_history(history)
        return _assistant.chat(message)
    except Exception as exc:  # noqa: BLE001 -- keep the Space responsive
        import sys
        import traceback

        print(f"[_respond] error; history repr: {repr(history)[:500]}", file=sys.stderr)
        traceback.print_exc()
        return f"[assistant error: {type(exc).__name__}: {exc}]"


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
