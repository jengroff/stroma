# DeepAgents Integration

If you use [deepagents](https://github.com/deepagents/deepagents) to build multi-agent systems, Stroma can add contract validation and cost tracking to your existing graphs without rewriting them.

## Install

```bash
uv add stroma[deepagents]
```

## Decorating deepagents nodes

Use `@stroma_deepagents_node` to attach contracts to your node functions:

```python
from pydantic import BaseModel
from stroma import ContractRegistry, NodeContract
from stroma.adapters.deepagents import (
    DeepAgentsAdapter,
    stroma_deepagents_node,
)


class InputState(BaseModel):
    x: int


class OutputState(BaseModel):
    y: int


registry = ContractRegistry()

contract = NodeContract(
    node_id="add_one",
    input_schema=InputState,
    output_schema=OutputState,
)
registry.register(contract)


@stroma_deepagents_node("add_one", contract)  # (1)!
async def add_one(state: InputState) -> dict:
    return {"y": state.x + 1}
```

1. Works like `@stroma_node` but is designed for deepagents' state-passing pattern.

## Wrapping a graph

The `DeepAgentsAdapter` discovers decorated nodes in your compiled graph and wraps them with validation:

```python
from deepagents import create_deep_agent

agent = create_deep_agent(...)  # returns a compiled LangGraph graph
adapter = DeepAgentsAdapter(registry)
wrapped = adapter.wrap(agent)  # (1)!

result = await wrapped.ainvoke({"x": 1})
```

1. `wrap()` finds all nodes decorated with `@stroma_deepagents_node`, replaces them with validating wrappers, and returns the modified graph. Non-decorated nodes are left untouched.

## How wrapping works

When the adapter wraps a node, it:

1. Extracts the state dict from the graph's state object
2. Validates it against the node's **input schema**
3. Calls the original node function
4. Parses cost info if the node returns a tuple (see below)
5. Validates the result against the node's **output schema**
6. Records token usage in the adapter's `CostTracker`
7. Returns the validated output as a dict

If validation fails at either boundary, a `ContractViolation` is raised — just like with the standard runner.

!!! info "State extraction"
    The adapter handles multiple state formats: plain dicts, Pydantic models, objects with `.dict()`, and objects with `__dict__`. This covers the various state representations that deepagents and LangGraph use internally.

## Cost tracking

Nodes can optionally return a tuple to report token usage:

```python
@stroma_deepagents_node("summarize", contract)
async def summarize(state: InputState) -> tuple:
    result = await call_llm(state.text)
    return ({"summary": result}, 500, 200, "gpt-4o")  # (dict, input_tokens, output_tokens, model)
```

Plain dict returns record zero tokens — no error is raised. Access accumulated usage via `adapter.cost_tracker`.

## Checkpointing

!!! warning "Checkpointing boundary"
    deepagents manages its own checkpointing through LangGraph's `BaseCheckpointSaver`. Stroma does **not** inject a checkpointer by default — deepagents owns that layer.

    If you need a secondary stroma-managed checkpoint (e.g. for cross-system recovery), pass `checkpoint_store` to the adapter constructor. You are responsible for ensuring it does not conflict with deepagents' internal checkpointer.

    ```python
    from stroma import AsyncInMemoryStore

    adapter = DeepAgentsAdapter(registry, checkpoint_store=AsyncInMemoryStore())
    ```

    For most use cases, let deepagents handle checkpointing and use Stroma only for contract validation and cost tracking.

## When to use the adapter vs. the runner

| Use case | Recommendation |
|----------|---------------|
| New pipeline from scratch | Use `StromaRunner` directly |
| Existing deepagents graph | Use `DeepAgentsAdapter` to add validation and cost tracking |
| Gradual migration | Start with the adapter, migrate nodes to the runner over time |
| Need retries and failure classification | Use `StromaRunner` — the adapter does not include retry logic |

!!! tip
    The adapter provides **contract validation and cost tracking**. Full runner features (retries, failure classification, checkpointing, tracing) require using `StromaRunner` directly.

## Recap

- Install with `uv add stroma[deepagents]`
- Decorate nodes with **`@stroma_deepagents_node`** to attach contracts
- Use **`DeepAgentsAdapter.wrap(agent)`** to add validation to an existing graph
- deepagents owns checkpointing — Stroma adds contracts and cost tracking on top
