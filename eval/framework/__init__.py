"""Ollive evaluation framework: a versioned evidence-generation system.

Public surface:

    from eval.framework import (
        CapabilityManifest, Scenario, ThreatTemplate, Verdict, RunResult,
        manifest_from_registry, generate, freeze, all_templates,
        ModelHost, run_scenario, grade, JudgeHarness,
    )

See ARCHITECTURE.md ("Evaluation framework") for the design rationale.
"""

from __future__ import annotations

from .generate import GENERATOR_VERSION, freeze, generate, write_frozen
from .judges import JudgeHarness
from .library import all_templates
from .manifest import analyze, manifest_from_registry
from .runner import ModelHost, grade, materialize_world, run_scenario
from .types import (
    CapabilityManifest,
    Fixture,
    OracleSpec,
    RunResult,
    Scenario,
    Session,
    ThreatTemplate,
    ToolSpec,
    Verdict,
)

__all__ = [
    "CapabilityManifest", "Fixture", "OracleSpec", "RunResult", "Scenario",
    "Session", "ThreatTemplate", "ToolSpec", "Verdict",
    "manifest_from_registry", "analyze",
    "generate", "freeze", "write_frozen", "GENERATOR_VERSION",
    "all_templates",
    "ModelHost", "run_scenario", "grade", "materialize_world",
    "JudgeHarness",
]
