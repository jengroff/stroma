# Concepts

Stroma is built around core primitives that work together to make agent pipelines reliable. Each can be used independently, but they compose naturally when wired through the `StromaRunner`.

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

When validation fails, a `ContractViolation` is raised with the node ID, direction (`"input"` or `"output"`), the raw data, and Pydantic's error details. The `str()` representation includes the first 5 field-level errors so you can diagnose failures without digging into the trace:

```
Contract violation for 'search' (output): urls: Input should be a valid list; scores: Input should be a valid list
```

The runner classifies contract violations as **terminal** failures — no retries, because the data shape won't fix itself.

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

```python
from stroma import FailureClass, FailurePolicy

custom_policies = {
    FailureClass.RECOVERABLE: FailurePolicy(max_retries=5, backoff_seconds=2.0),
    FailureClass.TERMINAL: FailurePolicy(max_retries=0),
    FailureClass.AMBIGUOUS: FailurePolicy(max_retries=2, backoff_seconds=0.5),
}
```

### Per-node policy overrides

The global `policy_map` applies to all nodes. When a specific node needs different retry behavior, use `node_policies` to override on a per-node basis:

```python
from stroma import RunConfig, FailureClass, FailurePolicy

config = RunConfig(
    policy_map={  # global defaults
        FailureClass.RECOVERABLE: FailurePolicy(max_retries=3, backoff_seconds=1.0),
        FailureClass.TERMINAL: FailurePolicy(max_retries=0),
        FailureClass.AMBIGUOUS: FailurePolicy(max_retries=1, backoff_seconds=0.5),
    },
    node_policies={  # per-node overrides
        "llm_call": {
            FailureClass.RECOVERABLE: FailurePolicy(max_retries=5, backoff_seconds=2.0),
        },
        "fast_transform": {
            FailureClass.RECOVERABLE: FailurePolicy(max_retries=0),
        },
    },
)
```

The lookup order is: per-node override → global `policy_map` → built-in defaults. Unspecified failure classes for a node fall through to the global policy.

!!! note "Jittered backoff"
    The actual delay before each retry is `random.uniform(0, backoff_seconds)` — not a fixed sleep. This prevents thundering herd problems when multiple pipelines retry simultaneously against the same API.

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

### Reporting token usage and model

Nodes report usage by returning a tuple. Four shapes are supported:

| Return shape | Fields |
|-------------|--------|
| `dict` | No usage tracking (tokens=0, cost=0) |
| `(dict, tokens)` | Total tokens, no model-based pricing |
| `(dict, input_tokens, model)` | Input tokens + model name for cost estimation |
| `(dict, input_tokens, output_tokens, model)` | Full usage with separate input/output tokens |

When a `model` string is provided, `estimate_cost_usd` looks up pricing from `KNOWN_MODELS` and computes the USD cost automatically:

```python
@stroma_node("summarize", contract)
async def summarize(state: Input) -> tuple:
    result = await llm.generate(state.text)
    return (
        {"summary": result.text},
        result.usage.input_tokens,
        result.usage.output_tokens,
        "gpt-4o",  # (1)!
    )
```

1. Stroma looks up `"gpt-4o"` in `KNOWN_MODELS` and computes cost as `(input_tokens * input_price + output_tokens * output_price) / 1_000_000`. Unknown models default to $0.00.

### Built-in pricing

`KNOWN_MODELS` ships with per-million-token pricing for these models:

| Model | Input ($/1M tokens) | Output ($/1M tokens) |
|-------|--------------------:|---------------------:|
| `gpt-4o` | 2.50 | 10.00 |
| `gpt-4o-mini` | 0.15 | 0.60 |
| `gpt-4-turbo` | 10.00 | 30.00 |
| `claude-opus-4-6` | 15.00 | 75.00 |
| `claude-sonnet-4-6` | 3.00 | 15.00 |
| `claude-haiku-4-5` | 0.80 | 4.00 |
| `gemini-1.5-pro` | 3.50 | 10.50 |
| `gemini-1.5-flash` | 0.35 | 1.05 |

Unknown models default to `$0.00` — no error, just no cost tracking. You can inspect or extend `KNOWN_MODELS` at runtime:

```python
from stroma import KNOWN_MODELS

# Add a custom model
KNOWN_MODELS["my-fine-tune"] = (5.00, 15.00)
```

The `max_cost_usd` budget enforces actual dollar limits based on model pricing.

---

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

### Storage backends

| Backend | Interface | Use case |
|---------|-----------|----------|
| `InMemoryStore` | sync | Testing, short-lived pipelines |
| `AsyncInMemoryStore` | async | Testing with async runners (default for `StromaRunner.quick()`) |
| `RedisStore` | async | Production, distributed systems (uses `redis.asyncio`) |
| `SyncRedisStore` | sync | Legacy or sync-only environments |

The `CheckpointManager` handles both sync and async stores transparently. Implement the `CheckpointStore` or `AsyncCheckpointStore` protocol to add your own backend — no subclassing required, just implement `save`, `load`, and `delete`.

!!! note "Additive with LangGraph"
    If you're already using LangGraph's checkpointer (MemorySaver, SqliteSaver, etc.), keep it. Stroma's checkpointing is for non-LangGraph pipelines or as a complementary layer.

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

## Hooks, Context, and Logging

These features are composable and optional — use what your pipeline needs.

**Observability hooks** — `NodeHooks` provides async callbacks (`on_node_start`, `on_node_success`, `on_node_failure`) at node boundaries for telemetry. All optional, zero overhead when `None`. See the [hooks tutorial](tutorial/hooks.md) and [Extending Stroma](extending.md) for full OTel examples.

**Shared context** — a mutable `dict` on `RunConfig` passed to nodes that accept a second parameter. Use it for HTTP clients, API keys, caches, or accumulated metadata. See the [shared context tutorial](tutorial/shared-context.md).

**Structured logging** — the runner creates a per-run `logging.LoggerAdapter` with `run_id` in its `extra` dict, making it filterable in JSON log pipelines.

## Pipeline Execution

The `StromaRunner` ties everything together. For each node in the sequence it:

1. Validates input against the contract
2. Fires `on_node_start` hook (if configured)
3. Executes the async node function (passing context if the node accepts it)
4. Validates output against the contract
5. Records resource usage, computes cost from model pricing, and checks the budget
6. Saves a checkpoint
7. Records a trace event
8. Fires `on_node_success` hook (if configured)

On failure, it fires `on_node_failure`, classifies the exception, looks up the per-node or global retry policy, and either retries with jittered backoff, stops with a terminal status, or gives up after exhausting retries.

```
Input State → [Hook:start] → [Contract] → Node → [Contract] → [Budget] → [Checkpoint] → [Hook:success] → Output State
                                             ↑                                                                   |
                                             └──────────── retry (if recoverable) ──────────────────────────────┘
```

### Parallel fan-out

For independent nodes that can run simultaneously, use `parallel()`:

```python
from stroma import parallel

result = await runner.run(
    [node_a, parallel(node_b, node_c), node_d],
    state,
)
```

`parallel()` wraps multiple nodes into a single pseudo-node that runs them concurrently with `asyncio.gather`. Child outputs are merged into a single dict (last write wins on key conflicts). Each child's output is validated against its declared contract before merging, so structurally invalid data is caught immediately. On any child failure (including `ContractViolation`), remaining tasks are cancelled and the exception propagates to the runner's failure handling. Parallel nodes also support retries — transient failures are retried with the same backoff policies as sequential nodes.

### Stateless runner

`CostTracker`, `RetryBudget`, and `ExecutionTrace` are created fresh per `run()` call. Calling `runner.run()` multiple times on the same instance does not accumulate state between runs.

## Stability

Not every primitive is at the same maturity level. Use this as a guide for production planning.

| Status | Primitives |
|--------|-----------|
| **Stable** | `StromaRunner`, contracts, failure classification, retry policies, execution tracing |
| **Stable** | Checkpointing (`InMemoryStore`, `AsyncInMemoryStore`, `RedisStore`) |
| **Beta** | LangGraph adapter, fluent builder API (`.with_budget()`, `.with_hooks()`, etc.) |
| **Experimental** | Cost tracking / `KNOWN_MODELS` pricing, `ModelHint` / fallback routing |

**Stable** means the API won't change without a major version bump. **Beta** means the API is solid but may see minor adjustments. **Experimental** means useful today but subject to change.
