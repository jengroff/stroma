# Universal Reliability Layer — Architecture Plan

**Status**: Phases 1-6 implemented in v0.3.2. Concrete adapters for non-graph paradigms are the next step.

## Context

Stroma's reliability primitives — contract validation, cost control, failure handling, observability — are portable across agent orchestration paradigms, not just graph-based frameworks. This document describes the architecture that makes that possible.

The analogy: dbt abstracted data transformation guarantees (typed models, tests, lineage) across warehouses. Stroma abstracts reliability guarantees across agent orchestration patterns.

## Four Agent Orchestration Paradigms

| Paradigm | Examples | Natural boundary | Adapter shape |
|---|---|---|---|
| Pre-defined topology | LangGraph, CrewAI Flows, Haystack | Graph node | `FrameworkAdapter` |
| Agentic loop | Claude Agent SDK, OpenAI Agents SDK, Pydantic AI | Tool call | `LoopAdapter` |
| Conversation-driven | AutoGen | Message turn | `TurnAdapter` |
| Declarative/compiler | DSPy | Module call | `StepInterceptor` |

## Core Abstractions

### ReliabilityContext

Per-run bundle of every reliability primitive: cost tracker, retry budget, execution trace, budget, policies, hooks, and checkpoint manager. Created once per run, threaded through whichever execution strategy drives the steps.

```python
ctx = ReliabilityContext.for_run(config, registry, checkpoint_manager)
```

### execute_step()

The freestanding reliability loop. Applies contract validation, cost tracking, budget enforcement, model fallback, retry logic, checkpointing, and trace recording to a single async callable. Works without `StromaRunner` or any framework adapter.

```python
result = await execute_step("summarize", my_func, input_state, ctx, contract=contract)
```

### StromaStep

Paradigm-agnostic decorator/wrapper backed by `execute_step()`. Equivalent to `StromaRunner.node()` but independent of any execution strategy.

```python
step = StromaStep(ctx)

@step("summarize", input=DocInput, output=Summary)
async def summarize(state: DocInput) -> dict:
    return {"text": "..."}
```

### Adapter Protocols

- `FrameworkAdapter` — for graph-based frameworks (`wrap(graph)` + `node_decorator()`)
- `StepInterceptor` — wraps individual step functions (`wrap_step()`)
- `LoopAdapter` — intercepts tool call boundaries (`on_tool_call()` + `on_tool_result()`)
- `TurnAdapter` — intercepts conversation turn boundaries (`on_turn_start()` + `on_turn_end()`)

## What Stays the Same

`StromaRunner` remains as the execution strategy for linear node pipelines. All existing node-based APIs (`NodeContract`, `stroma_node`, `NodeHooks`, etc.) are unchanged. Step aliases (`StepContract`, `stroma_step`, `StepHooks`, etc.) provide paradigm-neutral naming without breaking anything.

## Next Steps

Build concrete adapters for non-graph paradigms when there is a real integration to test against:

1. **Pydantic AI adapter** — natural fit because it already uses Pydantic for tool signatures
2. **Claude Agent SDK adapter** — `LoopAdapter` implementation intercepting tool calls
3. **AutoGen adapter** — `TurnAdapter` implementation intercepting message turns
4. **Framework-specific examples** — runnable examples for each paradigm (similar to AWS samples)
