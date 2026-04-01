# Retry & Failures

Not all errors are equal. A timeout might resolve on retry; a schema violation never will. Stroma classifies every exception and applies the right retry strategy automatically.

## Failure classes

Every exception is categorized into one of three classes:

| Class | Meaning | Default behavior |
|-------|---------|------------------|
| `RECOVERABLE` | Transient — likely to succeed on retry | 3 retries, 1s jittered backoff |
| `TERMINAL` | Permanent — retrying won't help | Stop immediately |
| `AMBIGUOUS` | Uncertain — might resolve on retry | 1 retry, 0.5s backoff |

## Built-in classification rules

The runner applies these rules automatically:

| Exception | Classification |
|-----------|---------------|
| `ContractViolation` | `TERMINAL` |
| `BudgetExceeded` | `RECOVERABLE` |
| `TimeoutError` | `RECOVERABLE` |
| `ValueError` | `AMBIGUOUS` |
| Everything else | `AMBIGUOUS` |

## Seeing retries in action

```python
import asyncio
from pydantic import BaseModel
from stroma import StromaRunner


class Input(BaseModel):
    value: int


class Output(BaseModel):
    result: int


runner = StromaRunner.quick()
attempt_count = 0


@runner.node("flaky", input=Input, output=Output)
async def flaky(state: Input) -> dict:
    global attempt_count
    attempt_count += 1
    if attempt_count < 3:  # (1)!
        raise TimeoutError("Service unavailable")
    return {"result": state.value * 2}


async def main():
    result = await runner.run([flaky], Input(value=5))
    print(result.status)       # COMPLETED
    print(result.final_state)  # result=10
    print(f"Took {attempt_count} attempts")  # Took 3 attempts

asyncio.run(main())
```

1. The first two calls raise `TimeoutError`, which is classified as `RECOVERABLE`. The runner retries up to 3 times with jittered backoff. The third attempt succeeds.

## Custom retry policies

Override the defaults by passing a custom `policy_map`:

```python
from stroma import FailureClass, FailurePolicy, StromaRunner

runner = StromaRunner.quick(
    policy_map={
        FailureClass.RECOVERABLE: FailurePolicy(
            max_retries=5,            # (1)!
            backoff_seconds=2.0,      # (2)!
        ),
        FailureClass.TERMINAL: FailurePolicy(max_retries=0),
        FailureClass.AMBIGUOUS: FailurePolicy(
            max_retries=2,
            backoff_seconds=0.5,
        ),
    }
)
```

1. Retry recoverable failures up to 5 times instead of the default 3.
2. Maximum backoff of 2 seconds. The actual delay is randomized between 0 and this value (jittered backoff).

## Custom classifiers

When the built-in rules don't fit, write a custom classifier. Classifiers are functions that inspect the exception and return a `FailureClass` or `None` to defer to the next classifier:

```python
from stroma import FailureClass, StromaRunner


def classify_rate_limit(exc, ctx):  # (1)!
    if "rate limit" in str(exc).lower():
        return FailureClass.RECOVERABLE
    return None  # (2)!


def classify_auth_error(exc, ctx):
    if "unauthorized" in str(exc).lower():
        return FailureClass.TERMINAL
    return None


runner = StromaRunner.quick(
    classifiers=[classify_rate_limit, classify_auth_error],  # (3)!
)
```

1. A classifier receives the exception and a `NodeContext` with `node_id`, `attempt`, and `run_id`.
2. Return `None` to pass to the next classifier. If no classifier matches, built-in rules apply.
3. Classifiers are checked in order. The first non-`None` result wins.

## Per-node policy overrides

The global `policy_map` applies to every node. When a specific node needs different retry behavior — for example, an LLM call that tolerates more retries vs. a fast transform that should fail immediately — use `node_policies`:

```python
from stroma import FailureClass, FailurePolicy, RunConfig

config = RunConfig(
    policy_map={  # (1)!
        FailureClass.RECOVERABLE: FailurePolicy(max_retries=3, backoff_seconds=1.0),
        FailureClass.TERMINAL: FailurePolicy(max_retries=0),
        FailureClass.AMBIGUOUS: FailurePolicy(max_retries=1, backoff_seconds=0.5),
    },
    node_policies={
        "llm_call": {  # (2)!
            FailureClass.RECOVERABLE: FailurePolicy(max_retries=5, backoff_seconds=2.0),
        },
        "fast_transform": {  # (3)!
            FailureClass.RECOVERABLE: FailurePolicy(max_retries=0),
        },
    },
)
```

1. Global defaults — apply to all nodes unless overridden.
2. `llm_call` gets 5 retries with longer backoff for recoverable failures.
3. `fast_transform` gets zero retries — any failure stops immediately.

The lookup order is: per-node override → global `policy_map` → built-in defaults. Only the failure classes you specify in the override are affected; everything else falls through.

## What happens when retries are exhausted

If a recoverable or ambiguous failure exhausts its retry budget, the pipeline stops with `status=PARTIAL`:

```python
async def main():
    result = await runner.run([always_fails], Input(value=1))
    print(result.status)  # PARTIAL — retries exhausted, but not a permanent failure
```

!!! info "PARTIAL vs FAILED"
    - `PARTIAL` means the runner gave up after exhausting retries on a recoverable/ambiguous error. The pipeline might succeed if you try again later.
    - `FAILED` means a terminal error occurred. Retrying won't help — fix the underlying issue.

## Recap

- **Three failure classes**: `RECOVERABLE`, `TERMINAL`, `AMBIGUOUS`
- **Built-in rules** handle common exceptions automatically
- **Custom classifiers** let you override classification for domain-specific errors
- **Retry policies** control max retries and backoff per failure class
- **Per-node overrides** via `node_policies` for node-specific retry behavior
- Exhausted retries produce `PARTIAL` status; terminal failures produce `FAILED`

**Next: [Checkpointing](checkpointing.md)** — save pipeline progress and resume after crashes.
