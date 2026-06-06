"""Frontier assistant backed by a hosted foundation model (Google Gemini).

Implements the same `Assistant` interface as the OSS backend, so the chat UI
and eval harness treat them identically -- the only differences are where the
model runs (Google's API vs local CPU) and its capability.
"""

from __future__ import annotations

import os

from google import genai
from google.genai import types

from .base import DEFAULT_SYSTEM_PROMPT, MAX_TOOL_ITERS, Assistant, Message

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
        tools=None,
        world=None,
    ) -> None:
        super().__init__(system_prompt=system_prompt, max_messages=max_messages,
                         tools=tools, world=world)
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

    def _build_config(self):
        kwargs = dict(
            system_instruction=self.memory.system_prompt,
            temperature=self.temperature,
            max_output_tokens=self.max_new_tokens,
        )
        if self.tools is not None:
            declarations = [
                types.FunctionDeclaration(
                    name=s["name"], description=s["description"], parameters=s["parameters"]
                )
                for s in self.tools.schemas()
            ]
            kwargs["tools"] = [types.Tool(function_declarations=declarations)]
        return types.GenerateContentConfig(**kwargs)

    def _record_usage(self, response) -> None:
        usage = getattr(response, "usage_metadata", None)
        if usage is not None:
            self.last_usage = {
                "input_tokens": getattr(usage, "prompt_token_count", 0) or 0,
                "output_tokens": getattr(usage, "candidates_token_count", 0) or 0,
            }

    def _generate(self, messages: list[Message]) -> str:
        # Split the system message out (Gemini takes it separately) and convert
        # the remaining turns to Gemini's content format.
        contents = [
            types.Content(role=_ROLE_MAP[m.role], parts=[types.Part(text=m.content)])
            for m in messages
            if m.role in _ROLE_MAP
        ]
        config = self._build_config()
        self.last_tool_calls = []

        # Native function-calling loop: generate -> if the model requests tools,
        # execute them against the sandbox and feed results back -> repeat.
        for _ in range(MAX_TOOL_ITERS):
            response = self._client.models.generate_content(
                model=self.model_name, contents=contents, config=config
            )
            self._record_usage(response)
            parts = response.candidates[0].content.parts or []
            calls = [p.function_call for p in parts if getattr(p, "function_call", None)]

            if self.tools is not None and calls:
                contents.append(response.candidates[0].content)  # model's call turn
                for fc in calls:
                    args = dict(fc.args) if fc.args else {}
                    result = self.tools.execute(fc.name, args, self.world)
                    self.last_tool_calls.append(
                        {"name": fc.name, "args": args, "result": result}
                    )
                    contents.append(
                        types.Content(
                            role="tool",
                            parts=[types.Part.from_function_response(
                                name=fc.name, response={"result": result})],
                        )
                    )
                continue

            return (response.text or "").strip()

        return "(stopped after too many tool calls)"
