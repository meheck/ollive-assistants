"""Version pinning for traces and eval reports.

The four versions are deliberately independent (see ARCHITECTURE.md): the
*agent* (the deployed product configuration) is a different thing from the
*prompt*, the *model*, and the *tools*. Pinning all four on every trace is what
lets a past turn be reconstructed and attributed -- "which configuration
produced this behavior?" -- which is the whole point of observability-as-evidence.
"""

from __future__ import annotations

import hashlib

#: Bump when the deployed assistant configuration changes in a meaningful way.
AGENT_VERSION = "ollive-agent-1.0.0"

#: Bump when the tool set / schemas change.
TOOL_REGISTRY_VERSION = "tools-1.0.0"


def prompt_version(system_prompt: str) -> str:
    """Stable short id derived from the system prompt text."""
    return "prompt-" + hashlib.sha1(system_prompt.encode("utf-8")).hexdigest()[:8]
