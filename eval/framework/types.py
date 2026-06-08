"""The contract for the evaluation framework.

Everything else (generators, runner, judges, the per-dimension threat libraries)
is built on these types. The design follows the project thesis: evaluation
produces *defensible evidence about an agent's risk profile*, so the unit of
evaluation is not a prompt but a frozen, serializable **threat scenario** whose
grader (an oracle and/or a judge) travels with it.

* The only universal, agent-general interface is the **tool schema**
  (name/description/parameters). Whether a tool is *consequential* or *ingests
  untrusted content* is a judgment derived from that schema -- provided as a
  native annotation when the agent author gives one (ours does), otherwise
  inferred by the manifest's LLM analyst. So `CapabilityManifest` carries tool
  schemas, never the agent's private sandbox type.
* A scenario declares an **abstract `Fixture`** (the world state it needs); the
  runner's thin env-adapter materializes that into the concrete agent sandbox
  (our `WorldState`). The templates/manifest never see `WorldState`.
* Graders are referenced by **name + params** (`OracleSpec`, `judge`), not raw
  callables, so a generated scenario set is fully serializable -> freezable ->
  content-hashable. That frozen artifact is what the framework version pins.
* Scenarios are **multi-session/multi-user** capable (`sessions`), so
  cross-session memory threats (poisoning, cross-user leakage) are first-class.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

# ---------------------------------------------------------------------------
# Capability manifest -- agent-general: tool schemas in, judgments derived.
# ---------------------------------------------------------------------------


@dataclass
class ToolSpec:
    """A single tool as the eval framework sees it: just the schema, plus two
    optional risk annotations. `None` means "not annotated -> ask the analyst"."""

    name: str
    description: str
    parameters: dict
    consequential: bool | None = None       # side-effecting? (transfer/email/delete)
    ingests_untrusted: bool | None = None    # pulls in untrusted external content?


@dataclass
class CapabilityManifest:
    """What an agent can do, as a function of its tools + whether it has memory.

    This is the *only* agent-specific input to generation. Two agents with the
    same manifest get the identical scenario set (same seed); similar manifests
    get overlapping sets -- comparability falls out of generation being a
    function of the manifest.
    """

    tools: list[ToolSpec]
    has_memory: bool = False

    def consequential_tools(self) -> list[ToolSpec]:
        return [t for t in self.tools if t.consequential]

    def ingest_tools(self) -> list[ToolSpec]:
        return [t for t in self.tools if t.ingests_untrusted]

    def tool(self, name: str) -> ToolSpec | None:
        return next((t for t in self.tools if t.name == name), None)


# ---------------------------------------------------------------------------
# Fixtures -- abstract sandbox state a scenario needs (adapter -> WorldState).
# ---------------------------------------------------------------------------


@dataclass
class Fixture:
    """Agent-independent description of the world a scenario runs in.

    The runner's env-adapter turns this into the concrete agent sandbox. For our
    agent the mapping is near 1:1 with `WorldState`, but keeping it abstract is
    what lets the templates stay free of any one agent's sandbox type.
    """

    accounts: dict[str, float] = field(default_factory=dict)        # name -> balance
    records: dict[str, str] = field(default_factory=dict)           # id -> contents (may hold secrets)
    search_fixtures: dict[str, str] = field(default_factory=dict)   # query-substr -> injected result
    notes: dict[str, Any] = field(default_factory=dict)             # free metadata for graders

    def to_dict(self) -> dict:
        return {
            "accounts": self.accounts,
            "records": self.records,
            "search_fixtures": self.search_fixtures,
            "notes": self.notes,
        }


# ---------------------------------------------------------------------------
# Scenario -- the frozen, serializable unit of evaluation.
# ---------------------------------------------------------------------------


@dataclass
class Session:
    """One conversation against a fresh assistant. Memory threats use >1 session
    (sharing the long-term store across sessions, with per-session `user_id`)."""

    turns: list[str]
    user_id: str = "eval_user"


@dataclass
class OracleSpec:
    """A deterministic grader referenced by name (+ params) so it serializes."""

    name: str                       # key into oracles.ORACLES
    params: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {"name": self.name, "params": self.params}


@dataclass
class Scenario:
    """A single test case: a (multi-session) interaction plus how to grade it.

    Carries its own grader(s): an `oracle` (code, ground truth from the sandbox)
    and/or a `judge` (LLM rubric, for the subjective part). At least one must be
    set. `expected` is the human-readable ground-truth label baked in at author
    time -- never inferred after the fact.
    """

    id: str
    dimension: str
    template_id: str
    sessions: list[Session]
    expected: str
    fixture: Fixture = field(default_factory=Fixture)
    oracle: OracleSpec | None = None
    judge: str | None = None                  # judge rubric name (key into judges)
    needs_tools: bool = False
    needs_memory: bool = False
    meta: dict = field(default_factory=dict)     # e.g. counterfactual pair id, attack note

    def to_dict(self) -> dict:
        """Canonical, fully-serializable form -- this is what gets frozen and
        content-hashed into the framework version (graders are name refs)."""
        return {
            "id": self.id,
            "dimension": self.dimension,
            "template_id": self.template_id,
            "sessions": [{"turns": s.turns, "user_id": s.user_id} for s in self.sessions],
            "expected": self.expected,
            "fixture": self.fixture.to_dict(),
            "oracle": self.oracle.to_dict() if self.oracle else None,
            "judge": self.judge,
            "needs_tools": self.needs_tools,
            "needs_memory": self.needs_memory,
            "meta": self.meta,
        }


# ---------------------------------------------------------------------------
# Threat template -- agent-independent attack pattern that expands into
# concrete scenarios against a given manifest under a frozen seed.
# ---------------------------------------------------------------------------


@dataclass
class ThreatTemplate:
    """A reusable threat pattern. `precondition` decides whether it fires for an
    agent (capability absent -> dimension N/A, not failed). `expand` binds the
    pattern's slots to *this* agent's tools/entities under `rng` (seeded)."""

    id: str
    dimension: str
    precondition: Callable[[CapabilityManifest], bool]
    expand: Callable[[CapabilityManifest, Any], list[Scenario]]   # (manifest, random.Random)
    description: str = ""


# ---------------------------------------------------------------------------
# Results -- what graders see, and what they return.
# ---------------------------------------------------------------------------


@dataclass
class RunResult:
    """Everything observed from running a scenario against one model. Passed to
    oracles (which inspect `world`/`store_dump`) and judges (which read text)."""

    scenario_id: str
    dimension: str
    template_id: str
    model: str
    transcript: list[dict]              # [{session, user_id, role, content}, ...]
    reply: str                          # final assistant reply (last turn)
    world: Any = None                   # WorldState after the run (oracle ground truth)
    store_dump: list[str] = field(default_factory=list)   # long-term memory contents
    recalled: list[str] = field(default_factory=list)     # memories recalled last turn
    trace_ids: list[str] = field(default_factory=list)    # evidence: the turn traces
    span_ids: list[str] = field(default_factory=list)     # OTel root-span ids (for Phoenix annotations)
    error: str | None = None


@dataclass
class Verdict:
    """A grader's judgment. `passed` is the binary safety call; `score` in [0,1]
    is the graded form (oracle: 0/1; judge: rubric score). `evidence` cites the
    ground truth (action_log slice, store contents, differential, etc.)."""

    passed: bool
    score: float
    rationale: str = ""
    evidence: Any = None
    scored_by: str = ""                 # "oracle:<name>" | "judge:<rubric>"

    def to_dict(self) -> dict:
        return {
            "passed": self.passed,
            "score": self.score,
            "rationale": self.rationale,
            "evidence": self.evidence,
            "scored_by": self.scored_by,
        }
