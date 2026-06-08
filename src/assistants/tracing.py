"""Optional *live* tracing: emit OpenTelemetry / OpenInference spans as the agent
runs, so a turn streams to an observability UI (Arize Phoenix) in real time.

This is the production pattern. The JSONL `Tracer` stays the durable, offline,
dependency-free audit record; this module is the live view layered on top, and
the two are linked because the OTel `trace_id` is written into the JSONL.

It is a hard no-op unless an OTLP endpoint is configured (env
`PHOENIX_COLLECTOR_ENDPOINT`, or `configure_tracing(endpoint=...)`). OpenTelemetry
is imported lazily inside `configure_tracing`, so the core package carries no new
dependency when tracing is off -- the `span()`/`set_*()` helpers degrade to
cheap no-ops and the agent runs exactly as before.

    configure_tracing()                  # reads env; True if live tracing is on
    with span("agent.turn", AGENT) as s: # no-op span when off
        set_io(s, input=..., output=...)

Spans follow the OpenInference semantic conventions that Phoenix *and* Langfuse
both speak, so the choice of backend is not baked in here.
"""

from __future__ import annotations

import json
import os
from contextlib import contextmanager

# OpenInference span kinds.
AGENT = "AGENT"
LLM = "LLM"
RETRIEVER = "RETRIEVER"
CHAIN = "CHAIN"
TOOL = "TOOL"

# OpenInference semantic-convention attribute keys (stable strings -> no
# dependency on the semconv package).
_KIND = "openinference.span.kind"
_INPUT = "input.value"
_INPUT_MIME = "input.mime_type"
_OUTPUT = "output.value"
_SESSION = "session.id"
_USER = "user.id"
_METADATA = "metadata"
_LLM_MODEL = "llm.model_name"
_TOK_PROMPT = "llm.token_count.prompt"
_TOK_COMPLETION = "llm.token_count.completion"
_TOK_TOTAL = "llm.token_count.total"
_TOOL_NAME = "tool.name"
_TOOL_PARAMS = "tool.parameters"

# Module-level state; set once by configure_tracing().
_TRACER = None
_PROVIDER = None
_ENDPOINT: str | None = None
_PROJECT: str | None = None
_CONFIGURED = False


# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------


def _normalize_endpoint(endpoint: str) -> str:
    """Phoenix receives OTLP/HTTP traces at `<base>/v1/traces`."""
    endpoint = endpoint.rstrip("/")
    return endpoint if endpoint.endswith("/v1/traces") else f"{endpoint}/v1/traces"


def configure_tracing(endpoint: str | None = None, project: str = "ollive") -> bool:
    """Turn on live tracing to an OTLP collector (Phoenix). Idempotent.

    Endpoint resolution: explicit arg -> `PHOENIX_COLLECTOR_ENDPOINT` ->
    `OTEL_EXPORTER_OTLP_ENDPOINT`. With none set, tracing stays off and this
    returns False (the agent is unaffected). Returns True if live tracing is on.
    """
    global _TRACER, _PROVIDER, _ENDPOINT, _PROJECT, _CONFIGURED
    if _CONFIGURED:
        return _TRACER is not None
    _CONFIGURED = True
    _PROJECT = project

    endpoint = (endpoint or os.getenv("PHOENIX_COLLECTOR_ENDPOINT")
                or os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT"))
    if not endpoint:
        return False

    try:
        from opentelemetry import trace
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor
    except ModuleNotFoundError:
        # Endpoint requested but deps missing: stay off rather than crash the agent.
        print("[tracing] OTLP endpoint set but OpenTelemetry is not installed; "
              "tracing disabled. Install: uv pip install opentelemetry-sdk "
              "opentelemetry-exporter-otlp-proto-http")
        return False

    _ENDPOINT = _normalize_endpoint(endpoint)
    # Phoenix reads the destination project from this resource attribute.
    resource = Resource.create(
        {"service.name": project, "openinference.project.name": project})
    _PROVIDER = TracerProvider(resource=resource)
    _PROVIDER.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(endpoint=_ENDPOINT)))
    trace.set_tracer_provider(_PROVIDER)
    _TRACER = trace.get_tracer("ollive.agent")
    return True


def tracing_enabled() -> bool:
    return _TRACER is not None


def endpoint() -> str | None:
    """The configured OTLP traces endpoint (e.g. for logging annotations against)."""
    return _ENDPOINT


def flush() -> None:
    """Block until buffered spans are exported. Call before logging annotations
    (which reference span ids) or before a short-lived process exits."""
    if _PROVIDER is not None:
        _PROVIDER.force_flush()


# ---------------------------------------------------------------------------
# Span emission -- every helper tolerates a None span (tracing off).
# ---------------------------------------------------------------------------


@contextmanager
def span(name: str, kind: str):
    """Open a span (auto-nested under the current one). Yields the span, or None
    when tracing is off -- callers pass that to the `set_*` helpers unconditionally."""
    if _TRACER is None:
        yield None
        return
    with _TRACER.start_as_current_span(name) as s:
        s.set_attribute(_KIND, kind)
        yield s


def set_io(s, *, input=None, output=None) -> None:
    if s is None:
        return
    if input is not None:
        s.set_attribute(_INPUT, input)
    if output is not None:
        s.set_attribute(_OUTPUT, output)


def set_session(s, *, session_id=None, user_id=None, metadata=None) -> None:
    if s is None:
        return
    if session_id:
        s.set_attribute(_SESSION, session_id)
    if user_id:
        s.set_attribute(_USER, user_id)
    if metadata is not None:
        s.set_attribute(_METADATA, json.dumps(metadata, ensure_ascii=False, default=str))


def set_documents(s, docs) -> None:
    """Attach recalled memories as retrieval documents (RETRIEVER span)."""
    if s is None or not docs:
        return
    for i, doc in enumerate(docs):
        s.set_attribute(f"retrieval.documents.{i}.document.content", str(doc))


def set_llm(s, *, model, messages, output, usage=None) -> None:
    """Populate an LLM span with the real input messages, output, and tokens."""
    if s is None:
        return
    s.set_attribute(_LLM_MODEL, model or "")
    for i, m in enumerate(messages):
        s.set_attribute(f"llm.input_messages.{i}.message.role", m.role)
        s.set_attribute(f"llm.input_messages.{i}.message.content", m.content)
    s.set_attribute("llm.output_messages.0.message.role", "assistant")
    s.set_attribute("llm.output_messages.0.message.content", output)
    # Compact summary value too (drives the list-view input/output columns).
    s.set_attribute(_INPUT, json.dumps([m.as_dict() for m in messages], ensure_ascii=False))
    s.set_attribute(_INPUT_MIME, "application/json")
    s.set_attribute(_OUTPUT, output)
    if usage:
        prompt, completion = usage.get("input_tokens"), usage.get("output_tokens")
        if prompt is not None:
            s.set_attribute(_TOK_PROMPT, int(prompt))
        if completion is not None:
            s.set_attribute(_TOK_COMPLETION, int(completion))
        if prompt is not None and completion is not None:
            s.set_attribute(_TOK_TOTAL, int(prompt) + int(completion))


def emit_tool_spans(tool_calls) -> None:
    """Emit one TOOL span per executed tool call, nested under the current span.

    Created after `_generate` returns (from the recorded telemetry), so timing is
    near-zero but the names, args, results, and `consequential` flag are exact --
    which is what the tool-safety evidence needs.
    """
    if _TRACER is None or not tool_calls:
        return
    for call in tool_calls:
        with _TRACER.start_as_current_span(f"tool.{call.get('name', 'unknown')}") as s:
            s.set_attribute(_KIND, TOOL)
            s.set_attribute(_TOOL_NAME, call.get("name", ""))
            args = call.get("args") or {}
            s.set_attribute(_TOOL_PARAMS, json.dumps(args, ensure_ascii=False, default=str))
            s.set_attribute(_INPUT, json.dumps(args, ensure_ascii=False, default=str))
            s.set_attribute(_OUTPUT, str(call.get("result", "")))
            s.set_attribute(_METADATA,
                            json.dumps({"consequential": call.get("consequential", False)}))


def record_error(s, error) -> None:
    if s is None or not error:
        return
    from opentelemetry.trace import Status, StatusCode
    s.set_status(Status(StatusCode.ERROR, str(error)))


def ids_of(s) -> tuple[str | None, str | None]:
    """(trace_id, span_id) of `s` as hex, or (None, None) when tracing is off.
    Written into the JSONL trace so a stored turn links to its live Phoenix span."""
    if s is None:
        return (None, None)
    ctx = s.get_span_context()
    if not ctx.is_valid:
        return (None, None)
    return (format(ctx.trace_id, "032x"), format(ctx.span_id, "016x"))


# ---------------------------------------------------------------------------
# Eval verdicts -> native Phoenix span annotations (so scores light up the UI).
# ---------------------------------------------------------------------------


def _await_spans(client, span_ids, timeout: float) -> set:
    """Block until `span_ids` are queryable in Phoenix (or `timeout` elapses).

    Phoenix ingests spans asynchronously, so a just-flushed span is not
    immediately present -- and an annotation logged against an absent span is
    silently dropped. Returns the set that did become present."""
    import time

    if _PROJECT is None:
        return set()
    want, present = set(span_ids), set()
    deadline = time.time() + timeout
    while want - present and time.time() < deadline:
        try:
            df = client.spans.get_spans_dataframe(project_name=_PROJECT)
            if "context.span_id" in df:
                present |= set(df["context.span_id"]) & want
        except Exception:  # noqa: BLE001
            pass
        if want - present:
            time.sleep(2)
    return present


def log_span_annotations(items, *, annotation_name: str = "eval",
                         wait_timeout: float = 90.0) -> int:
    """Attach eval verdicts to their turn spans as Phoenix annotations.

    `items`: dicts with `span_id`, `label`, `score`, `explanation`, and optional
    `annotator_kind` ("CODE" for an oracle, "LLM" for a judge). Returns how many
    landed. Waits for the target spans to be ingested first (else Phoenix drops
    the annotation), and uses `sync=True` with the default (empty) identifier so
    Phoenix upserts on `(span_id, name)` -- re-running corrects rather than
    duplicates. Uses the Phoenix REST client (lazy import); a no-op if it is
    unavailable so an eval run never fails on the observability side.
    """
    rows = [it for it in items if it.get("span_id")]
    if not rows:
        return 0
    try:
        from phoenix.client import Client
    except ModuleNotFoundError:
        return 0

    base = (_ENDPOINT or "http://localhost:6006/v1/traces").replace("/v1/traces", "")
    client = Client(base_url=base)
    present = _await_spans(client, {it["span_id"] for it in rows}, wait_timeout)

    logged = 0
    for it in rows:
        if it["span_id"] not in present:
            continue  # span never ingested -> annotation would be dropped
        try:
            client.spans.add_span_annotation(
                span_id=it["span_id"],
                annotation_name=annotation_name,
                annotator_kind=it.get("annotator_kind", "CODE"),
                label=it.get("label"),
                score=it.get("score"),
                explanation=it.get("explanation"),
                sync=True,   # default ('') identifier -> upsert on (span_id, name)
            )
            logged += 1
        except Exception:  # noqa: BLE001 -- observability must not break a run
            continue
    return logged
