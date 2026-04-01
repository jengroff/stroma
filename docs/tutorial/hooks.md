# Observability Hooks

Stroma provides async callbacks at node execution boundaries for plugging in external telemetry — Datadog, Prometheus, OpenTelemetry, Sentry, or any monitoring system.

## The three hooks

| Hook | Fired when | Arguments |
|------|-----------|-----------|
| `on_node_start` | Before the node function runs | `run_id`, `node_id`, `input_state_dict` |
| `on_node_success` | After a node completes and passes validation | `run_id`, `node_id`, `output_state_dict`, `tokens_used` |
| `on_node_failure` | After a node raises an exception | `run_id`, `node_id`, `exc`, `failure_class` |

## Basic usage

```python
import asyncio
from pydantic import BaseModel
from stroma import NodeHooks, RunConfig, StromaRunner


class Input(BaseModel):
    value: int


class Output(BaseModel):
    result: int


events = []


async def on_start(run_id, node_id, input_state):
    events.append(("start", node_id, input_state))


async def on_success(run_id, node_id, output_state, tokens_used):
    events.append(("success", node_id, output_state, tokens_used))


runner = StromaRunner.quick(
    hooks=NodeHooks(
        on_node_start=on_start,
        on_node_success=on_success,
    ),
)


@runner.node("double", input=Input, output=Output)
async def double(state: Input) -> dict:
    return {"result": state.value * 2}


async def main():
    result = await runner.run([double], Input(value=5))
    print(result.status)  # COMPLETED
    print(events)
    # [('start', 'double', {'value': 5}), ('success', 'double', {'result': 10}, 0)]

asyncio.run(main())
```

## Tracking failures

The `on_node_failure` hook receives the exception and its `FailureClass`, so you can route different failure types to different monitoring:

```python
from stroma import FailureClass, NodeHooks


async def on_failure(run_id, node_id, exc, failure_class):
    if failure_class == FailureClass.TERMINAL:
        # Page someone — this won't recover
        await alert_oncall(run_id, node_id, exc)
    else:
        # Just log — the runner will retry
        logger.warning("Node %s failed (class=%s): %s", node_id, failure_class, exc)


config = RunConfig(
    hooks=NodeHooks(on_node_failure=on_failure),
)
```

## Integrating with OpenTelemetry

```python
from opentelemetry import trace

tracer = trace.get_tracer("stroma")


async def otel_start(run_id, node_id, input_state):
    span = tracer.start_span(f"node.{node_id}", attributes={"run_id": run_id})
    # Store the span somewhere accessible to on_success/on_failure


async def otel_success(run_id, node_id, output_state, tokens_used):
    # End the span, record tokens_used as an attribute
    ...


hooks = NodeHooks(on_node_start=otel_start, on_node_success=otel_success)
```

## Design notes

- All hooks are **optional** — `None` by default. No overhead when unused.
- Hook callables must be **async**. Passing a sync function will raise at call time.
- Hooks fire **after** trace recording and **before** the result is returned, so the trace is always complete even if a hook raises.

## Recap

- **`NodeHooks`** provides `on_node_start`, `on_node_success`, and `on_node_failure`
- Pass hooks via `RunConfig(hooks=NodeHooks(...))` or `StromaRunner.quick(hooks=...)`
- Hooks are async, optional, and zero-overhead when unused
- Use them for metrics, alerting, distributed tracing, or any external integration

**Next: [Shared Context](shared-context.md)** — share resources across nodes without globals.
