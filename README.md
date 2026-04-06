# Stroma

**dbt didn't replace your data warehouse. Stroma doesn't replace your agent framework.**

dbt gave you typed models, tested transformations, and documented lineage — a software engineering layer that worked regardless of which warehouse you were running. Stroma does the same thing for agent pipelines: typed contracts at every execution boundary, formal failure classification, and cost-aware execution — portable across whatever orchestration pattern you're building on.

The framework handles the graph. Stroma handles the guarantees.

## The problem it solves

LLM pipelines fail in ways that traditional software doesn't. A node returns malformed data and the error surfaces three steps later. A transient timeout kills a 20-minute run and you start over from scratch. Costs spiral past budget with no enforcement mechanism. Failures are silent until they're catastrophic.

Stroma gives you the building blocks to handle this — without locking you into a framework.

## See it in action

The scenario below is the kind that breaks raw LangGraph pipelines: a multi-step run that crashes midway, resumes from checkpoint, and gives you a diff of what changed between the failed and successful run.

```python
import asyncio
from pydantic import BaseModel
from stroma import (
    AsyncInMemoryStore,
    CheckpointManager,
    ContractRegistry,
    NodeContract,
    RunConfig,
    StromaRunner,
    stroma_node,
)


class Document(BaseModel):
    text: str


class Extracted(BaseModel):
    entities: list[str]


class Summary(BaseModel):
    entities: list[str]
    count: int


registry = ContractRegistry()
store = AsyncInMemoryStore()
manager = CheckpointManager(store)

c1 = NodeContract(node_id="extract", input_schema=Document, output_schema=Extracted)
c2 = NodeContract(node_id="summarize", input_schema=Extracted, output_schema=Summary)
registry.register(c1)
registry.register(c2)


@stroma_node("extract", c1)
async def extract(state: Document) -> dict:
    return {"entities": state.text.split()}


@stroma_node("summarize", c2)
async def summarize_failing(state: Extracted) -> dict:
    raise TimeoutError("downstream API unavailable")  # (1)!


@stroma_node("summarize", c2)
async def summarize_fixed(state: Extracted) -> dict:
    return {"entities": state.entities, "count": len(state.entities)}


async def main():
    config1 = RunConfig(run_id="doc-run-1")
    runner1 = StromaRunner(registry, manager, config1)
    result1 = await runner1.run(
        [extract, summarize_failing],
        Document(text="Stroma adds reliability to agent pipelines"),
    )
    print(result1.status)  # PARTIAL — extract checkpointed, summarize exhausted retries

    config2 = RunConfig(run_id="doc-run-1", resume_from="summarize")  # (2)!
    runner2 = StromaRunner(registry, manager, config2)
    result2 = await runner2.run(
        [extract, summarize_fixed],
        Document(text="Stroma adds reliability to agent pipelines"),
    )
    print(result2.status)       # RESUMED — extract skipped, loaded from checkpoint
    print(result2.final_state)  # entities=[...] count=6

    diffs = result1.trace.diff(result2.trace)  # (3)!
    for d in diffs:
        print(d)


asyncio.run(main())
# In a Jupyter notebook, replace the line above with: await main()
```

1. `TimeoutError` is classified as `RECOVERABLE`. Stroma retries with jittered backoff. After exhausting retries, the run fails — but `extract`'s output is already checkpointed.
2. Same `run_id`, `resume_from="summarize"`. The runner loads `extract`'s checkpoint and skips re-running it entirely.
3. `diff()` compares both traces — node IDs, attempts, inputs, outputs, failure states — so you can see exactly what changed between the failed run and the successful one.

## What You Get

- **Contracts** — Pydantic-based input/output validation at every node boundary
- **Failure classification** — automatic categorization of errors as recoverable, terminal, or ambiguous
- **Retry policies** — configurable retries with jittered backoff, per failure class or per node
- **Checkpointing** — async-first save and resume across crashes (in-memory or Redis)
- **Cost estimation** — model-aware USD cost tracking via `KNOWN_MODELS` and token/dollar/latency budgets
- **Per-node timeouts** — configurable `node_timeouts` with `asyncio.wait_for`; timeouts are classified as recoverable and retried automatically
- **Parallel execution** — fan out work to concurrent nodes with `parallel()`, per-child contract validation, merged output, and full retry support
- **Node hooks** — async `on_node_start`, `on_node_success`, and `on_node_failure` callbacks
- **Shared context** — pass a mutable `context` dict through `RunConfig` to every node
- **Execution tracing** — full record of every node attempt, with diffing and JSON export
- **Per-run logging** — structured `LoggerAdapter` with `run_id` in every log line
- **Model fallback** — automatically downgrade to a cheaper model when spend crosses a budget threshold via `.with_model_fallback()`
- **Fluent builder API** — configure runners with chained `.with_budget()`, `.with_hooks()`, `.with_model_fallback()`, `.with_redis()`, etc.
- **LangGraph adapter** — apply contracts to existing LangGraph graphs
- **CrewAI adapter** — contract validation for CrewAI Flow methods
- **DeepAgents adapter** — contract validation and cost tracking for deepagents graphs
- **Universal reliability middleware** — `execute_step()` and `StromaStep` apply contracts, retries, cost tracking, and checkpointing to any async callable, independent of any framework
- **Framework-agnostic** — works with any async Python code, no framework lock-in

## Install

Requires **Python 3.12+**.

```bash
uv add stroma
```

Optional extras:

```bash
uv add stroma[redis]       # Redis-backed checkpointing
uv add stroma[langgraph]   # LangGraph adapter
uv add stroma[crewai]      # CrewAI adapter
uv add stroma[deepagents]  # DeepAgents adapter
```

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

### Per-node timeouts

Guard against hanging LLM calls with per-node timeouts. Timeouts raise `TimeoutError`, which is classified as recoverable and retried automatically:

```python
runner = StromaRunner.quick().with_node_timeouts({
    "llm_call": 30_000,   # 30 seconds
    "embedding": 10_000,  # 10 seconds
})
```

### Async checkpointing

The default store is now async. For distributed pipelines, use the async Redis store:

```python
from stroma import RedisStore, CheckpointManager

store = RedisStore("redis://localhost:6379", ttl_seconds=7200)
manager = CheckpointManager(store)
```

The original synchronous Redis store is still available as `SyncRedisStore`.

### Model fallback at budget threshold

Automatically downgrade to a cheaper model when spend crosses a threshold instead of failing:

```python
runner = (
    StromaRunner.quick()
    .with_budget(cost_usd=1.00)
    .with_model_fallback("gpt-4o", to="gpt-4o-mini", at_budget_pct=0.80)
)
```

Nodes read the active model from `ctx["_stroma_model"]` and pass it to their LLM client.

### Framework-free reliability with StromaStep

Apply contracts, retries, cost tracking, and checkpointing to any async callable — no runner or framework adapter required:

```python
from stroma import ReliabilityContext, RunConfig, StromaStep

ctx = ReliabilityContext.for_run(RunConfig(), registry, checkpoint_manager)
step = StromaStep(ctx)

@step("summarize", input=DocInput, output=Summary)
async def summarize(state: DocInput) -> dict:
    return {"text": state.doc[:100]}

result = await summarize(DocInput(doc="..."))
```

## Documentation

Full documentation including a tutorial and API reference is available at the [docs site](https://jengroff.github.io/stroma).

## Development

```bash
uv sync --extra dev
uv run pytest tests/ -v --cov=stroma --cov-fail-under=85
```

## License

MIT
