# LangGraph Integration

If you already use [LangGraph](https://github.com/langchain-ai/langgraph), Stroma can add contract validation to your existing graphs without rewriting them.

## Install

```bash
pip install stroma[langgraph]
```

## Decorating LangGraph nodes

Use `@stroma_langgraph_node` to attach contracts to your LangGraph node functions:

```python
from pydantic import BaseModel
from stroma import (
    ContractRegistry,
    NodeContract,
    StromaRunner,
)
from stroma.adapters.langgraph import (
    LangGraphAdapter,
    stroma_langgraph_node,
)


class InputState(BaseModel):
    x: int


class OutputState(BaseModel):
    y: int


# Define contracts
registry = ContractRegistry()

contract = NodeContract(
    node_id="add_one",
    input_schema=InputState,
    output_schema=OutputState,
)
registry.register(contract)


@stroma_langgraph_node("add_one", contract)  # (1)!
async def add_one(state: InputState) -> dict:
    return {"y": state.x + 1}
```

1. Works like `@stroma_node` but is designed for LangGraph's state-passing pattern.

## Wrapping a graph

The `LangGraphAdapter` discovers decorated nodes in your graph and wraps them with validation:

```python
runner = StromaRunner.quick()
adapter = LangGraphAdapter(registry, runner)

# Assuming you have a compiled LangGraph graph
# graph = build_your_graph()
# wrapped = adapter.wrap(graph)  # (1)!
```

1. `wrap()` finds all nodes decorated with `@stroma_langgraph_node`, replaces them with validating wrappers, and returns the modified graph. Non-decorated nodes are left untouched.

## How wrapping works

When the adapter wraps a node, it:

1. Extracts the state dict from LangGraph's state object
2. Validates it against the node's **input schema**
3. Calls the original node function
4. Validates the result against the node's **output schema**
5. Returns the validated output as a dict

If validation fails at either boundary, a `ContractViolation` is raised — just like with the standard runner.

!!! info "State extraction"
    The adapter handles multiple state formats: plain dicts, Pydantic models, objects with `.dict()`, and objects with `__dict__`. This covers LangGraph's various state representations.

## When to use the adapter vs. the runner

| Use case | Recommendation |
|----------|---------------|
| New pipeline from scratch | Use `StromaRunner` directly |
| Existing LangGraph graph | Use `LangGraphAdapter` to add validation |
| Gradual migration | Start with the adapter, migrate nodes to the runner over time |

!!! tip
    The adapter currently provides **contract validation only**. Full runner features (retries, checkpointing, cost tracking) require using `StromaRunner` directly.

## Recap

- Install with `pip install stroma[langgraph]`
- Decorate nodes with **`@stroma_langgraph_node`** to attach contracts
- Use **`LangGraphAdapter.wrap(graph)`** to add validation to an existing graph
- The adapter validates inputs and outputs at every decorated node boundary

**That's the end of the tutorial!** For deeper dives, check the [Concepts guide](../concepts.md) and the [API Reference](../api/runner.md).
