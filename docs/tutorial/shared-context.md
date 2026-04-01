# Shared Context

Nodes often need access to shared resources — HTTP clients, database connections, API keys, caches, or configuration. Without a sharing mechanism, you'd resort to module-level globals, which make testing painful and concurrency unsafe.

Stroma provides a `context` dict on `RunConfig` that is passed to any node that accepts a second parameter.

## Passing context to nodes

```python
import asyncio
import httpx
from pydantic import BaseModel
from stroma import StromaRunner


class Url(BaseModel):
    url: str


class Page(BaseModel):
    body: str


runner = StromaRunner.quick()


@runner.node("fetch", input=Url, output=Page)
async def fetch(state: Url, ctx: dict) -> dict:  # (1)!
    client = ctx["http"]
    resp = await client.get(state.url)
    return {"body": resp.text}


async def main():
    async with httpx.AsyncClient() as client:
        runner.config.context = {"http": client}  # (2)!
        result = await runner.run([fetch], Url(url="https://example.com"))
        print(len(result.final_state.body))

asyncio.run(main())
```

1. Add a second parameter (any name) to receive the context dict. Stroma detects this automatically via `inspect.signature`.
2. Set the context before calling `run()`. The same dict is passed by reference to every node.

## Context detection

Stroma checks the number of parameters on each node function:

| Parameters | Behavior |
|-----------|----------|
| 1 (`state`) | No context passed — backwards compatible |
| 2+ (`state, ctx, ...`) | Context dict passed as the second argument |

Existing single-parameter nodes continue to work even when context is set on the config — they just don't receive it.

## Mutations persist across nodes

The context dict is passed by reference. Mutations in one node are visible in subsequent nodes:

```python
@runner.node("step1", input=Input, output=Intermediate)
async def step1(state: Input, ctx: dict) -> dict:
    ctx["step1_complete"] = True  # (1)!
    return {"value": state.value + 1}


@runner.node("step2", input=Intermediate, output=Output)
async def step2(state: Intermediate, ctx: dict) -> dict:
    assert ctx["step1_complete"] is True  # (2)!
    return {"result": state.value * 2}
```

1. Node writes to the context dict.
2. The next node sees the mutation.

This is useful for accumulating metadata, passing intermediate state that doesn't fit the pipeline's schema, or flagging conditions for downstream nodes.

## Common patterns

### Injecting an API client

```python
config = RunConfig(context={"openai": openai_client, "model": "gpt-4o"})
```

### Feature flags

```python
config = RunConfig(context={"enable_summarization": True, "max_tokens": 500})
```

### Accumulating metrics

```python
config = RunConfig(context={"node_timings": {}})

@runner.node("slow_step", input=In, output=Out)
async def slow_step(state: In, ctx: dict) -> dict:
    start = time.monotonic()
    result = await expensive_call(state)
    ctx["node_timings"]["slow_step"] = time.monotonic() - start
    return result
```

## Recap

- **`RunConfig.context`** is a plain `dict[str, Any]` passed to nodes by reference
- Nodes with **two or more parameters** receive context automatically
- Nodes with **one parameter** are unaffected — full backwards compatibility
- Mutations in one node are **visible in subsequent nodes**
- Use context for HTTP clients, config, feature flags, or accumulated metadata

**Next: [Parallel Execution](parallel.md)** — run independent nodes concurrently.
