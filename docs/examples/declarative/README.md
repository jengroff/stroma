# Declarative / Compiler Example

## Paradigm

Declarative / compiler. You describe what you want (DSPy Signatures), the framework optimizes prompts and few-shot examples to get there. The specific reliability problem: optimizer mutations can silently break output shape without any runtime error in raw DSPy — a compiled module might return fields the downstream code doesn't expect.

## What the pipeline does

A two-step QA pipeline using DSPy. The first module retrieves context for a question, the second generates an answer using chain-of-thought reasoning. Both modules use a `DummyLM` for deterministic output without API keys. The example demonstrates both a successful run and a broken run where the retrieve module returns an unexpected field name — caught immediately by contract validation.

## Dependencies

Requires the examples extra:

```bash
uv add stroma[examples]
```

## Running

```bash
uv run python docs/examples/declarative/agent.py
uv run python docs/examples/declarative/with_stroma.py
```

## Comparison

| | Without Stroma | With Stroma |
|---|---|---|
| Silent output shape breakage | Optimizer mutates module output, downstream code gets `None` or `KeyError` | `ContractViolation` raised at the module boundary with field-level error details |
| Cost visibility across module calls | None | Per-module token and cost tracking via `ReliabilityContext` |
| Per-module audit trail | None | Full `ExecutionTrace` with per-module attempt records |

## Stroma primitives used

- **`execute_step()`** — wraps each DSPy module call directly, without requiring a runner or framework adapter.
- **`NodeContract`** — defines the expected input/output schema for each module, catching shape mismatches from optimization or prompt mutation.
- **`ContractViolation`** — fires as `TERMINAL` when a module returns fields that don't match the declared output schema, preventing silent downstream failures.
