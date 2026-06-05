"""Open-source assistant backed by a Hugging Face model.

Defaults to Qwen2.5-0.5B-Instruct -- the model Ollive recommends for the
Hugging Face Spaces deployment. It is small enough to run on CPU (and the HF
free Space tier) yet instruction-tuned, so it behaves like an assistant rather
than a raw text completer.
"""

from __future__ import annotations

import os

import torch
from transformers import AutoModelForCausalLM, AutoTokenizer

from .base import Assistant, Message

DEFAULT_MODEL = "Qwen/Qwen2.5-0.5B-Instruct"

DEFAULT_SYSTEM_PROMPT = (
    "You are a helpful, concise personal assistant. "
    "Answer clearly. If you are unsure or do not know something, say so plainly "
    "rather than guessing."
)


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
        max_messages: int = 16,
        max_new_tokens: int = 512,
        temperature: float = 0.7,
        device: str | None = None,
    ) -> None:
        super().__init__(system_prompt=system_prompt, max_messages=max_messages)
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

    def _generate(self, messages: list[Message]) -> str:
        self._ensure_loaded()
        prompt = self._tokenizer.apply_chat_template(
            [m.as_dict() for m in messages],
            tokenize=False,
            add_generation_prompt=True,
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
