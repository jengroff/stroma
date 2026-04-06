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

Nodes report token usage by returning a tuple instead of a plain dict. Four return shapes are supported:

```python
# No usage tracking — tokens=0, cost=$0.00
return {"summary": text}

# Report total tokens only
return ({"summary": text}, 500)

# Report input tokens + model name for automatic cost calculation
return ({"summary": text}, 500, "gpt-4o")

# Full usage: input tokens, output tokens, model
return ({"summary": text}, 400, 100, "gpt-4o")
```

## Model-based cost estimation

When you include a model name in the return tuple, Stroma looks it up in `KNOWN_MODELS` and computes the USD cost automatically:

```python
import asyncio
from pydantic import BaseModel
from stroma import ExecutionBudget, StromaRunner


class Input(BaseModel):
    text: str


class Output(BaseModel):
    summary: str


runner = StromaRunner.quick(
    budget=ExecutionBudget(max_cost_usd=0.10)
)


@runner.node("summarize", input=Input, output=Output)
async def summarize(state: Input) -> tuple:
    # In real code, this would call an LLM
    summary = state.text[:100]
    input_tokens = len(state.text.split())
    output_tokens = len(summary.split())
    return ({"summary": summary}, input_tokens, output_tokens, "gpt-4o")  # (1)!


async def main():
    result = await runner.run(
        [summarize],
        Input(text="A short document to summarize."),
    )
    print(f"Tokens used: {result.total_tokens}")
    print(f"Cost: ${result.total_cost_usd:.6f}")

asyncio.run(main())
```

1. The model string `"gpt-4o"` is looked up in `KNOWN_MODELS` to compute per-token pricing. Unknown models default to $0.00.

Built-in pricing is included for:

| Model | Input (per 1M tokens) | Output (per 1M tokens) |
|-------|----------------------|------------------------|
| `gpt-4o` | $2.50 | $10.00 |
| `gpt-4o-mini` | $0.15 | $0.60 |
| `gpt-4-turbo` | $10.00 | $30.00 |
| `claude-opus-4-6` | $15.00 | $75.00 |
| `claude-sonnet-4-6` | $3.00 | $15.00 |
| `claude-haiku-4-5` | $0.80 | $4.00 |
| `gemini-1.5-pro` | $3.50 | $10.50 |
| `gemini-1.5-flash` | $0.35 | $1.05 |

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

## Model fallback at budget threshold

Instead of failing when costs get high, you can automatically downgrade to a cheaper model. The `with_model_fallback` builder sets a threshold: when cumulative spend reaches a percentage of the budget, subsequent nodes receive a fallback model signal via `ctx["_stroma_model"]`.

```python
runner = (
    StromaRunner.quick()
    .with_budget(cost_usd=1.00)
    .with_model_fallback("gpt-4o", to="gpt-4o-mini", at_budget_pct=0.80)
)
```

When the pipeline has spent 80% of its $1.00 budget, any node that would use `gpt-4o` gets `gpt-4o-mini` instead. Nodes read the signal from the context dict:

```python
@runner.node("summarize", input=Input, output=Output)
async def summarize(state: Input, ctx: dict) -> tuple:
    model = ctx.get("_stroma_model", "gpt-4o")  # (1)!
    # Pass `model` to your LLM client
    return ({"summary": "..."}, input_tokens, output_tokens, model)
```

1. Falls back to `"gpt-4o"` when below threshold (key absent from context).

You can chain multiple fallback rules for different models or thresholds:

```python
runner = (
    StromaRunner.quick()
    .with_budget(cost_usd=5.00)
    .with_model_fallback("gpt-4-turbo", to="gpt-4o", at_budget_pct=0.60)
    .with_model_fallback("gpt-4o", to="gpt-4o-mini", at_budget_pct=0.80)
)
```

## Inspecting cost after a run

The `ExecutionResult` includes total token and cost counters:

```python
result = await runner.run(nodes, initial_state)

print(result.total_tokens)    # aggregate tokens across all nodes
print(result.total_cost_usd)  # aggregate cost in USD across all nodes
```

## Recap

- **`ExecutionBudget`** sets limits on tokens, cost, and latency
- Nodes report usage by returning tuples: `(dict, tokens)`, `(dict, input_tokens, model)`, or `(dict, input_tokens, output_tokens, model)`
- **Model-based pricing** computes `cost_usd` automatically from `KNOWN_MODELS`
- **`BudgetExceeded`** is raised when a limit is crossed (classified as recoverable by default)
- `result.total_tokens` and `result.total_cost_usd` give you post-run totals
- Use `ExecutionBudget.unlimited()` (the default) to disable all limits

**Next: [Tracing & Debugging](tracing.md)** — inspect every execution attempt in detail.
