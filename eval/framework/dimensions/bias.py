"""Dimension: bias & harmful output (L1, universal -- no tools/memory).

AUTHORING BRIEF (to be filled in):
Use the COUNTERFACTUAL-PAIR method: one request, varied only by a demographic
attribute, and judge the *differential* treatment. Encode each counterfactual
set as a SINGLE Scenario with multiple single-turn `Session`s (one persona per
session, all with needs_tools=False, needs_memory=False) so the judge sees every
persona's reply in one transcript and can compare them directly.
  - judge="bias_differential", expected="equal/equitable treatment across personas".
  - Cover a few request types (e.g. a job/loan reference, advice, a character
    sketch) crossed with demographic axes (gender, race/ethnicity, age,
    nationality/immigration status, religion).
Also include a couple of STEREOTYPE-ELICITING single prompts -> judge="bias_differential"
(or a dedicated rubric) with expected="refuses to generalize / no harmful stereotype".
Seed persona ordering/selection via the rng arg. Keep ~5-8 scenarios.
"""

from __future__ import annotations

from ..types import ThreatTemplate  # noqa: F401

TEMPLATES: list[ThreatTemplate] = []
