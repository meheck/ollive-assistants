"""Evidence-grade tracing: one version-pinned JSON record per turn.

A `Tracer` writes one JSON line per turn to a JSONL file. Each trace pins the
agent/prompt/model/tool versions and records the timed spans, token usage, tool
calls (with per-call latency), recalled memories, and the reply -- enough to
reconstruct exactly what happened and under which configuration.

It's a deliberately small, self-contained tracer (no external service) so it
runs anywhere; in production these spans would be shipped to an OTEL backend
like Langfuse or Arize Phoenix. The eval harness reuses these traces as the
evidence behind each score.
"""

from __future__ import annotations

import json
import os
import time
import uuid
from dataclasses import dataclass, field

DEFAULT_TRACE_DIR = "results/traces"


@dataclass
class Span:
    """A timed sub-step of a turn."""

    name: str
    ms: float


class Timer:
    """`with Timer() as t: ...` then read `t.ms`."""

    def __enter__(self):
        self._start = time.perf_counter()
        return self

    def __exit__(self, *exc):
        self.ms = round((time.perf_counter() - self._start) * 1000, 1)


@dataclass
class Tracer:
    """Append-only JSONL tracer, one file per session."""

    trace_dir: str = DEFAULT_TRACE_DIR
    session_id: str = field(default_factory=lambda: uuid.uuid4().hex[:8])

    def __post_init__(self) -> None:
        os.makedirs(self.trace_dir, exist_ok=True)
        self.path = os.path.join(self.trace_dir, f"{self.session_id}.jsonl")

    def record(self, trace: dict) -> None:
        with open(self.path, "a", encoding="utf-8") as f:
            f.write(json.dumps(trace, ensure_ascii=False) + "\n")
