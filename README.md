# Stroma

**Reliability primitives for agent pipelines.**

```python
from pydantic import BaseModel
from stroma import StromaRunner

class Input(BaseModel):
    value: int

class Output(BaseModel):
    result: int

runner = StromaRunner.quick()

@runner.node("double", input=Input, output=Output)
async def double(state: Input) -> dict:
    return {"result": state.value * 2}

result = await runner.run([double], Input(value=5))
print(result.final_state)  # result=10
```

## Install

```bash
pip install stroma
```

Optional extras:

```bash
pip install stroma[redis]       # Redis-backed checkpointing
pip install stroma[langgraph]   # LangGraph adapter
```

## What You Get

- **Contracts** — Pydantic-based input/output validation at every node boundary
- **Failure classification** — automatic categorization of errors as recoverable, terminal, or ambiguous
- **Retry policies** — configurable retries with jittered backoff per failure class
- **Checkpointing** — save and resume pipelines across crashes (in-memory or Redis)
- **Cost tracking** — enforce token, dollar, and latency budgets across your pipeline
- **Execution tracing** — full record of every node attempt, with diffing and JSON export
- **LangGraph adapter** — apply contracts to existing LangGraph graphs
- **Framework-agnostic** — works with any async Python code, no framework lock-in

## Documentation

Full documentation including a tutorial and API reference is available at the [docs site](https://jengroff.github.io/stroma).

## Development

```bash
pip install -e ".[dev]"
uv run pytest tests/ -v --cov=stroma --cov-fail-under=90
```

## License

MIT
