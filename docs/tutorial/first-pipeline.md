# Your First Pipeline

Build a working pipeline in under 10 lines of code.

## The code

```python
import asyncio
from pydantic import BaseModel
from stroma import StromaRunner


class Input(BaseModel):
    value: int


class Output(BaseModel):
    result: int


runner = StromaRunner.quick()  # (1)!


@runner.node("double", input=Input, output=Output)  # (2)!
async def double(state: Input) -> dict:  # (3)!
    return {"result": state.value * 2}


async def main():
    result = await runner.run([double], Input(value=5))  # (4)!
    print(result.status)       # COMPLETED
    print(result.final_state)  # result=10

asyncio.run(main())
```

1. `StromaRunner.quick()` creates a runner with sensible defaults: in-memory checkpointing, unlimited budget, and standard retry policies.
2. `@runner.node()` declares the contract (input/output schemas) and registers it automatically.
3. Nodes are async functions that receive a Pydantic model and return a dict matching the output schema.
4. `runner.run()` executes nodes in sequence, applying validation, retries, and checkpointing at each step.

Run it:

```bash
python first_pipeline.py
```

```
COMPLETED
result=10
```

## Chaining multiple nodes

Pipelines become useful when you chain nodes together. Each node's output becomes the next node's input:

```python
import asyncio
from pydantic import BaseModel
from stroma import StromaRunner


class Numbers(BaseModel):
    value: int


class Doubled(BaseModel):
    result: int


class Final(BaseModel):
    total: int


runner = StromaRunner.quick()


@runner.node("double", input=Numbers, output=Doubled)
async def double(state: Numbers) -> dict:
    return {"result": state.value * 2}


@runner.node("add_ten", input=Doubled, output=Final)
async def add_ten(state: Doubled) -> dict:
    return {"total": state.result + 10}


async def main():
    result = await runner.run([double, add_ten], Numbers(value=5))
    print(result.final_state)  # total=20

asyncio.run(main())
```

The runner validates the output of `double` against `Doubled`, then validates the input of `add_ten` against `Doubled`, catching any shape mismatches before they propagate.

## What's happening under the hood

For each node in the sequence, the runner:

1. Validates the current state against the node's **input schema**
2. Calls the async node function
3. Validates the return value against the node's **output schema**
4. Records resource usage and checks budgets
5. Saves a **checkpoint** of the output
6. Records a **trace event** for debugging

All of this happens automatically. The next pages show you how to configure each piece.

## Recap

- `StromaRunner.quick()` gets you running with zero configuration
- `@runner.node()` declares contracts and registers them in one step
- Nodes are `async` functions: Pydantic model in, dict out
- `runner.run()` chains nodes sequentially with full instrumentation

**Next: [Adding Contracts](adding-contracts.md)** — learn what happens when validation fails and how to use contracts explicitly.
