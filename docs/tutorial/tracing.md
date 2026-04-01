# Tracing & Debugging

Every node execution attempt is recorded as a `TraceEvent`. The trace gives you a complete audit trail — successes, failures, retries, timing, and the actual data that flowed through each step.

## Inspecting a trace

```python
import asyncio
from pydantic import BaseModel
from stroma import StromaRunner


class Input(BaseModel):
    value: int


class Output(BaseModel):
    result: int


runner = StromaRunner.quick()
attempt_count = 0


@runner.node("flaky", input=Input, output=Output)
async def flaky(state: Input) -> dict:
    global attempt_count
    attempt_count += 1
    if attempt_count < 2:
        raise TimeoutError("Temporary failure")
    return {"result": state.value * 2}


async def main():
    result = await runner.run([flaky], Input(value=5))

    for event in result.trace:  # (1)!
        status = "FAILED" if event.failure else "OK"
        print(
            f"  {event.node_id} attempt {event.attempt}: "
            f"{status} ({event.duration_ms}ms)"
        )

asyncio.run(main())
```

1. Iterate over `result.trace` to see every attempt, including retries.

Output:

```
  flaky attempt 1: FAILED (2ms)
  flaky attempt 2: OK (0ms)
```

## Filtering events

```python
# Only failures
for event in result.trace.failures():
    print(f"{event.node_id}: {event.failure_message}")

# Events for a specific node
for event in result.trace.events_for("flaky"):
    print(f"Attempt {event.attempt}: {event.output_state}")
```

## What's in a TraceEvent

Each `TraceEvent` captures:

| Field | Type | Description |
|-------|------|-------------|
| `node_id` | `str` | Which node was executed |
| `run_id` | `str` | The pipeline run ID |
| `attempt` | `int` | Attempt number (1-based) |
| `timestamp_utc` | `datetime` | When the attempt started |
| `input_state` | `dict` | Input data passed to the node |
| `output_state` | `dict | None` | Output data, or `None` on failure |
| `duration_ms` | `int` | Wall-clock duration |
| `failure` | `FailureClass | None` | Failure classification, or `None` on success |
| `failure_message` | `str | None` | Error message, or `None` on success |

## Comparing two runs

Use `diff()` to compare traces across runs. This is useful for regression testing or debugging why a pipeline behaves differently:

```python
# Run the same pipeline twice
result_a = await runner_a.run(nodes, state)
result_b = await runner_b.run(nodes, state)

diffs = result_a.trace.diff(result_b.trace)  # (1)!

if not diffs:
    print("Traces are logically equivalent")
else:
    for d in diffs:
        print(d)
```

1. `diff()` compares node IDs, attempts, inputs, outputs, and failure states. It ignores timestamps and durations since those vary between runs.

## Exporting traces

Serialize the entire trace to JSON for logging, monitoring, or external analysis:

```python
import json

json_str = result.trace.to_json()
events = json.loads(json_str)

print(f"Recorded {len(events)} events")
print(json.dumps(events[0], indent=2))
```

## Replaying events

Use `replay()` to iterate events in recorded order — identical to iterating the trace, but makes the intent explicit:

```python
for event in result.trace.replay():
    print(f"{event.node_id} @ {event.timestamp_utc}")
```

## Recap

- Every node attempt is recorded as a **`TraceEvent`** with full input/output data
- **`result.trace`** is iterable — loop over it to inspect all events
- **`.failures()`** and **`.events_for(node_id)`** filter events
- **`.diff(other_trace)`** compares two runs, ignoring timing
- **`.to_json()`** exports the trace for external systems

**Next: [LangGraph Integration](langgraph.md)** — apply Stroma contracts to existing LangGraph graphs.
