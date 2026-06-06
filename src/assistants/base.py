"""Shared contract for all assistant backends.

Both the OSS and frontier assistants implement `Assistant` so the chat UI and
the eval harness can treat them interchangeably. Keeping the message format and
short-term memory here (rather than in each backend) guarantees the two
assistants get an identical context-construction policy -- which is what makes
the head-to-head comparison fair.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Literal

from .tools import ToolRegistry, WorldState

#: Max generate -> tool-call -> generate cycles within a single turn.
MAX_TOOL_ITERS = 5

Role = Literal["system", "user", "assistant"]

#: Shared assistant persona. Both backends use this identical prompt so the
#: OSS-vs-frontier comparison isolates the model, not the prompt.
DEFAULT_SYSTEM_PROMPT = (
    "You are a helpful, concise personal assistant. "
    "Answer clearly. If you are unsure or do not know something, say so plainly "
    "rather than guessing."
)


@dataclass
class Message:
    role: Role
    content: str

    def as_dict(self) -> dict[str, str]:
        """Shape expected by chat templates and the Anthropic/OpenAI APIs."""
        return {"role": self.role, "content": self.content}


def _estimate_tokens(text: str) -> int:
    """Cheap, model-agnostic token estimate (~4 chars/token + per-message overhead).

    Good enough for windowing decisions without importing any tokenizer into the
    shared base; both models have large context windows so exact counts aren't
    needed here.
    """
    return len(text) // 4 + 4


@dataclass
class ShortTermMemory:
    """In-session conversational memory: a sliding window over recent turns.

    We window by an approximate *token budget* (like a real chatbot) rather than
    a fixed message count: keep the most recent turns that fit in `max_tokens`,
    dropping the oldest when over budget. The system prompt is stored separately
    and always retained; only the user/assistant exchange is windowed.
    """

    system_prompt: str
    max_tokens: int = 6000
    _history: list[Message] = field(default_factory=list)

    def add_user(self, content: str) -> None:
        self._history.append(Message("user", content))
        self._truncate()

    def add_assistant(self, content: str) -> None:
        self._history.append(Message("assistant", content))
        self._truncate()

    def _truncate(self) -> None:
        # Drop oldest messages until the history fits the token budget. Always
        # keep at least the most recent message.
        total = sum(_estimate_tokens(m.content) for m in self._history)
        while len(self._history) > 1 and total > self.max_tokens:
            total -= _estimate_tokens(self._history.pop(0).content)

    def render(self) -> list[Message]:
        """Full message list (system + windowed history) for a model call."""
        return [Message("system", self.system_prompt), *self._history]

    def as_dicts(self) -> list[dict[str, str]]:
        return [m.as_dict() for m in self.render()]

    def reset(self) -> None:
        self._history.clear()


class Assistant(ABC):
    """A multi-turn personal assistant with short-term memory.

    Subclasses only implement `_generate`, which maps a full message list to a
    reply string. Memory bookkeeping lives here so every backend behaves the
    same way.
    """

    #: Stable identifier used in traces/eval reports (e.g. "qwen2.5-0.5b").
    model_id: str

    def __init__(
        self,
        system_prompt: str,
        max_tokens: int = 6000,
        tools: ToolRegistry | None = None,
        world: WorldState | None = None,
        long_term_memory=None,
    ) -> None:
        self.memory = ShortTermMemory(system_prompt=system_prompt, max_tokens=max_tokens)
        #: Optional tool registry. When set, backends run a native
        #: function-calling loop against `self.world`.
        self.tools = tools
        #: Sandbox the tools act on (auto-created when tools are enabled).
        self.world = world if world is not None else (WorldState() if tools else None)
        #: Optional cross-session memory (duck-typed: .retrieve(query)/.store(msg)).
        #: Kept generic so base.py never imports the Mem0 dependency.
        self.ltm = long_term_memory
        #: Tool calls / recalled memories from the most recent turn (for traces).
        self.last_tool_calls: list[dict] = []
        self.last_recalled: list[str] = []

    @abstractmethod
    def _generate(self, messages: list[Message]) -> str:
        """Produce a reply given the full (system + history) message list."""

    def chat(self, user_input: str) -> str:
        """Handle one user turn: recall, generate, remember, return reply.

        If cross-session memory is attached, relevant memories are recalled and
        prepended to the current user message (for THIS call only -- the stored
        history keeps the original), then the turn is persisted afterward.
        """
        self.memory.add_user(user_input)
        messages = self.memory.render()

        self.last_recalled = []
        if self.ltm is not None:
            recalled = self.ltm.retrieve(user_input)
            if recalled:
                self.last_recalled = recalled
                note = "Things you remember about the user:\n" + "\n".join(
                    f"- {r}" for r in recalled
                )
                last = messages[-1]
                messages = messages[:-1] + [Message(last.role, f"{note}\n\n{last.content}")]

        reply = self._generate(messages)
        self.memory.add_assistant(reply)
        if self.ltm is not None:
            self.ltm.store(user_input)
        return reply

    def reset(self) -> None:
        self.memory.reset()
