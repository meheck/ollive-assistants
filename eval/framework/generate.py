"""Scenario generation: a deterministic function of (manifest, library, seed).

    test_set = generate(capability_manifest, threat_library, seed)

Only the manifest is agent-specific, so identical manifests -> identical sets and
similar manifests -> overlapping sets (comparability by construction). Each
template fires only if its precondition holds for the manifest (capability
absent -> that dimension is simply not generated, i.e. N/A -- never a false 0).

Generation is reproducible because the seed is frozen and the *output is frozen*:
`freeze()` serializes the scenario set and content-hashes it into a framework
version id (same trick as the agent's prompt/tools hashes). Even when an LLM
helps author a template's content, that happens once here at authoring time; the
frozen artifact -- not the LLM -- is what every eval run replays.
"""

from __future__ import annotations

import hashlib
import json
import random

from .types import CapabilityManifest, Scenario, ThreatTemplate

#: Bump on a breaking change to generation semantics (not on content tweaks --
#: those change the content hash on their own).
GENERATOR_VERSION = "gen-1.0.0"
DEFAULT_SEED = 42


def _seed_for(seed: int, template_id: str) -> int:
    """A per-template RNG stream that's still a pure function of (seed, id), so
    adding a template doesn't perturb other templates' generated content."""
    h = hashlib.sha1(f"{seed}:{template_id}".encode()).hexdigest()
    return int(h[:8], 16)


def _validate(sc: Scenario) -> None:
    """Fidelity gate: a generated scenario must be well-formed and gradable.
    Malformed scenarios raise loudly rather than being silently scored."""
    assert sc.sessions and all(s.turns for s in sc.sessions), f"{sc.id}: empty sessions/turns"
    assert sc.oracle or sc.judge, f"{sc.id}: no grader (needs an oracle and/or judge)"
    assert sc.expected, f"{sc.id}: missing expected-behavior label"


def generate(
    manifest: CapabilityManifest,
    library: list[ThreatTemplate],
    seed: int = DEFAULT_SEED,
) -> list[Scenario]:
    """Expand every applicable template into concrete, validated scenarios."""
    scenarios: list[Scenario] = []
    for tmpl in sorted(library, key=lambda t: t.id):       # fixed order -> stable ids
        if not tmpl.precondition(manifest):
            continue
        rng = random.Random(_seed_for(seed, tmpl.id))
        for sc in tmpl.expand(manifest, rng):
            _validate(sc)
            scenarios.append(sc)
    return scenarios


# ---------------------------------------------------------------------------
# Freeze + version the generated set (the reproducibility artifact).
# ---------------------------------------------------------------------------


def freeze(scenarios: list[Scenario], seed: int = DEFAULT_SEED) -> dict:
    """Serialize the scenario set and content-hash it into a framework version.

    The returned dict is the auditable artifact: the exact scenarios plus the
    version ids that produced them. Two runs with the same artifact are directly
    comparable; a content change flips `content_hash` automatically.
    """
    payload = [sc.to_dict() for sc in scenarios]
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    content_hash = hashlib.sha1(canonical.encode()).hexdigest()[:8]
    return {
        "framework_version": f"evalkit-1.0.0+{content_hash}",
        "generator_version": GENERATOR_VERSION,
        "seed": seed,
        "n_scenarios": len(scenarios),
        "content_hash": content_hash,
        "scenarios": payload,
    }


def write_frozen(artifact: dict, path: str) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(artifact, f, ensure_ascii=False, indent=2)
