"""Cross-session long-term memory via Mem0 (self-hosted, no extra inference).

Design choices (see ARCHITECTURE.md "Why memory makes no extra inference calls"):

* `infer=False` -- store turns directly and recall by **embedding similarity**;
  no LLM call is made for memory, so there is zero extra inference cost.
* Local **HuggingFace** embedder + persistent **Chroma** -> fully local, nothing
  leaves the machine, no external account.
* Scoped by `user_id` so memories never cross users.
* **Deterministic PII scrubbing before storage** -- because no LLM mediates what
  gets stored, a rule-based scrubber (not a model) decides; PII is redacted, so
  it never persists.

This module is imported only by the local app / eval harness, never by the
deployed Spaces, so `base.py` stays free of the Mem0 dependency.
"""

from __future__ import annotations

import logging
import os
import re

# Disable Mem0's outbound telemetry (privacy: nothing should phone home).
os.environ.setdefault("MEM0_TELEMETRY", "False")

# We use Mem0 with infer=False + embedding similarity only -- not its optional
# spaCy-based graph/entity features. Quiet the resulting "spaCy not installed"
# warnings so the CLI output stays clean (the feature is genuinely unused).
logging.getLogger("mem0").setLevel(logging.ERROR)

DEFAULT_EMBEDDER = "sentence-transformers/all-MiniLM-L6-v2"

# Deterministic PII patterns -> redaction token. Order matters (SSN before the
# looser card pattern). This is the hard guard; it does not rely on any model.
_PII_PATTERNS: list[tuple[re.Pattern, str]] = [
    (re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b"), "[REDACTED_EMAIL]"),
    (re.compile(r"\b\d{3}-\d{2}-\d{4}\b"), "[REDACTED_SSN]"),
    (re.compile(r"\b(?:\d[ -]?){13,16}\b"), "[REDACTED_CARD]"),
    (re.compile(r"\b(?:\+?\d{1,2}[\s.-]?)?\(?\d{3}\)?[\s.-]?\d{3}[\s.-]?\d{4}\b"), "[REDACTED_PHONE]"),
]


def scrub_pii(text: str) -> tuple[str, bool]:
    """Redact obvious PII. Returns (scrubbed_text, found_any)."""
    found = False
    for pattern, token in _PII_PATTERNS:
        text, n = pattern.subn(token, text)
        found = found or bool(n)
    return text, found


class LongTermMemory:
    """Embedding-based cross-session memory with per-user scoping + PII scrubbing."""

    def __init__(
        self,
        persist_dir: str,
        user_id: str = "default_user",
        model: str = "gemini-2.5-flash",
        api_key: str | None = None,
        embedder_model: str = DEFAULT_EMBEDDER,
        top_k: int = 3,
        threshold: float = 0.25,
    ) -> None:
        from mem0 import Memory  # lazy: keep the import cost out of plain chat

        config = {
            # LLM is required by the config but never called (infer=False).
            "llm": {"provider": "gemini", "config": {
                "model": model, "api_key": api_key or os.getenv("GEMINI_API_KEY")}},
            "embedder": {"provider": "huggingface", "config": {"model": embedder_model}},
            "vector_store": {"provider": "chroma", "config": {
                "collection_name": "ltm", "path": os.path.join(persist_dir, "chroma")}},
        }
        self._mem = Memory.from_config(config)
        self.user_id = user_id
        self.top_k = top_k
        self.threshold = threshold
        #: Cache memory-text -> embedding so we don't re-run the embedder on
        #: every retrieve (the embedder forward pass dwarfs the cosine math).
        self._emb_cache: dict[str, list] = {}

    def _embed_cached(self, text: str):
        emb = self._emb_cache.get(text)
        if emb is None:
            emb = self._mem.embedding_model.embed(text)
            self._emb_cache[text] = emb
        return emb

    def _cosine(self, a, b) -> float:
        import numpy as np

        a, b = np.asarray(a, dtype=float), np.asarray(b, dtype=float)
        denom = (a @ a) ** 0.5 * (b @ b) ** 0.5
        return float(a @ b / denom) if denom else 0.0

    def retrieve(self, query: str) -> list[str]:
        """Return memories relevant to `query`, ranked by real cosine similarity.

        Mem0 + Chroma's vector search is unreliable in this version (it reports a
        degenerate score of 1.0 for everything AND silently drops some matches,
        including exact ones). So we use Mem0 purely as scoped storage: fetch all
        of this user's memories via get_all, then rank/filter ourselves with the
        local embedder and drop anything below `threshold`. Per-user memory is
        small, so scoring all of it locally is cheap and correct.
        """
        allm = self._mem.get_all(filters={"user_id": self.user_id})
        rows = allm.get("results", allm) if isinstance(allm, dict) else allm
        # Dedupe identical memory texts (Mem0 stores duplicates with infer=False).
        candidates = list(dict.fromkeys(r.get("memory") for r in rows if r.get("memory")))
        if not candidates:
            return []

        # Embed the query once; reuse cached embeddings for the stored memories.
        q_emb = self._mem.embedding_model.embed(query)
        scored = [(self._cosine(q_emb, self._embed_cached(m)), m) for m in candidates]
        scored = [(s, m) for s, m in scored if s >= self.threshold]
        scored.sort(reverse=True)
        return [m for _, m in scored[: self.top_k]]

    def store(self, user_message: str) -> None:
        """Persist a (PII-scrubbed) user message as cross-session memory."""
        scrubbed, _ = scrub_pii(user_message)
        if scrubbed.strip():
            self._mem.add(
                [{"role": "user", "content": scrubbed}],
                user_id=self.user_id, infer=False,
            )
