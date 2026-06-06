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


@dataclass
class ShortTermMemory:
    """In-session conversational memory: a sliding window over recent turns.

    The system prompt is stored separately and always retained; only the
    user/assistant exchange is windowed. We window by number of *messages*
    (default 16 == 8 turns) which is simple, deterministic, and model-agnostic
    -- a token-budget window is a later refinement (noted in the README).
    """

    system_prompt: str
    max_messages: int = 16
    _history: list[Message] = field(default_factory=list)

    def add_user(self, content: str) -> None:
        self._history.append(Message("user", content))
        self._truncate()

    def add_assistant(self, content: str) -> None:
        self._history.append(Message("assistant", content))
        self._truncate()

    def _truncate(self) -> None:
        if len(self._history) > self.max_messages:
            self._history = self._history[-self.max_messages :]

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
        max_messages: int = 16,
        tools: ToolRegistry | None = None,
        world: WorldState | None = None,
    ) -> None:
        self.memory = ShortTermMemory(system_prompt=system_prompt, max_messages=max_messages)
        #: Optional tool registry. When set, backends run a native
        #: function-calling loop against `self.world`.
        self.tools = tools
        #: Sandbox the tools act on (auto-created when tools are enabled).
        self.world = world if world is not None else (WorldState() if tools else None)
        #: Tool calls made during the most recent turn (for traces/eval).
        self.last_tool_calls: list[dict] = []

    @abstractmethod
    def _generate(self, messages: list[Message]) -> str:
        """Produce a reply given the full (system + history) message list."""

    def chat(self, user_input: str) -> str:
        """Handle one user turn: append, generate, remember, return reply."""
        self.memory.add_user(user_input)
        reply = self._generate(self.memory.render())
        self.memory.add_assistant(reply)
        return reply

    def reset(self) -> None:
        self.memory.reset()
