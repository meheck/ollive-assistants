"""The threat library: aggregates every dimension's templates into one list.

`generate(manifest, all_templates(), seed)` is the whole eval set. Adding a
dimension = adding its module's `TEMPLATES` here.
"""

from __future__ import annotations

from .dimensions import (
    bias,
    content_safety,
    hallucination,
    memory_safety,
    prompt_injection,
    tool_safety,
)
from .types import ThreatTemplate

_MODULES = [
    hallucination,
    bias,
    content_safety,
    tool_safety,
    prompt_injection,
    memory_safety,
]


def all_templates() -> list[ThreatTemplate]:
    templates: list[ThreatTemplate] = []
    for mod in _MODULES:
        templates.extend(getattr(mod, "TEMPLATES", []))
    return templates
