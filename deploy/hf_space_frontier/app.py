"""Gradio chat UI for the frontier assistant (Google Gemini).

Entrypoint for both local runs and the public Hugging Face Space. The Space
ships with a free-tier Gemini key (from the GEMINI_API_KEY Secret) so visitors
can try it with zero setup; an optional textbox lets a user supply their own key
to use their own quota instead.
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

import gradio as gr  # noqa: E402

from assistants.frontier import DEFAULT_SYSTEM_PROMPT, FrontierAssistant  # noqa: E402
from shared_chat import ingest_history  # noqa: E402

MODEL_NAME = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")

# Default assistant uses the Space's free-tier key (GEMINI_API_KEY Secret).
_default_assistant = FrontierAssistant(model_name=MODEL_NAME, system_prompt=DEFAULT_SYSTEM_PROMPT)


def _mask(key: str) -> str:
    """Last 4 chars only -- enough to identify a key in logs without leaking it."""
    return f"...{key[-4:]}" if len(key) >= 4 else "(short)"


def _friendly_error(exc: Exception) -> str:
    """Turn a raw API exception into a short, actionable chat message."""
    msg = str(exc)
    if "RESOURCE_EXHAUSTED" in msg or "429" in msg:
        return (
            "⚠️ The shared demo key has hit its rate limit (Gemini free tier). "
            "Paste your own Gemini API key in the box above to keep chatting, "
            "or try again in a minute."
        )
    if "API key not valid" in msg or "API_KEY_INVALID" in msg:
        return "⚠️ That API key isn't valid. Clear the box to use the demo key."
    return f"⚠️ Sorry, something went wrong ({type(exc).__name__}). Please try again."


def _turn(assistant, message: str, history) -> str:
    """One turn that raises on failure (so the caller can handle it)."""
    assistant.reset()
    ingest_history(assistant, history)
    return assistant.chat(message)


def _respond(message: str, history, user_key: str):
    # Try the user's own key first (a fresh client per request -- nothing is
    # cached or retained between turns). On any failure fall back to the demo
    # key so the chat stays usable; if that also fails, show a clean message.
    user_key = (user_key or "").strip()
    if user_key:
        try:
            reply = _turn(
                FrontierAssistant(model_name=MODEL_NAME,
                                  system_prompt=DEFAULT_SYSTEM_PROMPT,
                                  api_key=user_key),
                message, history,
            )
            print(f"[frontier] served with USER key ({_mask(user_key)})", file=sys.stderr, flush=True)
            return reply
        except Exception as exc:  # noqa: BLE001
            print(f"[frontier] USER key ({_mask(user_key)}) failed: {exc}; "
                  "falling back to demo key", file=sys.stderr, flush=True)

    try:
        reply = _turn(_default_assistant, message, history)
        print("[frontier] served with DEMO key", file=sys.stderr, flush=True)
        return reply
    except Exception as exc:  # noqa: BLE001
        print(f"[frontier] DEMO key failed: {exc}", file=sys.stderr, flush=True)
        return _friendly_error(exc)


demo = gr.ChatInterface(
    fn=_respond,
    additional_inputs=[
        gr.Textbox(
            label="Your Gemini API key (optional)",
            placeholder="Leave blank to use the demo's free-tier key",
            type="password",
        )
    ],
    title="Ollive — Frontier Assistant (Gemini 2.5 Flash)",
    description=(
        "A personal assistant backed by a hosted frontier model (Google "
        "Gemini). Multi-turn with short-term conversational memory. Uses a "
        "shared free-tier key by default; paste your own key to use your quota."
    ),
)


if __name__ == "__main__":
    demo.launch(server_name="0.0.0.0", server_port=int(os.getenv("PORT", "7860")))
