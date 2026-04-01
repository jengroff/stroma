# Extending Stroma

Stroma exposes four extension points. Each is a protocol, callable, dataclass, or
plain dict — no subclassing, no registration ceremony.

| Extension point | What it controls |
|----------------|-----------------|
| `AsyncCheckpointStore` | Where pipeline state is persisted |
| `Classifier` | How exceptions are categorized for retry |
| `NodeHooks` | Observability callbacks at node boundaries |
| `context` dict | Shared resources across nodes in a run |

The [tutorial](tutorial/hooks.md) covers basic usage of hooks and context.
This page focuses on **implementation** — writing backends, composing classifiers,
building a full OTel integration, and wiring everything together.

---

## Custom checkpoint backends

Implement `AsyncCheckpointStore` to persist pipeline state anywhere — Postgres,
S3, DynamoDB, or your own system. Stroma uses structural typing: no base class,
just implement `save`, `load`, and `delete` as async methods.

```python
from pydantic import BaseModel


class PostgresStore:
    def __init__(self, dsn: str) -> None:
        self._dsn = dsn

    async def save(self, run_id: str, node_id: str, state: BaseModel) -> None:
        import asyncpg
        async with await asyncpg.connect(self._dsn) as conn:
            await conn.execute(
                """
                INSERT INTO checkpoints (run_id, node_id, state, schema_ref)
                VALUES ($1, $2, $3, $4)
                ON CONFLICT (run_id, node_id) DO UPDATE SET state = EXCLUDED.state
                """,
                run_id,
                node_id,
                state.model_dump_json(),
                f"{type(state).__module__}:{type(state).__qualname__}",
            )

    async def load(self, run_id: str, node_id: str) -> BaseModel | None:
        import asyncpg, importlib
        async with await asyncpg.connect(self._dsn) as conn:
            row = await conn.fetchrow(
                "SELECT state, schema_ref FROM checkpoints WHERE run_id=$1 AND node_id=$2",
                run_id, node_id,
            )
        if row is None:
            return None
        module_name, qualname = row["schema_ref"].split(":", 1)
        schema = getattr(importlib.import_module(module_name), qualname)
        return schema.model_validate_json(row["state"])

    async def delete(self, run_id: str) -> None:
        import asyncpg
        async with await asyncpg.connect(self._dsn) as conn:
            await conn.execute("DELETE FROM checkpoints WHERE run_id=$1", run_id)
```

Wire it in via `CheckpointManager`:

```python
from stroma import CheckpointManager, StromaRunner

store = PostgresStore("postgresql://localhost/mydb")
manager = CheckpointManager(store)
runner = StromaRunner(registry, manager, config)
```

!!! tip "Schema round-tripping"
    Stroma stores a `module:qualname` reference alongside the JSON so it can
    deserialize without knowing the schema at load time. Your custom backend
    should do the same — the `_schema_ref` and `_resolve_schema` helpers in
    `stroma.checkpoint` are available for reuse.

---

## Custom failure classifiers

`Classifier` is the primary extension point for error handling:

```python
Classifier = Callable[[Exception, NodeContext], FailureClass | None]
```

Return a `FailureClass` to handle the exception, or `None` to defer to the next
classifier. Built-in rules apply last. Write focused, single-responsibility
classifiers and compose them:

```python
from stroma import Classifier, FailureClass, NodeContext


def openai_classifier(exc: Exception, ctx: NodeContext) -> FailureClass | None:
    msg = str(exc).lower()
    if "rate_limit_exceeded" in msg or "429" in msg:
        return FailureClass.RECOVERABLE
    if "invalid_api_key" in msg or "401" in msg:
        return FailureClass.TERMINAL
    if "500" in msg or "service_unavailable" in msg:
        return FailureClass.RECOVERABLE
    return None


def anthropic_classifier(exc: Exception, ctx: NodeContext) -> FailureClass | None:
    msg = str(exc).lower()
    if "overloaded" in msg:
        return FailureClass.RECOVERABLE
    if "permission_error" in msg:
        return FailureClass.TERMINAL
    return None


def escalate_on_repeat(exc: Exception, ctx: NodeContext) -> FailureClass | None:
    # After 3 timeouts on the same node, give up
    if isinstance(exc, TimeoutError) and ctx.attempt >= 3:
        return FailureClass.TERMINAL
    return None


runner = (
    StromaRunner.quick()
    .with_classifiers([escalate_on_repeat, openai_classifier, anthropic_classifier])
)
```

Classifiers run in list order. The first non-`None` result wins — so put
more specific classifiers (like `escalate_on_repeat`) before broader ones.

!!! tip "`ctx` carries attempt and node identity"
    `NodeContext.attempt` is 1-based. `NodeContext.node_id` lets you apply
    different logic to different nodes inside a single classifier if needed.

---

## Full OpenTelemetry integration

The hooks tutorial covers basic hook usage. Here's a complete OTel span lifecycle
that opens a span in `on_node_start` and closes it in `on_node_success` or
`on_node_failure`:

```python
from opentelemetry import trace
from opentelemetry.trace import StatusCode
from stroma import FailureClass
from stroma.runner import NodeHooks

tracer = trace.get_tracer("stroma")

# Span storage keyed by (run_id, node_id)
_active_spans: dict[tuple[str, str], trace.Span] = {}


async def otel_start(run_id: str, node_id: str, input_state: dict) -> None:
    span = tracer.start_span(
        f"stroma.node.{node_id}",
        attributes={
            "stroma.run_id": run_id,
            "stroma.node_id": node_id,
        },
    )
    _active_spans[(run_id, node_id)] = span


async def otel_success(run_id: str, node_id: str, output_state: dict, tokens: int) -> None:
    span = _active_spans.pop((run_id, node_id), None)
    if span is None:
        return
    span.set_attribute("stroma.tokens_used", tokens)
    span.set_status(StatusCode.OK)
    span.end()


async def otel_failure(run_id: str, node_id: str, exc: Exception, failure_class: FailureClass) -> None:
    span = _active_spans.pop((run_id, node_id), None)
    if span is None:
        return
    span.record_exception(exc)
    span.set_attribute("stroma.failure_class", str(failure_class))
    span.set_status(StatusCode.ERROR, description=str(exc))
    span.end()


otel_hooks = NodeHooks(
    on_node_start=otel_start,
    on_node_success=otel_success,
    on_node_failure=otel_failure,
)

runner = StromaRunner.quick().with_hooks(otel_hooks)
```

!!! warning "Retries produce multiple spans"
    If a node is retried, `on_node_failure` fires for each failed attempt and
    `on_node_start` fires again before each retry. Each attempt gets its own
    span, which is the correct behavior — you want visibility into every attempt,
    not just the final outcome.

---

## Composing all extension points

A production-ready runner built entirely from the four extension points:

```python
import httpx
from stroma import CheckpointManager, ExecutionBudget, FailureClass, StromaRunner
from stroma.runner import NodeHooks

runner = (
    StromaRunner.quick()
    # Durable checkpointing
    .with_redis("redis://localhost:6379", ttl_seconds=7200)
    # Hard budget limits
    .with_budget(tokens=100_000, cost_usd=2.00, latency_ms=120_000)
    # Provider-specific error handling
    .with_classifiers([escalate_on_repeat, openai_classifier, anthropic_classifier])
    # Full OTel observability
    .with_hooks(otel_hooks)
    # Shared HTTP client and config
    .with_context({
        "http": httpx.AsyncClient(timeout=30.0),
        "model": "gpt-4o",
        "cache": {},
    })
)
```

This is a complete production configuration in nine lines. Every extension point
is optional — compose only what your pipeline needs.
