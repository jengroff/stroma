# Concepts

Stroma is built around five core primitives that work together to make agent pipelines reliable. Each can be used independently, but they compose naturally when wired through the `StromaRunner`.

!!! tip "New to Stroma?"
    If you're looking for a hands-on introduction, start with the [Tutorial](tutorial/index.md). This page covers architecture and design decisions — it's a reference, not a walkthrough.

## Contracts

A **contract** defines the expected input and output schemas for a pipeline node using Pydantic models. Contracts catch data shape issues at node boundaries before they propagate downstream.

```python
from pydantic import BaseModel
from stroma import ContractRegistry, NodeContract

class Query(BaseModel):
    text: str
    max_results: int

class SearchResult(BaseModel):
    urls: list[str]
    scores: list[float]

registry = ContractRegistry()
registry.register(NodeContract(
    node_id="search",
    input_schema=Query,
    output_schema=SearchResult,
))
```

When validation fails, a `ContractViolation` is raised with the node ID, direction (`"input"` or `"output"`), the raw data, and Pydantic's error details. The runner classifies contract violations as **terminal** failures — no retries, because the data shape won't fix itself.

!!! info "Why terminal?"
    A `ContractViolation` means the node produced structurally invalid data. Retrying with the same input will produce the same bad output. The fix is in the node's logic, not in a retry.

## Failure Classification

Not all errors are equal. Stroma categorizes every exception into one of three classes:

| Class | Meaning | Default behavior |
|-------|---------|------------------|
| `RECOVERABLE` | Transient failure (timeouts, rate limits) | Retry up to 3 times with jittered backoff |
| `TERMINAL` | Permanent failure (bad data, logic errors) | Stop immediately |
| `AMBIGUOUS` | Unknown — might resolve on retry | Retry once with short backoff |

Built-in rules handle common exceptions:

| Exception | Classification |
|-----------|---------------|
| `ContractViolation` | `TERMINAL` |
| `BudgetExceeded` | `RECOVERABLE` |
| `TimeoutError` | `RECOVERABLE` |
| `ValueError` | `AMBIGUOUS` |
| Everything else | `AMBIGUOUS` |

Override with **custom classifiers** — callables that inspect the exception and context, returning a `FailureClass` or `None` to defer:

```python
from stroma import FailureClass, StromaRunner

def classify_rate_limit(exc, ctx):  # (1)!
    if "rate limit" in str(exc).lower():
        return FailureClass.RECOVERABLE
    return None  # (2)!

runner = StromaRunner.quick(
    classifiers=[classify_rate_limit],
)
```

1. `ctx` is a `NodeContext` with `node_id`, `attempt`, and `run_id` — use it to make classification decisions based on where and when the error occurred.
2. Return `None` to pass to the next classifier. If no classifier matches, built-in rules apply.

Custom classifiers are checked first, in order. If none return a result, the built-in rules apply.

## Retry Policies

Each failure class maps to a **retry policy** controlling:

- **`max_retries`** — how many times to retry before giving up
- **`backoff_seconds`** — maximum backoff (actual delay is jittered between 0 and this value)
- **`fallback_node_id`** — an alternative node to route to (for future use)

```python
from stroma import FailureClass, FailurePolicy

custom_policies = {
    FailureClass.RECOVERABLE: FailurePolicy(max_retries=5, backoff_seconds=2.0),
    FailureClass.TERMINAL: FailurePolicy(max_retries=0),
    FailureClass.AMBIGUOUS: FailurePolicy(max_retries=2, backoff_seconds=0.5),
}
```

!!! note "Jittered backoff"
    The actual delay before each retry is `random.uniform(0, backoff_seconds)` — not a fixed sleep. This prevents thundering herd problems when multiple pipelines retry simultaneously against the same API.

## Checkpointing

After each successful node execution, the output state is **checkpointed**. If a pipeline fails partway through, you can resume from the last checkpoint instead of re-running completed nodes:

```python
from stroma import RunConfig

# First run fails at node3
config1 = RunConfig(run_id="run-123")
result = await runner.run([node1, node2, node3], initial_state)
# result.status == PARTIAL or FAILED

# Resume from node3 — node1 and node2 are skipped, output loaded from checkpoint
config2 = RunConfig(run_id="run-123", resume_from="node3")  # (1)!
result = await runner.run([node1, node2, node3], initial_state)
# result.status == RESUMED
```

1. The `run_id` must match the original run. The runner loads the checkpoint for the node *before* `resume_from` and uses it as input.

Two storage backends are included:

| Backend | Use case | Persistence |
|---------|----------|-------------|
| `InMemoryStore` | Testing, short-lived pipelines | In-process only |
| `RedisStore` | Production, distributed systems | Survives restarts |

Implement the `CheckpointStore` protocol to add your own backend (Postgres, S3, DynamoDB, etc.) — no subclassing required, just implement `save`, `load`, and `delete`.

## Cost Tracking

Stroma tracks three resource dimensions across your pipeline:

| Dimension | Field | Unit |
|-----------|-------|------|
| **Tokens** | `max_tokens_total` | integer |
| **Cost** | `max_cost_usd` | USD (float) |
| **Latency** | `max_latency_ms` | milliseconds |

Set budget limits on any dimension. When a limit is exceeded, `BudgetExceeded` is raised — classified as `RECOVERABLE` by default.

```python
from stroma import ExecutionBudget

budget = ExecutionBudget(
    max_tokens_total=10_000,
    max_cost_usd=0.50,
    max_latency_ms=30_000,
)
```

Nodes report token usage by returning a tuple:

```python
@stroma_node("summarize", contract)
async def summarize(state: Input) -> dict:
    result = await llm.generate(state.text)
    return ({"summary": result.text}, result.usage.total_tokens)  # (1)!
```

1. Return `(dict, int)` to report tokens. Return just a `dict` if you don't need token tracking — usage defaults to 0.

## Execution Tracing

Every node execution attempt is recorded as a `TraceEvent` capturing:

- Node ID, run ID, and attempt number
- Timestamp and duration
- Input and output state (as dicts)
- Failure class and message (if failed)

The `ExecutionTrace` provides filtering, diffing, replay, and JSON serialization:

```python
result = await runner.run(nodes, state)

# Inspect failures
for event in result.trace.failures():
    print(f"{event.node_id} attempt {event.attempt}: {event.failure_message}")

# Compare two runs
diffs = trace_a.diff(trace_b)  # (1)!

# Export for monitoring
json_payload = result.trace.to_json()
```

1. `diff()` compares node IDs, attempts, inputs, outputs, and failure states — ignoring timestamps and durations that naturally vary between runs.

## Pipeline Execution

The `StromaRunner` ties everything together. For each node in the sequence it:

1. Validates input against the contract
2. Executes the async node function
3. Validates output against the contract
4. Records resource usage and checks the budget
5. Saves a checkpoint
6. Records a trace event

On failure, it classifies the exception, applies the retry policy, and either retries with jittered backoff, stops with a terminal status, or gives up after exhausting retries.

```
Input State → [Contract] → Node → [Contract] → [Budget] → [Checkpoint] → Output State
                              ↑                                              |
                              └──────── retry (if recoverable) ──────────────┘
```

!!! info "Sequential execution"
    The runner executes nodes sequentially — no branching or parallel execution. This is by design: it keeps the mental model simple and makes checkpointing/resume deterministic. For complex DAG-based workflows, use the [LangGraph adapter](tutorial/langgraph.md) or compose multiple `StromaRunner` pipelines.
