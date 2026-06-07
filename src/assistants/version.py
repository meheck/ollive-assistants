"""Version pinning for traces and eval reports.

The four versions are deliberately independent (see ARCHITECTURE.md): the
*agent* (the deployed product configuration) is a different thing from the
*prompt*, the *model*, and the *tools*. Pinning all four on every trace is what
lets a past turn be reconstructed and attributed -- "which configuration
produced this behavior?" -- which is the whole point of observability-as-evidence.
"""

from __future__ import annotations

import hashlib
import json

#: Bump when the deployed assistant configuration changes in a meaningful way.
AGENT_VERSION = "ollive-agent-1.0.0"

#: Human-readable label for the tool set. The actual version id appended to
#: traces also carries a content hash (see `tools_version`), so it can't silently
#: drift if the schemas change but nobody bumps this label.
TOOL_REGISTRY_VERSION = "tools-1.0.0"


def prompt_version(system_prompt: str) -> str:
    """Stable short id derived from the system prompt text.

    A *content fingerprint*: changes iff the prompt text changes. It is one-way,
    so the trace also records the prompt text in the run manifest (see the
    Tracer) to make the id dereferenceable.
    """
    return "prompt-" + hashlib.sha1(system_prompt.encode("utf-8")).hexdigest()[:8]


def tools_version(schemas: list[dict]) -> str:
    """Content-hashed tool-registry id, e.g. `tools-1.0.0+ab12cd34`.

    Unlike a hand-bumped constant, this is derived from the actual tool schemas,
    so the id changes automatically whenever any tool's name/description/params
    change -- it cannot drift from reality. Schemas are sorted by name and dumped
    canonically so the hash is order-independent. Like the prompt id it is a
    fingerprint, so the full schemas are also recorded in the run manifest.
    """
    canonical = json.dumps(
        sorted(schemas, key=lambda s: s["name"]), sort_keys=True, separators=(",", ":")
    )
    digest = hashlib.sha1(canonical.encode("utf-8")).hexdigest()[:8]
    return f"{TOOL_REGISTRY_VERSION}+{digest}"
