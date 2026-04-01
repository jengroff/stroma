# Cost Control

LLM pipelines can get expensive fast. Stroma tracks three resource dimensions and lets you set hard limits on any of them.

## The three dimensions

| Dimension | What it tracks | Unit |
|-----------|---------------|------|
| **Tokens** | Total LLM tokens consumed | integer |
| **Cost** | Total monetary spend | USD (float) |
| **Latency** | Total wall-clock time | milliseconds |

## Setting a budget

```python
from stroma import ExecutionBudget, StromaRunner

runner = StromaRunner.quick(
    budget=ExecutionBudget(
        max_tokens_total=10_000,   # (1)!
        max_cost_usd=0.50,        # (2)!
        max_latency_ms=30_000,    # (3)!
    )
)
```

1. Stop if total tokens across all nodes exceed 10,000.
2. Stop if total cost exceeds $0.50.
3. Stop if total wall-clock time exceeds 30 seconds.

Set any combination — `None` means no limit on that dimension. `ExecutionBudget.unlimited()` (the default) sets all three to `None`.

## Reporting token usage

Nodes report token usage by returning a tuple of `(output_dict, tokens_used)`:

```python
import asyncio
from pydantic import BaseModel
from stroma import ExecutionBudget, StromaRunner


class Input(BaseModel):
    text: str


class Output(BaseModel):
    summary: str


runner = StromaRunner.quick(
    budget=ExecutionBudget(max_tokens_total=1_000)
)


@runner.node("summarize", input=Input, output=Output)
async def summarize(state: Input) -> tuple:  # (1)!
    # In real code, this would call an LLM
    summary = state.text[:100]
    tokens_used = len(state.text.split())
    return ({"summary": summary}, tokens_used)  # (2)!


async def main():
    result = await runner.run(
        [summarize],
        Input(text="A short document to summarize."),
    )
    print(f"Tokens used: {result.total_tokens}")
    print(f"Cost: ${result.total_cost_usd:.4f}")

asyncio.run(main())
```

1. Return type annotation is `tuple` instead of `dict` when reporting tokens.
2. The second element of the tuple is the token count as an integer. If you return just a dict, token usage is recorded as 0.

## What happens when a budget is exceeded

When cumulative usage crosses a budget limit, `BudgetExceeded` is raised. By default this is classified as `RECOVERABLE` — the runner will retry (useful if the budget was close and a cheaper retry succeeds).

```python
async def main():
    result = await runner.run([expensive_node], Input(text="..." * 10_000))
    if result.status != "COMPLETED":
        print(f"Budget exceeded! Used {result.total_tokens} tokens")
```

!!! tip
    If you want budget violations to be terminal (no retries), add a custom classifier:

    ```python
    from stroma import FailureClass
    from stroma.cost import BudgetExceeded

    def budget_is_terminal(exc, ctx):
        if isinstance(exc, BudgetExceeded):
            return FailureClass.TERMINAL
        return None

    runner = StromaRunner.quick(classifiers=[budget_is_terminal])
    ```

## Inspecting cost after a run

The `ExecutionResult` includes total token and cost counters:

```python
result = await runner.run(nodes, initial_state)

print(result.total_tokens)    # aggregate tokens across all nodes
print(result.total_cost_usd)  # aggregate cost across all nodes
```

!!! info
    Latency is tracked automatically from wall-clock time. Token usage comes from your node's return value. Cost in USD is currently recorded as 0.0 — to track actual costs, record them in your node logic and include them in a custom `CostTracker`.

## Recap

- **`ExecutionBudget`** sets limits on tokens, cost, and latency
- Nodes report tokens by returning `(dict, tokens_used)` tuples
- **`BudgetExceeded`** is raised when a limit is crossed (classified as recoverable by default)
- `result.total_tokens` and `result.total_cost_usd` give you post-run totals
- Use `ExecutionBudget.unlimited()` (the default) to disable all limits

**Next: [Tracing & Debugging](tracing.md)** — inspect every execution attempt in detail.
