"""Frontier assistant backed by a hosted foundation model (Google Gemini).

Implements the same `Assistant` interface as the OSS backend, so the chat UI
and eval harness treat them identically -- the only differences are where the
model runs (Google's API vs local CPU) and its capability.
"""

from __future__ import annotations

import os

from google import genai
from google.genai import types

from .base import DEFAULT_SYSTEM_PROMPT, Assistant, Message

__all__ = ["FrontierAssistant", "DEFAULT_MODEL", "DEFAULT_SYSTEM_PROMPT"]

DEFAULT_MODEL = "gemini-2.5-flash"

# Gemini uses "model" for the assistant role; our internal role is "assistant".
_ROLE_MAP = {"user": "user", "assistant": "model"}


class FrontierAssistant(Assistant):
    def __init__(
        self,
        model_name: str = DEFAULT_MODEL,
        system_prompt: str = DEFAULT_SYSTEM_PROMPT,
        max_messages: int = 16,
        max_new_tokens: int = 512,
        temperature: float = 0.7,
        api_key: str | None = None,
    ) -> None:
        super().__init__(system_prompt=system_prompt, max_messages=max_messages)
        self.model_id = model_name
        self.model_name = model_name
        self.max_new_tokens = max_new_tokens
        self.temperature = temperature
        key = api_key or os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
        if not key:
            raise ValueError(
                "No Gemini API key. Set GEMINI_API_KEY (or GOOGLE_API_KEY) in .env."
            )
        self._client = genai.Client(api_key=key)
        #: Token usage from the most recent call (for cost/observability later).
        self.last_usage: dict[str, int] | None = None

    def _generate(self, messages: list[Message]) -> str:
        # Split the system message out (Gemini takes it separately) and convert
        # the remaining turns to Gemini's content format.
        system_instruction = self.memory.system_prompt
        contents = [
            types.Content(role=_ROLE_MAP[m.role], parts=[types.Part(text=m.content)])
            for m in messages
            if m.role in _ROLE_MAP
        ]

        response = self._client.models.generate_content(
            model=self.model_name,
            contents=contents,
            config=types.GenerateContentConfig(
                system_instruction=system_instruction,
                temperature=self.temperature,
                max_output_tokens=self.max_new_tokens,
            ),
        )

        usage = getattr(response, "usage_metadata", None)
        if usage is not None:
            self.last_usage = {
                "input_tokens": getattr(usage, "prompt_token_count", 0) or 0,
                "output_tokens": getattr(usage, "candidates_token_count", 0) or 0,
            }
        return (response.text or "").strip()
