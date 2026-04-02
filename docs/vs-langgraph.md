# Stroma vs. LangGraph

Stroma and LangGraph solve different problems. LangGraph is a graph execution framework. Stroma is a set of reliability primitives. They can be used independently or together via the `LangGraphAdapter`.

This page is an honest comparison to help you decide what to use.

## What each tool does

| | LangGraph | Stroma |
|---|---|---|
| **Primary job** | Graph orchestration (routing, cycles, streaming, HITL) | Reliability at node boundaries (contracts, retries, cost, tracing) |
| **State model** | TypedDict or Pydantic, validated at graph entry | Pydantic, validated at every node boundary (input + output) |
| **Failure handling** | Binary retry (retry or don't) | Three-class taxonomy (recoverable / terminal / ambiguous) with per-node policies and custom classifiers |
| **Checkpointing** | Built-in (MemorySaver, Sqlite, Postgres) | Built-in (in-memory, Redis) — independent layer, does not replace LangGraph's |
| **Cost tracking** | None | Token, USD, and latency budgets with model-aware pricing |
| **Tracing** | Via LangSmith (external service) | In-process `ExecutionTrace` with diff, replay, JSON export |
| **Concurrency** | Full graph-level parallelism | `parallel()` fan-out with per-child contract validation |
| **Streaming** | Yes | No |
| **Human-in-the-loop** | Yes (`interrupt_before` / `interrupt_after`) | No |
| **Dynamic routing / cycles** | Yes | No — sequential pipeline or use an external orchestrator |

## What Stroma adds to LangGraph

If you already have a LangGraph graph, Stroma adds three things LangGraph doesn't provide:

**Typed contracts at every node boundary.** LangGraph validates state at graph entry — the first node's input — but [does not enforce schemas at subsequent node boundaries](https://langchain-ai.github.io/langgraph/concepts/low_level/#state). A node can return malformed data and it propagates silently until something downstream breaks. Stroma's `NodeContract` validates both input and output at every decorated node.

**Formal failure classification.** LangGraph's `RetryPolicy` retries on any exception up to a max count. It doesn't distinguish between a rate limit (retry in 2 seconds) and a schema violation (don't retry at all). Stroma classifies every failure and applies different retry policies per class, per node.

**Cost budget enforcement.** LangGraph has no mechanism for capping token spend, USD cost, or latency across a run. Stroma's `ExecutionBudget` enforces hard limits on all three, with `BudgetExceeded` integrated into the failure classification system.

## What Stroma does not do

Stroma is not an orchestrator. It does not provide:

- **Graph execution** — no conditional edges, cycles, or dynamic routing
- **Streaming** — no token-level or event-level streaming
- **Human-in-the-loop** — no interrupt/resume at arbitrary points
- **Agent loops** — no built-in tool-call loops or ReAct patterns

If you need these, use LangGraph (or another orchestrator) and add Stroma on top via the adapter.

## Known limitations

Being transparent about where Stroma is still maturing:

- **Adapter maturity** — `LangGraphAdapter` and `DeepAgentsAdapter` are beta. They provide contract validation and cost tracking, but not the full runner feature set (retries, failure classification)
- **Sequential execution model** — `StromaRunner` runs nodes in a fixed sequence. For graph topologies, you need an external orchestrator
- **`parallel()` semantics** — fan-out uses `asyncio.gather` with no concurrency limits or cancellation policies. Per-child contract validation is enforced, but there's no per-child retry or checkpointing

## Using them together

The `LangGraphAdapter` wraps an existing LangGraph graph to add contract validation without rewriting it:

```python
from stroma import ContractRegistry
from stroma.adapters.langgraph import LangGraphAdapter, stroma_langgraph_node

adapter = LangGraphAdapter(registry)
wrapped_graph = adapter.wrap(your_langgraph_graph)
```

Decorated nodes get input/output validation. Non-decorated nodes are left untouched. LangGraph keeps its own checkpointer — Stroma doesn't interfere.

See the [LangGraph Integration tutorial](tutorial/langgraph.md) for a full walkthrough.

## When to use what

| Situation | Recommendation |
|---|---|
| Building a graph with routing, cycles, or streaming | LangGraph |
| Need typed validation at every node boundary | Stroma |
| Need formal failure taxonomy beyond binary retry | Stroma |
| Need cost/token/latency budget enforcement | Stroma |
| Existing LangGraph graph, want to add contracts | `LangGraphAdapter` |
| New sequential pipeline from scratch | `StromaRunner` directly |
| Need both orchestration and reliability | LangGraph for the graph, Stroma for the guarantees |
