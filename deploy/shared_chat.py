"""Shared Gradio chat glue for the assistant Spaces.

Both the OSS and frontier Spaces vendor this module so the history-handling
logic (which is fiddly across Gradio versions) lives in exactly one place. The
specific assistant is injected, so this file is backend-agnostic.
"""

from __future__ import annotations

import sys
import traceback

import gradio as gr


def coerce_text(content) -> str:
    """Flatten a Gradio message's content into plain text.

    Gradio 6 may store `content` as a string OR a list of content parts
    (e.g. [{"type": "text", "text": "..."}]). Chat templates concatenate
    content as a string, so a raw list crashes them -- we flatten here.
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


def ingest_history(assistant, history) -> None:
    """Replay per-session history into the assistant's memory.

    Tolerant of Gradio's formats: dict {"role","content"}, [user, bot] pairs,
    or ChatMessage-like objects with .role/.content.
    """
    def add(role, content):
        text = coerce_text(content)
        if not text:
            return
        if role == "user":
            assistant.memory.add_user(text)
        elif role == "assistant":
            assistant.memory.add_assistant(text)

    for turn in history or []:
        if isinstance(turn, dict):
            add(turn.get("role"), turn.get("content"))
        elif isinstance(turn, (list, tuple)) and len(turn) == 2:
            add("user", turn[0])
            add("assistant", turn[1])
        else:
            add(getattr(turn, "role", None), getattr(turn, "content", None))


def run_turn(assistant, message: str, history) -> str:
    """Handle one chat turn against a (shared) assistant.

    Resets the assistant and rebuilds it from THIS session's history, so
    concurrent users never share context even though they share one instance.
    Errors are logged (visible in Space logs) and surfaced as a message rather
    than crashing the turn.
    """
    assistant.reset()
    try:
        ingest_history(assistant, history)
        return assistant.chat(message)
    except Exception as exc:  # noqa: BLE001 -- keep the Space responsive
        print(f"[run_turn] error; history repr: {repr(history)[:500]}", file=sys.stderr)
        traceback.print_exc()
        return f"[assistant error: {type(exc).__name__}: {exc}]"


def build_demo(assistant, title: str, description: str, examples: list[str]):
    """Build a ChatInterface around a single shared assistant instance."""
    return gr.ChatInterface(
        fn=lambda message, history: run_turn(assistant, message, history),
        title=title,
        description=description,
        examples=examples,
    )
