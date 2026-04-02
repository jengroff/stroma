# Stroma vs. LangGraph

LangGraph handles orchestration. Stroma adds reliability primitives. They can be used independently or together.

Understanding the distinction matters because the two tools solve different problems at different layers of the stack.

## The dbt analogy

dbt didn't replace your data warehouse. Snowflake already had views, stored procedures, and scheduling. What dbt gave you was a software engineering layer on top — typed models, tested transformations, documented lineage — that worked regardless of which warehouse you were running.

Stroma does the same thing for agent execution graphs. LangGraph already has checkpointing, retry, and state management. What Stroma gives you is a reliability layer on top — typed state contracts, formal failure classification, portable checkpointing, cost-aware execution planning — that works regardless of which orchestration framework you're running.

The framework handles the graph. Stroma handles the guarantees.

## What LangGraph provides

LangGraph is a mature, well-designed orchestration framework. It gives you:

- **Graph execution** — nodes, edges, conditional routing, cycles
- **State management** — TypedDict and Pydantic models for graph state
- **Built-in checkpointing** — MemorySaver, SqliteSaver, AsyncPostgresSaver
- **Node-level retry** — RetryPolicy for retrying individual nodes on failure
- **Streaming** — token and event streaming out of the box
- **Human-in-the-loop** — interrupt_before and interrupt_after for manual intervention

These are real, production-grade features. If you are building a LangGraph application, you should use them.

## Where Stroma is additive

Stroma does not duplicate LangGraph's orchestration primitives. It addresses a different layer of the problem — one that LangGraph does not currently solve.

### Typed state contracts at node boundaries

LangGraph passes state through the graph. It validates state at graph entry — the first node's input — but [run-time validation only occurs on inputs to the first node](https://langchain-ai.github.io/langgraph/concepts/low_level/#state), not on subsequent nodes or outputs. It does not enforce schema contracts at individual node boundaries — it does not verify that node A's output is structurally valid input for node B before passing it through.

Stroma's NodeContract does exactly this. Every node boundary is a validation checkpoint. When a node returns malformed data, ContractViolation is raised immediately at that boundary — classified as a terminal failure — rather than propagating corrupt state downstream where it becomes much harder to diagnose.

This is the load-bearing primitive. Everything else in Stroma composes on top of it.

### Formal failure classification

LangGraph's RetryPolicy is binary: retry or don't, up to a maximum number of attempts. It does not distinguish between failures that are transient (and likely to resolve on retry) versus permanent (and not worth retrying) versus ambiguous.

Stroma's failure taxonomy is a formal three-class system:

| Class | Meaning | Default behavior |
|---|---|---|
| RECOVERABLE | Transient — retry with backoff | 3 retries, jittered backoff |
| TERMINAL | Permanent — stop immediately | No retries |
| AMBIGUOUS | Uncertain — limited retry | 1 retry, short backoff |

Custom classifiers let you extend this taxonomy for domain-specific errors — rate limits, auth failures, service-specific exceptions — without modifying the core retry logic.

### Execution tracing with diff and replay

LangGraph's primary observability tool is LangSmith. Stroma takes a different approach: `ExecutionTrace` captures every attempt — successes, failures, retries, timing, input and output state — as a first-class in-process object. You can diff two traces across runs, replay events in order, filter to failures, and export to JSON for any monitoring system you choose.

### Cost-aware execution planning

LangGraph has no built-in mechanism for enforcing token, cost, or latency budgets across a pipeline run, or for routing nodes to cheaper models when budgets are constrained.

Stroma's ExecutionBudget and CostTracker enforce hard limits on all three dimensions, with BudgetExceeded integrated into the failure classification system so budget violations are handled with the same retry machinery as any other recoverable failure.

## The architectural difference

LangGraph's reliability features are framework-internal. They work within LangGraph, through LangGraph's APIs, against LangGraph's state model. If you switch orchestration frameworks, or compose multiple frameworks, or build a custom execution layer, you leave those features behind.

Stroma's primitives are framework-agnostic by design. The core library has no dependency on LangGraph. The LangGraphAdapter is the only framework-specific code in the entire codebase — a single file that translates between LangGraph's execution model and Stroma's contract system. Everything else — contracts, failure classification, checkpointing, cost tracking, execution tracing — is portable.

This is a deliberate architectural decision, not an oversight. The reliability spine should not be coupled to the orchestration layer, for the same reason that dbt's transformation logic should not be coupled to a specific warehouse's proprietary SQL dialect.

## Side-by-side

| Capability | Stroma | LangGraph |
|---|---|---|
| Orchestration (routing, cycles, streaming) | No | Yes |
| Typed boundary contracts | Yes | Partial |
| Retry classification (3-class) | Yes | Partial |
| Checkpoint / resume | Yes | Yes |
| Execution trace with diff / replay | Yes | Partial |
| Framework-agnostic | Yes | No |

## When to use what

| Situation | Recommendation |
|---|---|
| Building a new pipeline from scratch | Use StromaRunner directly, with LangGraph as your execution backend if needed |
| Existing LangGraph graph | Use LangGraphAdapter to add contract validation without rewriting |
| Already using LangGraph's checkpointer | Keep it — Stroma's checkpointing is additive, not required |
| Need formal failure taxonomy and custom classifiers | Stroma |
| Need typed boundary validation between nodes | Stroma |
| Need portable reliability primitives across frameworks | Stroma |
| Need graph routing, cycles, streaming, human-in-the-loop | LangGraph |

Use LangGraph to build your graph. Use Stroma to make it reliable. Use both when you need both.
