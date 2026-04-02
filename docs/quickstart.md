# Quickstart

A complete pipeline in 5 minutes — contracts, retries, checkpoint/resume, and trace inspection.

## Define your schemas

```python
from pydantic import BaseModel


class RawText(BaseModel):
    text: str


class Summary(BaseModel):
    summary: str
    word_count: int
```

## Build the pipeline

```python
from stroma import StromaRunner

runner = StromaRunner.quick()


@runner.node("summarize", input=RawText, output=Summary)
async def summarize(state: RawText) -> dict:
    words = state.text.split()
    return {"summary": " ".join(words[:10]) + "...", "word_count": len(words)}


@runner.node("validate", input=Summary, output=Summary)
async def validate(state: Summary) -> dict:
    if state.word_count == 0:
        raise ValueError("Empty summary")
    return state.model_dump()
```

## Run it

```python
import asyncio

async def main():
    result = await runner.run(
        [summarize, validate],
        RawText(text="Stroma adds reliability to async agent pipelines"),
    )
    print(result.status)       # COMPLETED
    print(result.final_state)  # summary='Stroma adds reliability to async agent pipelines...' word_count=7

asyncio.run(main())
```

## See what happens when things fail

### Contract violation — terminal failure

If a node returns data that doesn't match the output schema, Stroma raises a `ContractViolation` immediately. This is classified as **terminal** — no retries, because the bug is in the node logic, not a transient issue.

```python
@runner.node("bad_node", input=RawText, output=Summary)
async def bad_node(state: RawText) -> dict:
    return {"wrong_field": "oops"}  # missing 'summary' and 'word_count'

result = await runner.run([bad_node], RawText(text="hello"))
print(result.status)  # FAILED
print(result.trace.failures())
# ContractViolation — terminal, no retry
```

### Transient error — automatic retry

Transient failures like `TimeoutError` are classified as **recoverable**. Stroma retries with jittered backoff, up to the configured limit.

```python
attempt = {"count": 0}

@runner.node("flaky", input=RawText, output=Summary)
async def flaky(state: RawText) -> dict:
    attempt["count"] += 1
    if attempt["count"] < 3:
        raise TimeoutError("API timed out")
    return {"summary": state.text[:20], "word_count": len(state.text.split())}

result = await runner.run([flaky], RawText(text="hello world"))
print(result.status)          # COMPLETED
print(attempt["count"])       # 3 (failed twice, succeeded on third try)
```

### Crash recovery — checkpoint and resume

After each node succeeds, Stroma checkpoints the output. If a later node fails, you can resume from the checkpoint instead of re-running everything.

```python
from stroma import RunConfig

# First run — node1 succeeds, node2 fails
config1 = RunConfig(run_id="run-42")
result = await runner.run([summarize, failing_node], RawText(text="..."))
# result.status == FAILED, but summarize's output is checkpointed

# Resume from node2 — summarize is skipped, its output is loaded from checkpoint
config2 = RunConfig(run_id="run-42", resume_from="failing_node")
runner2 = StromaRunner(runner.registry, runner.checkpoint_manager, config2)
result = await runner2.run([summarize, fixed_node], RawText(text="..."))
# result.status == RESUMED
```

## Inspect the trace

Every node attempt is recorded — successes, failures, retries, timing, and state.

```python
result = await runner.run([summarize, validate], RawText(text="hello world"))

for event in result.trace:
    print(f"{event.node_id} attempt={event.attempt} duration={event.duration_ms}ms")
    if event.failure:
        print(f"  FAILED: {event.failure} — {event.failure_message}")

# Export the full trace as JSON
import json
print(json.dumps(result.trace.to_json(), indent=2))
```

## Next steps

- **[Tutorial](tutorial/index.md)** — Step-by-step walkthrough of every feature.
- **[Concepts](concepts.md)** — Architecture and design decisions.
- **[Extending Stroma](extending.md)** — Custom backends, classifiers, and OTel integration.
