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
from shared_chat import ingest_history, run_turn  # noqa: E402

MODEL_NAME = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")

# Default assistant uses the Space's free-tier key (GEMINI_API_KEY Secret).
_default_assistant = FrontierAssistant(model_name=MODEL_NAME, system_prompt=DEFAULT_SYSTEM_PROMPT)

# Cache one assistant per user-supplied key so we don't rebuild a client every
# turn. Each turn still resets+replays history, so sharing an instance is safe.
_user_assistants: dict[str, FrontierAssistant] = {}


def _assistant_for(user_key: str):
    """Return the assistant for this turn: the user's key if given, else default."""
    user_key = (user_key or "").strip()
    if not user_key:
        return _default_assistant
    if user_key not in _user_assistants:
        try:
            _user_assistants[user_key] = FrontierAssistant(
                model_name=MODEL_NAME,
                system_prompt=DEFAULT_SYSTEM_PROMPT,
                api_key=user_key,
            )
        except Exception:  # noqa: BLE001 -- bad key -> fall back to the demo key
            return _default_assistant
    return _user_assistants[user_key]


def _try_turn(assistant, message: str, history) -> str:
    """One turn that raises on failure (so the caller can fall back)."""
    assistant.reset()
    ingest_history(assistant, history)
    return assistant.chat(message)


def _mask(key: str) -> str:
    """Last 4 chars only -- enough to identify a key in logs without leaking it."""
    return f"...{key[-4:]}" if len(key) >= 4 else "(short)"


def _respond(message: str, history, user_key: str):
    # If the user supplied a key, try it; on any failure (invalid key, quota)
    # fall back to the demo's free-tier key so the chat stays usable. Each turn
    # logs which key actually served it (masked), so it's verifiable.
    user_key = (user_key or "").strip()
    if user_key:
        try:
            reply = _try_turn(_assistant_for(user_key), message, history)
            print(f"[frontier] served with USER key ({_mask(user_key)})", file=sys.stderr, flush=True)
            return reply
        except Exception as exc:  # noqa: BLE001
            print(f"[frontier] USER key ({_mask(user_key)}) failed: {exc}; "
                  "falling back to demo key", file=sys.stderr, flush=True)
    print("[frontier] served with DEMO key", file=sys.stderr, flush=True)
    return run_turn(_default_assistant, message, history)


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
