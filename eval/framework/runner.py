"""Run a `Scenario` against an assistant and grade it.

Responsibilities:

* **Env adapter** -- materialize a scenario's abstract `Fixture` into our concrete
  `WorldState`. This is the one place that knows about `WorldState`; the
  templates and manifest stay agent-independent.
* **Execution** -- run a scenario's sessions in order. Each session is a fresh
  assistant (fresh short-term memory) but shares the scenario's `WorldState` and
  long-term memory store, with a per-session `user_id`. That's what makes
  cross-session memory threats (poisoning across sessions; cross-user leakage)
  expressible and isolated per scenario.
* **Determinism + cost** -- one long-lived `ModelHost` per model reconfigured per
  scenario, so OSS weights load once; evals run at temperature 0.
* **Evidence** -- every turn is traced; the runner collects the `trace_id`s so a
  result row points back at the observability trace (and through its manifest to
  the exact prompt/tool schemas).
* **Grading** -- apply the scenario's oracle (deterministic) and/or judge (LLM).
"""

from __future__ import annotations

import json
import os
import tempfile

from assistants.frontier import FrontierAssistant
from assistants.observability import Tracer
from assistants.tools import WorldState, default_registry

from .oracles import resolve as resolve_oracle
from .types import Fixture, RunResult, Scenario, Verdict

# ---------------------------------------------------------------------------
# Env adapter: abstract Fixture -> concrete WorldState.
# ---------------------------------------------------------------------------


def materialize_world(fixture: Fixture):
    """Build a WorldState for a scenario. Fixture fields, when non-empty,
    *replace* the default seed so a scenario has exact control over its sandbox
    (and its oracle stays unambiguous); empty fields keep the realistic default."""
    world = WorldState()
    if fixture.accounts:
        world.accounts = dict(fixture.accounts)
    if fixture.records:
        world.records = dict(fixture.records)
    if fixture.search_fixtures:
        world.search_fixtures = dict(fixture.search_fixtures)
    return world


# ---------------------------------------------------------------------------
# Model host: one assistant per model, reconfigured per scenario.
# ---------------------------------------------------------------------------


class ModelHost:
    """Holds one assistant instance per backend so weights/clients load once;
    per scenario we swap tools/world/memory/tracer and reset short-term memory."""

    def __init__(self, model: str):
        self.model = model
        self._assistant = self._build()

    def _build(self):
        if self.model == "frontier":
            return FrontierAssistant(temperature=0.0)
        # Lazy: importing the OSS backend pulls torch/transformers (GBs) -- only
        # load it when an OSS run is actually requested.
        from assistants.oss import OSSAssistant
        return OSSAssistant(temperature=0.0)

    def configure(self, *, tools, world, ltm, tracer) -> None:
        a = self._assistant
        a.tools = tools
        a.world = world
        a.ltm = ltm
        a.tracer = tracer
        a.memory.reset()                 # fresh short-term memory for the session
        a.last_tool_calls, a.last_recalled = [], []

    @property
    def assistant(self):
        return self._assistant


# ---------------------------------------------------------------------------
# Run one scenario.
# ---------------------------------------------------------------------------


def run_scenario(host: ModelHost, scenario: Scenario, traces_dir: str) -> RunResult:
    """Execute every session of `scenario` and return a RunResult for grading."""
    registry = default_registry() if scenario.needs_tools else None
    world = materialize_world(scenario.fixture) if scenario.needs_tools else None

    transcript: list[dict] = []
    reply = ""
    recalled: list[str] = []
    store_dump: list[str] = []
    error = None

    # Per-scenario, per-model trace file -> deterministic path we read back.
    safe_id = scenario.id.replace("/", "_")
    tracer = Tracer(trace_dir=traces_dir, session_id=f"{safe_id}.{host.model}")

    # One long-term store dir per scenario (isolation); per-session user_id.
    mem_dir = tempfile.mkdtemp(prefix="evalmem_") if scenario.needs_memory else None

    try:
        for si, session in enumerate(scenario.sessions):
            ltm = None
            if scenario.needs_memory:
                # Lazy: only memory scenarios pull mem0/chromadb.
                from assistants.long_term_memory import LongTermMemory
                ltm = LongTermMemory(persist_dir=mem_dir, user_id=session.user_id)

            host.configure(tools=registry, world=world, ltm=ltm, tracer=tracer)
            a = host.assistant
            for turn in session.turns:
                transcript.append({"session": si, "user_id": session.user_id,
                                   "role": "user", "content": turn})
                reply = a.chat(turn)
                transcript.append({"session": si, "user_id": session.user_id,
                                   "role": "assistant", "content": reply})
            recalled = list(a.last_recalled or [])
            if ltm is not None:                       # dump the LAST session's view
                store_dump = ltm._all_memory_texts()
    except Exception as exc:  # keep the harness alive; record the failure
        error = f"{type(exc).__name__}: {exc}"

    return RunResult(
        scenario_id=scenario.id, dimension=scenario.dimension,
        template_id=scenario.template_id, model=host.model,
        transcript=transcript, reply=reply, world=world,
        store_dump=store_dump, recalled=recalled,
        trace_ids=_read_trace_ids(tracer.path), error=error,
    )


def _read_trace_ids(path: str) -> list[str]:
    if not os.path.exists(path):
        return []
    ids = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            try:
                ids.append(json.loads(line)["trace_id"])
            except (json.JSONDecodeError, KeyError):
                pass
    return ids


# ---------------------------------------------------------------------------
# Grade a RunResult against its scenario's oracle and/or judge.
# ---------------------------------------------------------------------------


def grade(scenario: Scenario, rr: RunResult, judge_fn=None) -> dict:
    """Apply the scenario's grader(s). Returns both verdicts plus an overall
    pass/score (pass = every grader passes; score = mean of grader scores)."""
    verdicts: list[Verdict] = []

    if rr.error:
        return {"verdicts": [], "passed": False, "score": 0.0, "error": rr.error}

    if scenario.oracle is not None:
        verdicts.append(resolve_oracle(scenario.oracle)(rr))

    if scenario.judge is not None and judge_fn is not None:
        verdicts.append(judge_fn(scenario.judge, scenario, rr))

    if not verdicts:
        return {"verdicts": [], "passed": False, "score": 0.0,
                "error": "no grader produced a verdict"}

    passed = all(v.passed for v in verdicts)
    score = sum(v.score for v in verdicts) / len(verdicts)
    return {"verdicts": [v.to_dict() for v in verdicts], "passed": passed, "score": score}
