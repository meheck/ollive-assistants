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
    """Append-only JSONL tracer, one file per session.

    Each trace pins version *ids* (e.g. `prompt-72b6303d`, `tools-1.0.0+ab12cd34`)
    that are one-way content hashes. So that those ids are *dereferenceable* --
    "what exact prompt/tool schema produced this trace?" -- the tracer also keeps
    a shared `manifest.json` next to the traces mapping each id to its actual
    content. Without it, observability could only detect drift, not reconstruct
    the configuration; the eval harness needs reconstruction to use a trace as
    evidence.
    """

    trace_dir: str = DEFAULT_TRACE_DIR
    session_id: str = field(default_factory=lambda: uuid.uuid4().hex[:8])

    def __post_init__(self) -> None:
        os.makedirs(self.trace_dir, exist_ok=True)
        self.path = os.path.join(self.trace_dir, f"{self.session_id}.jsonl")
        self.manifest_path = os.path.join(self.trace_dir, "manifest.json")
        #: ids already written this session, so we touch the manifest at most once.
        self._registered: set[str] = set()

    def record(self, trace: dict) -> None:
        with open(self.path, "a", encoding="utf-8") as f:
            f.write(json.dumps(trace, ensure_ascii=False) + "\n")

    def register(self, entries: dict[str, dict]) -> None:
        """Map version-id -> artifact (prompt text, tool schemas) in the manifest.

        Merges into the shared `manifest.json` (read-modify-write) and is
        idempotent: ids are content hashes, so re-registering the same id writes
        the same content. After the first turn of a session this is a no-op.
        """
        fresh = {k: v for k, v in entries.items() if k not in self._registered}
        if not fresh:
            return
        manifest: dict = {}
        if os.path.exists(self.manifest_path):
            try:
                with open(self.manifest_path, encoding="utf-8") as f:
                    manifest = json.load(f)
            except (json.JSONDecodeError, OSError):
                manifest = {}
        manifest.update(fresh)
        with open(self.manifest_path, "w", encoding="utf-8") as f:
            json.dump(manifest, f, ensure_ascii=False, indent=2)
        self._registered.update(fresh)
