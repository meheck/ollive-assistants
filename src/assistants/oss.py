"""Open-source assistant backed by a Hugging Face model.

Defaults to Qwen2.5-0.5B-Instruct -- the model Ollive recommends for the
Hugging Face Spaces deployment. It is small enough to run on CPU (and the HF
free Space tier) yet instruction-tuned, so it behaves like an assistant rather
than a raw text completer.
"""

from __future__ import annotations

import json
import os
import re

import torch
from transformers import AutoModelForCausalLM, AutoTokenizer

from .base import DEFAULT_SYSTEM_PROMPT, MAX_TOOL_ITERS, Assistant, Message

# Qwen emits tool calls as <tool_call>{"name": ..., "arguments": {...}}</tool_call>.
_TOOL_CALL_RE = re.compile(r"<tool_call>\s*(\{.*?\})\s*</tool_call>", re.DOTALL)


def _parse_qwen_tool_calls(text: str) -> list[dict]:
    """Extract tool calls from a Qwen generation. Returns [] if none/invalid."""
    calls = []
    for match in _TOOL_CALL_RE.findall(text):
        try:
            obj = json.loads(match)
            if isinstance(obj, dict) and "name" in obj:
                calls.append(obj)
        except json.JSONDecodeError:
            continue
    return calls

# Re-exported for callers that import it from here (e.g. the Space app).
__all__ = ["OSSAssistant", "DEFAULT_MODEL", "DEFAULT_SYSTEM_PROMPT"]

DEFAULT_MODEL = "Qwen/Qwen2.5-1.5B-Instruct"


def _select_device() -> str:
    """Pick a generation device.

    We default to CUDA when present, otherwise CPU. We deliberately do *not*
    auto-select Apple MPS: Qwen2.5 on MPS trips a Metal assertion
    (`total bytes of NDArray > 2**32`) during attention, and CPU is both
    reliable and representative of the free Hugging Face Space tier we deploy
    to. Set OSS_DEVICE=mps to override on machines where it works.
    """
    if torch.cuda.is_available():
        return "cuda"
    return "cpu"


class OSSAssistant(Assistant):
    def __init__(
        self,
        model_name: str = DEFAULT_MODEL,
        system_prompt: str = DEFAULT_SYSTEM_PROMPT,
        max_tokens: int = 6000,
        max_new_tokens: int = 512,
        temperature: float = 0.7,
        device: str | None = None,
        tools=None,
        world=None,
        long_term_memory=None,
    ) -> None:
        super().__init__(system_prompt=system_prompt, max_tokens=max_tokens,
                         tools=tools, world=world, long_term_memory=long_term_memory)
        self.model_id = model_name.split("/")[-1].lower()
        self.model_name = model_name
        self.max_new_tokens = max_new_tokens
        self.temperature = temperature
        self.device = device or os.getenv("OSS_DEVICE") or _select_device()
        self._tokenizer = None
        self._model = None

    def _ensure_loaded(self) -> None:
        """Lazy-load weights so importing the module stays cheap."""
        if self._model is not None:
            return
        dtype = torch.float32 if self.device == "cpu" else torch.float16
        self._tokenizer = AutoTokenizer.from_pretrained(self.model_name)
        self._model = AutoModelForCausalLM.from_pretrained(
            self.model_name, dtype=dtype
        ).to(self.device)
        self._model.eval()

    def _generate_once(self, msg_dicts: list[dict], tools_arg) -> str:
        """Render the chat template (optionally with tools) and generate once."""
        prompt = self._tokenizer.apply_chat_template(
            msg_dicts, tools=tools_arg, tokenize=False, add_generation_prompt=True
        )
        inputs = self._tokenizer(prompt, return_tensors="pt").to(self.device)

        do_sample = self.temperature > 0
        with torch.no_grad():
            output = self._model.generate(
                **inputs,
                max_new_tokens=self.max_new_tokens,
                do_sample=do_sample,
                temperature=self.temperature if do_sample else None,
                top_p=0.9 if do_sample else None,
                pad_token_id=self._tokenizer.eos_token_id,
            )
        # Only decode the newly generated tokens, not the echoed prompt.
        new_tokens = output[0][inputs["input_ids"].shape[1] :]
        return self._tokenizer.decode(new_tokens, skip_special_tokens=True).strip()

    def _generate(self, messages: list[Message]) -> str:
        self._ensure_loaded()
        self.last_tool_calls = []
        msg_dicts = [m.as_dict() for m in messages]
        tools_arg = (
            [{"type": "function", "function": s} for s in self.tools.schemas()]
            if self.tools is not None
            else None
        )

        # Native tool loop: generate -> parse <tool_call> blocks -> execute ->
        # feed results back as `tool` messages -> repeat until a plain answer.
        for _ in range(MAX_TOOL_ITERS):
            text = self._generate_once(msg_dicts, tools_arg)
            calls = _parse_qwen_tool_calls(text) if self.tools is not None else []
            if not calls:
                return text.strip()

            msg_dicts.append({
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {"type": "function",
                     "function": {"name": c["name"], "arguments": c.get("arguments", {})}}
                    for c in calls
                ],
            })
            for c in calls:
                args = c.get("arguments", {}) or {}
                result = self.tools.execute(c["name"], args, self.world)
                self.last_tool_calls.append({"name": c["name"], "args": args, "result": result})
                msg_dicts.append({"role": "tool", "name": c["name"], "content": result})

        return "(stopped after too many tool calls)"
