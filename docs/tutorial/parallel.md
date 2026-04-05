# Parallel Execution

Real agent pipelines often have independent nodes that can run simultaneously — parallel retrieval, concurrent scoring, map-reduce patterns. The `parallel()` primitive lets you fan out to multiple nodes and merge their results.

## Basic usage

Wrap independent nodes with `parallel()` and place the result in your node sequence:

```python
import asyncio
from pydantic import BaseModel
from stroma import StromaRunner, stroma_node, NodeContract
from stroma.runner import parallel


class Input(BaseModel):
    text: str


class Sentiment(BaseModel):
    score: float


class Keywords(BaseModel):
    words: list[str]


class Analysis(BaseModel):
    score: float
    words: list[str]


runner = StromaRunner.quick()

sentiment_contract = NodeContract(node_id="sentiment", input_schema=Input, output_schema=Sentiment)
keywords_contract = NodeContract(node_id="keywords", input_schema=Input, output_schema=Keywords)
runner.registry.register(sentiment_contract)
runner.registry.register(keywords_contract)


@stroma_node("sentiment", sentiment_contract)
async def sentiment(state: Input) -> dict:
    return {"score": 0.85}


@stroma_node("keywords", keywords_contract)
async def keywords(state: Input) -> dict:
    return {"words": ["python", "async", "reliability"]}


async def main():
    result = await runner.run(
        [parallel(sentiment, keywords)],  # (1)!
        Input(text="Stroma makes pipelines reliable"),
    )
    print(result.status)              # COMPLETED
    print(result.final_state.score)   # 0.85
    print(result.final_state.words)   # ['python', 'async', 'reliability']

asyncio.run(main())
```

1. `parallel(sentiment, keywords)` creates a pseudo-node that runs both concurrently with `asyncio.gather`, then merges their output dicts.

## How merging works

Each child node returns a dict. The outputs are merged into a single dict with **last-write-wins** on key conflicts:

```python
# node_a returns {"x": 1, "shared": "a"}
# node_b returns {"y": 2, "shared": "b"}
# merged result: {"x": 1, "y": 2, "shared": "b"}
```

!!! warning
    If child nodes produce overlapping keys, the last one (in argument order) wins. Design your schemas to avoid conflicts, or use distinct field names.

## Mixing sequential and parallel

`parallel()` returns a pseudo-node, so you can mix it freely in a sequence:

```python
result = await runner.run(
    [preprocess, parallel(node_a, node_b, node_c), postprocess],
    initial_state,
)
```

The execution flow is:

1. `preprocess` runs (sequential)
2. `node_a`, `node_b`, `node_c` run concurrently
3. Their outputs merge into a single state
4. `postprocess` runs (sequential) with the merged state

## Error handling and retries

If any child node raises an exception, the remaining tasks are cancelled and the exception propagates to the runner's failure handling. Parallel nodes use the same retry path as sequential nodes — transient failures are retried with jittered backoff according to the configured policy. If retries are exhausted, the pipeline records `PARTIAL` status:

```python
@stroma_node("failing", contract)
async def failing(state: Input) -> dict:
    raise RuntimeError("something broke")

result = await runner.run(
    [parallel(good_node, failing)],
    state,
)
assert result.status == RunStatus.PARTIAL  # (1)!
```

1. `RuntimeError` is classified as `AMBIGUOUS` (1 retry by default). After exhausting retries, the status is `PARTIAL`, not `FAILED`. Terminal failures like `ContractViolation` still produce `FAILED` immediately.

## Context support

Parallel child nodes that accept a context parameter receive it just like sequential nodes:

```python
@stroma_node("fetch_a", contract)
async def fetch_a(state: Input, ctx: dict) -> dict:
    resp = await ctx["http"].get("https://api-a.example.com")
    return {"a_data": resp.json()}
```

## Tracing

Parallel execution is recorded as a single trace event with a node ID like `parallel(sentiment, keywords)`. Individual child nodes don't produce separate trace events — they run inside the pseudo-node.

## Standalone usage

`parallel()` can be called without the runner for testing:

```python
merged = await parallel(node_a, node_b)(state)
# merged is a plain dict
```

## Recap

- **`parallel(node_a, node_b, ...)`** runs nodes concurrently with `asyncio.gather`
- Child outputs are **merged** into a single dict (last-write-wins on key conflicts)
- Mix **sequential and parallel** freely: `[seq, parallel(a, b), seq]`
- **Retries** work the same as sequential nodes — transient failures are retried with backoff
- **Failures propagate** — terminal exceptions fail immediately; exhausted retries produce `PARTIAL`
- **Context** is passed through to children that accept it
- One **trace event** per parallel pseudo-node

**That's the end of the tutorial!** For deeper dives, check out the [Concepts guide](../concepts.md) and the [API Reference](../api/runner.md).
