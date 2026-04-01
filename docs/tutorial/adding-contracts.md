# Adding Contracts

Contracts define the expected input and output schemas for each node. They catch data shape issues at node boundaries before they propagate downstream.

## How contracts work

When you used `@runner.node("double", input=Input, output=Output)` in the previous page, you were already using contracts. The decorator creates a `NodeContract` and registers it behind the scenes.

Let's see what that looks like explicitly:

```python
import asyncio
from pydantic import BaseModel
from stroma import (
    ContractRegistry,
    CheckpointManager,
    InMemoryStore,
    NodeContract,
    RunConfig,
    StromaRunner,
    stroma_node,
)


class Query(BaseModel):
    text: str
    max_results: int


class SearchResult(BaseModel):
    urls: list[str]
    scores: list[float]


# 1. Create a contract
contract = NodeContract(  # (1)!
    node_id="search",
    input_schema=Query,
    output_schema=SearchResult,
)

# 2. Register it
registry = ContractRegistry()
registry.register(contract)  # (2)!

# 3. Decorate the node
@stroma_node("search", contract)  # (3)!
async def search(state: Query) -> dict:
    return {
        "urls": [f"https://example.com/{i}" for i in range(state.max_results)],
        "scores": [0.9, 0.8, 0.7][:state.max_results],
    }

# 4. Build the runner
runner = StromaRunner(
    registry,
    CheckpointManager(InMemoryStore()),
    RunConfig(),
)


async def main():
    result = await runner.run([search], Query(text="stroma", max_results=3))
    print(result.final_state)

asyncio.run(main())
```

1. A `NodeContract` binds a node ID to its input and output Pydantic models.
2. The `ContractRegistry` maps node IDs to contracts. The runner uses it to look up which schema to validate against.
3. The `@stroma_node` decorator attaches the contract to the function so the runner can find it.

!!! tip "Quick API vs explicit API"
    Use `@runner.node()` for most cases — it's less code and handles registration automatically. Use the explicit API when you need to share a registry across runners, or when you want to separate contract definition from node implementation.

## What happens when validation fails

If a node returns data that doesn't match its output schema, the runner raises a `ContractViolation`:

```python
@runner.node("bad_node", input=Query, output=SearchResult)
async def bad_node(state: Query) -> dict:
    return {"urls": "not-a-list", "scores": "also-wrong"}  # (1)!
```

1. `urls` should be `list[str]` and `scores` should be `list[float]`. Pydantic will reject this.

The runner classifies `ContractViolation` as a **terminal failure** — no retries, because the data shape won't fix itself on a second attempt. The pipeline stops immediately with `status=FAILED`.

```python
result = await runner.run([bad_node], Query(text="test", max_results=1))
print(result.status)  # FAILED
```

!!! warning
    Contract violations are caught at the boundary, not inside the node. If your node does internal processing that produces bad data, the violation is detected when the runner validates the output — not during execution.

## Input validation

The runner also validates inputs. If node B expects `SearchResult` but node A produced something different, the input validation catches it:

```python
class WrongOutput(BaseModel):
    name: str  # (1)!

runner = StromaRunner.quick()

@runner.node("node_a", input=Query, output=WrongOutput)
async def node_a(state: Query) -> dict:
    return {"name": "oops"}

@runner.node("node_b", input=SearchResult, output=SearchResult)
async def node_b(state: SearchResult) -> dict:
    return {"urls": state.urls, "scores": state.scores}


async def main():
    result = await runner.run(
        [node_a, node_b],
        Query(text="test", max_results=1),
    )
    print(result.status)  # FAILED — node_b's input validation rejects WrongOutput

asyncio.run(main())
```

1. `node_a` outputs `WrongOutput` which has no `urls` or `scores` fields — so `node_b`'s input validation will fail.

## Recap

- **`NodeContract`** binds a node ID to input/output Pydantic models
- **`ContractRegistry`** maps node IDs to contracts for the runner to look up
- **`@runner.node()`** combines contract creation + registration + decoration in one step
- **`ContractViolation`** is raised on schema mismatch — classified as terminal (no retries)
- Validation happens at both **input and output** boundaries

**Next: [Retry & Failures](retry-and-failures.md)** — learn how the runner classifies errors and configures retries.
