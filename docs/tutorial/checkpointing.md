# Checkpointing

After each successful node, the runner saves the output state as a checkpoint. If a pipeline fails partway through, you can resume from the last checkpoint instead of re-running everything.

## How it works

```
node1 ✓ → [checkpoint] → node2 ✓ → [checkpoint] → node3 ✗ (fails)
                                                      ↑
                                          resume here on next run
```

The runner automatically checkpoints after every successful node execution. You don't need to add any code for this — it happens by default.

## Resuming a failed pipeline

Use the same `run_id` and set `resume_from` to the node that failed:

```python
import asyncio
from pydantic import BaseModel
from stroma import (
    AsyncInMemoryStore,
    CheckpointManager,
    ContractRegistry,
    NodeContract,
    RunConfig,
    StromaRunner,
    stroma_node,
)


class State(BaseModel):
    value: int


class Processed(BaseModel):
    result: int


class Final(BaseModel):
    total: int


registry = ContractRegistry()

c1 = NodeContract(node_id="step1", input_schema=State, output_schema=Processed)
c2 = NodeContract(node_id="step2", input_schema=Processed, output_schema=Final)
registry.register(c1)
registry.register(c2)

store = AsyncInMemoryStore()  # (1)!
checkpoint_mgr = CheckpointManager(store)

fail_once = True


@stroma_node("step1", c1)
async def step1(state: State) -> dict:
    print("Running step1")
    return {"result": state.value * 10}


@stroma_node("step2", c2)
async def step2(state: Processed) -> dict:
    global fail_once
    if fail_once:
        fail_once = False
        raise TimeoutError("Simulated failure")  # (2)!
    print("Running step2")
    return {"total": state.result + 1}


async def main():
    # First run — step1 succeeds, step2 fails
    config1 = RunConfig(run_id="my-run")
    runner1 = StromaRunner(registry, checkpoint_mgr, config1)
    result1 = await runner1.run([step1, step2], State(value=5))
    print(f"First run: {result1.status}")  # PARTIAL

    # Resume — step1 is skipped, its output loaded from checkpoint
    config2 = RunConfig(run_id="my-run", resume_from="step2")  # (3)!
    runner2 = StromaRunner(registry, checkpoint_mgr, config2)
    result2 = await runner2.run([step1, step2], State(value=5))
    print(f"Resumed: {result2.status}")    # RESUMED
    print(result2.final_state)             # total=51

asyncio.run(main())
```

1. The store must be shared across runs. `AsyncInMemoryStore` is the default for `StromaRunner.quick()`. For production, use `RedisStore` so checkpoints survive process restarts.
2. `step2` fails on the first run. After exhausting retries, the pipeline returns `PARTIAL`.
3. `resume_from="step2"` tells the runner to skip `step1` and load its checkpoint output instead.

!!! warning
    `AsyncInMemoryStore` and `InMemoryStore` lose data when the process exits. For real resume-across-crashes, use `RedisStore`.

## Redis-backed checkpointing

For durable checkpointing that survives process restarts:

```python
from stroma import RedisStore, CheckpointManager

store = RedisStore(
    redis_url="redis://localhost:6379",
    ttl_seconds=3600,  # (1)!
)
checkpoint_mgr = CheckpointManager(store)
```

1. Checkpoints expire after 1 hour by default. Adjust based on your pipeline's expected recovery window.

`RedisStore` is async — it uses `redis.asyncio` under the hood and won't block the event loop.

Install the Redis extra:

```bash
uv add stroma[redis]
```

!!! info "Sync Redis"
    If you need a synchronous Redis store (e.g., for non-async code), use `SyncRedisStore` instead. It has the same API but uses the synchronous `redis-py` client.

## Storage backends

| Backend | Interface | Persistence | Use case |
|---------|-----------|-------------|----------|
| `InMemoryStore` | sync | In-process only | Testing with sync stores |
| `AsyncInMemoryStore` | async | In-process only | Testing (default for `quick()`) |
| `RedisStore` | async | Survives restarts | Production |
| `SyncRedisStore` | sync | Survives restarts | Legacy/sync environments |

## Custom storage backends

Implement `AsyncCheckpointStore` (async) or `CheckpointStore` (sync) to use any storage backend:

=== "Async backend"

    ```python
    from pydantic import BaseModel


    class PostgresStore:  # (1)!
        async def save(self, run_id: str, node_id: str, state: BaseModel) -> None:
            ...

        async def load(self, run_id: str, node_id: str) -> BaseModel | None:
            ...

        async def delete(self, run_id: str) -> None:
            ...
    ```

    1. No need to subclass anything — just implement `save`, `load`, and `delete` as async methods. Stroma uses structural typing (Python protocols).

=== "Sync backend"

    ```python
    from pydantic import BaseModel


    class PostgresStore:
        def save(self, run_id: str, node_id: str, state: BaseModel) -> None:
            ...

        def load(self, run_id: str, node_id: str) -> BaseModel | None:
            ...

        def delete(self, run_id: str) -> None:
            ...
    ```

The `CheckpointManager` auto-detects whether the store is sync or async and handles both transparently.

## Recap

- The runner **checkpoints automatically** after every successful node
- Resume with the **same `run_id`** and `resume_from="node_id"`
- **`AsyncInMemoryStore`** for testing (default), **`RedisStore`** for production
- **`InMemoryStore`** and **`SyncRedisStore`** available for sync use cases
- Implement **`AsyncCheckpointStore`** or **`CheckpointStore`** for custom backends

**Next: [Cost Control](cost-control.md)** — set budgets on tokens, dollars, and latency.
