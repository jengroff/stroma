# Quickstart

Stroma's value is clearest when things go wrong. This page leads with failure — a pipeline that crashes, retries, gets caught at the contract boundary, and resumes from checkpoint — then shows what success looks like.

## Install

```bash
uv add stroma
```

## Define your schemas

```python
from pydantic import BaseModel


class Document(BaseModel):
    text: str


class Summary(BaseModel):
    summary: str
    word_count: int
```

## Build the pipeline

```python
from stroma import StromaRunner

runner = StromaRunner.quick()


@runner.node("summarize", input=Document, output=Summary)
async def summarize(state: Document) -> dict:
    words = state.text.split()
    return {"summary": " ".join(words[:10]) + "...", "word_count": len(words)}


@runner.node("validate", input=Summary, output=Summary)
async def validate(state: Summary) -> dict:
    if state.word_count == 0:
        raise ValueError("Empty summary")
    return state.model_dump()
```

## What happens when things go wrong

### Bad output — caught at the boundary

When a node returns data that doesn't match its output schema, Stroma raises `ContractViolation` immediately at that boundary — classified as **terminal**, so there's no retry. The error surfaces at the node that caused it, not three steps downstream where it would otherwise corrupt state silently.

```python
import asyncio


@runner.node("bad_summarize", input=Document, output=Summary)
async def bad_summarize(state: Document) -> dict:
    return {"wrong_field": "this will be caught"}  # missing summary and word_count


async def main():
    result = await runner.run([bad_summarize], Document(text="hello"))
    print(result.status)  # FAILED

    for event in result.trace.failures():
        print(f"{event.node_id}: {event.failure_message}")
    # summarize (output): summary: Field required; word_count: Field required


asyncio.run(main())
```

### Transient failure — automatic retry

`TimeoutError` is classified as **recoverable**. Stroma retries with jittered backoff, up to the configured limit, without any code from you.

```python
attempt = {"count": 0}


@runner.node("flaky_summarize", input=Document, output=Summary)
async def flaky_summarize(state: Document) -> dict:
    attempt["count"] += 1
    if attempt["count"] < 3:
        raise TimeoutError("upstream API timed out")
    words = state.text.split()
    return {"summary": " ".join(words[:10]) + "...", "word_count": len(words)}


async def main():
    result = await runner.run([flaky_summarize], Document(text="hello world from stroma"))
    print(result.status)       # COMPLETED
    print(attempt["count"])    # 3 — failed twice, succeeded on third attempt


asyncio.run(main())
```

### Crash mid-pipeline — resume from checkpoint

This is the scenario that separates Stroma from a raw execution loop. After each node succeeds, its output is checkpointed. If a later node fails, you resume from where you left off — the completed nodes are skipped entirely, their outputs loaded from the store.

```python
from stroma import (
    AsyncInMemoryStore,
    CheckpointManager,
    ContractRegistry,
    NodeContract,
    RunConfig,
    StromaRunner,
    stroma_node,
)


registry = ContractRegistry()
store = AsyncInMemoryStore()
manager = CheckpointManager(store)

c1 = NodeContract(node_id="summarize", input_schema=Document, output_schema=Summary)
c2 = NodeContract(node_id="validate", input_schema=Summary, output_schema=Summary)
registry.register(c1)
registry.register(c2)

summarize_run_count = {"n": 0}


@stroma_node("summarize", c1)
async def summarize_checkpointed(state: Document) -> dict:
    summarize_run_count["n"] += 1
    words = state.text.split()
    return {"summary": " ".join(words[:10]) + "...", "word_count": len(words)}


@stroma_node("validate", c2)
async def validate_failing(state: Summary) -> dict:
    raise RuntimeError("downstream service down")


@stroma_node("validate", c2)
async def validate_fixed(state: Summary) -> dict:
    return state.model_dump()


async def main():
    # First run — summarize succeeds and is checkpointed, validate crashes
    config1 = RunConfig(run_id="qs-run-1")
    runner1 = StromaRunner(registry, manager, config1)
    result1 = await runner1.run(
        [summarize_checkpointed, validate_failing],
        Document(text="Stroma adds reliability to async agent pipelines"),
    )
    print(result1.status)              # FAILED
    print(summarize_run_count["n"])    # 1

    # Resume — summarize is skipped, its checkpoint is loaded
    config2 = RunConfig(run_id="qs-run-1", resume_from="validate")
    runner2 = StromaRunner(registry, manager, config2)
    result2 = await runner2.run(
        [summarize_checkpointed, validate_fixed],
        Document(text="Stroma adds reliability to async agent pipelines"),
    )
    print(result2.status)              # RESUMED
    print(result2.final_state)         # summary='Stroma adds reliability to async...' word_count=7
    print(summarize_run_count["n"])    # still 1 — never ran again

    # Diff the two traces to see exactly what changed
    diffs = result1.trace.diff(result2.trace)
    for d in diffs:
        print(d)


asyncio.run(main())
```

## When everything works

```python
async def main():
    result = await runner.run(
        [summarize, validate],
        Document(text="Stroma adds reliability to async agent pipelines"),
    )
    print(result.status)       # COMPLETED
    print(result.final_state)  # summary='Stroma adds reliability to async...' word_count=7

asyncio.run(main())
```

## Next steps

- **[Tutorial](tutorial/index.md)** — Step-by-step walkthrough of every feature.
- **[Concepts](concepts.md)** — Architecture and design decisions.
- **[Stroma vs. LangGraph](vs-langgraph.md)** — Where the two tools fit together.
- **[Extending Stroma](extending.md)** — Custom backends, classifiers, and OTel integration.
