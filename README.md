# Stroma

**Framework-agnostic reliability primitives for agent pipelines.**

```python
from pydantic import BaseModel
from stroma import StromaRunner

class Input(BaseModel):
    value: int

class Output(BaseModel):
    result: int

runner = StromaRunner.quick()

@runner.node("double", input=Input, output=Output)
async def double(state: Input) -> dict:
    return {"result": state.value * 2}

result = await runner.run([double], Input(value=5))
print(result.final_state)  # result=10
```

## Install

Requires **Python 3.12+**.

```bash
uv add stroma
```

Optional extras:

```bash
uv add stroma[redis]       # Redis-backed checkpointing
uv add stroma[langgraph]   # LangGraph adapter
uv add stroma[deepagents]  # DeepAgents adapter
```

## What You Get

- **Contracts** — Pydantic-based input/output validation at every node boundary
- **Failure classification** — automatic categorization of errors as recoverable, terminal, or ambiguous
- **Retry policies** — configurable retries with jittered backoff, per failure class or per node
- **Checkpointing** — async-first save and resume across crashes (in-memory or Redis)
- **Cost estimation** — model-aware USD cost tracking via `KNOWN_MODELS` and token/dollar/latency budgets
- **Parallel execution** — fan out work to concurrent nodes with `parallel()` and merged output
- **Node hooks** — async `on_node_start`, `on_node_success`, and `on_node_failure` callbacks
- **Shared context** — pass a mutable `context` dict through `RunConfig` to every node
- **Execution tracing** — full record of every node attempt, with diffing and JSON export
- **Per-run logging** — structured `LoggerAdapter` with `run_id` in every log line
- **Fluent builder API** — configure runners with chained `.with_budget()`, `.with_hooks()`, `.with_redis()`, etc.
- **LangGraph adapter** — apply contracts to existing LangGraph graphs
- **DeepAgents adapter** — contract validation and cost tracking for deepagents graphs
- **Framework-agnostic** — works with any async Python code, no framework lock-in

## Quick Examples

### Cost estimation

Nodes can return token counts and a model name. Stroma computes USD cost automatically from built-in pricing data:

```python
@runner.node("summarize", input=DocInput, output=Summary)
async def summarize(state: DocInput) -> tuple:
    # call your LLM here...
    return ({"text": response}, input_tokens, output_tokens, "gpt-4o")
```

### Parallel execution

Run independent nodes concurrently and merge their outputs:

```python
from stroma import parallel

result = await runner.run(
    [parallel(fetch_metadata, fetch_embeddings), merge_node],
    initial_state,
)
```

### Node hooks

Attach lifecycle callbacks to observe node execution:

```python
from stroma import NodeHooks, RunConfig

async def on_start(run_id, node_id, input_dict):
    print(f"Starting {node_id}")

config = RunConfig(hooks=NodeHooks(on_node_start=on_start))
```

### Shared context

Pass runtime configuration to nodes that accept a second argument:

```python
@runner.node("enrich", input=Input, output=Output)
async def enrich(state: Input, ctx: dict) -> dict:
    api_key = ctx["api_key"]
    # ...

config = RunConfig(context={"api_key": "sk-..."})
```

### Per-node retry policies

Override the global retry policy for specific nodes:

```python
from stroma import FailureClass, FailurePolicy

config = RunConfig(
    node_policies={
        "flaky_node": {
            FailureClass.RECOVERABLE: FailurePolicy(max_retries=5, backoff_seconds=2.0),
        }
    }
)
```

### Async checkpointing

The default store is now async. For distributed pipelines, use the async Redis store:

```python
from stroma import RedisStore, CheckpointManager

store = RedisStore("redis://localhost:6379", ttl_seconds=7200)
manager = CheckpointManager(store)
```

The original synchronous Redis store is still available as `SyncRedisStore`.

## Documentation

Full documentation including a tutorial and API reference is available at the [docs site](https://jengroff.github.io/stroma).

## Development

```bash
uv sync --extra dev
uv run pytest tests/ -v --cov=stroma --cov-fail-under=85
```

## License

MIT
