from __future__ import annotations

import importlib
from typing import Any, NamedTuple, Protocol, runtime_checkable

from pydantic import BaseModel


@runtime_checkable
class CheckpointStore(Protocol):
    """Protocol for checkpoint storage backends.

    Implementations must provide `save`, `load`, and `delete`.
    Optionally implement `save_typed` and `load_typed` for schema-aware
    storage and retrieval.
    """

    def save(self, run_id: str, node_id: str, state: BaseModel) -> None:
        """Persist the state for a given run/node pair."""
        ...

    def load(self, run_id: str, node_id: str) -> BaseModel | None:
        """Load previously saved state, or return `None` if not found."""
        ...

    def delete(self, run_id: str) -> None:
        """Delete all checkpoints for a run."""
        ...


class CheckpointKey(NamedTuple):
    """Composite key for checkpoint lookups."""

    run_id: str
    node_id: str


class InMemoryStore:
    """In-memory checkpoint store for testing and short-lived pipelines.

    State is serialized to JSON internally so that round-trip behavior
    matches persistent backends.

    ## Example

    ```python
    store = InMemoryStore()
    store.save("run-1", "node-1", MyModel(value=42))
    loaded = store.load("run-1", "node-1")
    ```
    """

    def __init__(self) -> None:
        self._states: dict[CheckpointKey, str] = {}
        self._schemas: dict[CheckpointKey, type[BaseModel]] = {}

    def save(self, run_id: str, node_id: str, state: BaseModel) -> None:
        """Save state as JSON, recording the schema type for later deserialization."""
        self._states[CheckpointKey(run_id, node_id)] = state.model_dump_json()
        self._schemas[CheckpointKey(run_id, node_id)] = type(state)

    def load(self, run_id: str, node_id: str) -> BaseModel | None:
        """Load state using the schema that was recorded at save time."""
        key = CheckpointKey(run_id, node_id)
        raw = self._states.get(key)
        schema = self._schemas.get(key)
        if raw is None or schema is None:
            return None
        return schema.model_validate_json(raw)

    def delete(self, run_id: str) -> None:
        """Delete all checkpoints for a run."""
        keys = [key for key in self._states if key.run_id == run_id]
        for key in keys:
            self._states.pop(key, None)
            self._schemas.pop(key, None)

    def save_typed(self, run_id: str, node_id: str, state: BaseModel, schema: type[BaseModel]) -> None:
        """Save state coerced to a specific schema type."""
        if not issubclass(schema, BaseModel):
            raise TypeError("schema must be a BaseModel type")
        if not isinstance(state, schema):
            state = schema.model_validate(state.model_dump())
        self._states[CheckpointKey(run_id, node_id)] = state.model_dump_json()
        self._schemas[CheckpointKey(run_id, node_id)] = schema

    def load_typed(self, run_id: str, node_id: str, schema: type[BaseModel]) -> BaseModel | None:
        """Load state, deserializing with the provided schema regardless of what was saved."""
        raw = self._states.get(CheckpointKey(run_id, node_id))
        if raw is None:
            return None
        return schema.model_validate_json(raw)


def _schema_ref(schema: type[BaseModel]) -> str:
    """Return a `module:qualname` string reference for a schema class."""
    return f"{schema.__module__}:{schema.__qualname__}"


def _resolve_schema(ref: str) -> type[BaseModel]:
    """Resolve a `module:qualname` reference back to a schema class."""
    module_name, qualname = ref.split(":", 1)
    module = importlib.import_module(module_name)
    result: Any = module
    for part in qualname.split("."):
        result = getattr(result, part)
    if not isinstance(result, type) or not issubclass(result, BaseModel):
        raise TypeError("resolved schema is not a BaseModel")
    return result


class RedisStore:
    """Redis-backed checkpoint store for durable, distributed pipelines.

    Requires the `redis` extra: `pip install stroma[redis]`.

    Pass a `redis_url` (e.g. `redis://localhost:6379`) and an optional
    `ttl_seconds` (defaults to 3600) to control key expiration.

    ## Example

    ```python
    store = RedisStore("redis://localhost:6379", ttl_seconds=7200)
    manager = CheckpointManager(store)
    ```
    """

    def __init__(self, redis_url: str, ttl_seconds: int = 3600) -> None:
        try:
            import redis  # ty: ignore[unresolved-import]
        except ImportError as exc:
            raise ImportError("redis is required for RedisStore; install with pip install stroma[redis]") from exc
        self._client = redis.from_url(redis_url, decode_responses=True)
        self._ttl = ttl_seconds

    def _state_key(self, run_id: str, node_id: str) -> str:
        return f"stroma:{run_id}:{node_id}"

    def _schema_key(self, run_id: str, node_id: str) -> str:
        return f"stroma:{run_id}:{node_id}:schema"

    def save(self, run_id: str, node_id: str, state: BaseModel) -> None:
        """Persist state to Redis with TTL."""
        payload = state.model_dump_json()
        self._client.setex(self._state_key(run_id, node_id), self._ttl, payload)
        self._client.setex(self._schema_key(run_id, node_id), self._ttl, _schema_ref(type(state)))

    def load(self, run_id: str, node_id: str) -> BaseModel | None:
        """Load state from Redis, resolving the schema dynamically."""
        payload = self._client.get(self._state_key(run_id, node_id))
        if payload is None:
            return None
        schema_ref = self._client.get(self._schema_key(run_id, node_id))
        if schema_ref is None:
            return None
        schema = _resolve_schema(schema_ref)
        return schema.model_validate_json(payload)

    def delete(self, run_id: str) -> None:
        """Delete all checkpoints for a run using SCAN + pipeline for efficiency."""
        pattern = f"stroma:{run_id}:*"
        pipe = self._client.pipeline()
        for key in self._client.scan_iter(match=pattern):
            pipe.delete(key)
        pipe.execute()

    def save_typed(self, run_id: str, node_id: str, state: BaseModel, schema: type[BaseModel]) -> None:
        """Persist state to Redis using an explicit schema reference."""
        if not issubclass(schema, BaseModel):
            raise TypeError("schema must be a BaseModel type")
        payload = state.model_dump_json()
        self._client.setex(self._state_key(run_id, node_id), self._ttl, payload)
        self._client.setex(self._schema_key(run_id, node_id), self._ttl, _schema_ref(schema))

    def load_typed(self, run_id: str, node_id: str, schema: type[BaseModel]) -> BaseModel | None:
        """Load state from Redis, deserializing with the provided schema."""
        payload = self._client.get(self._state_key(run_id, node_id))
        if payload is None:
            return None
        return schema.model_validate_json(payload)


class CheckpointManager:
    """High-level checkpoint operations: save, resume, and clear.

    Wraps a `CheckpointStore` and handles schema-aware loading when the
    underlying store supports it.

    ## Example

    ```python
    manager = CheckpointManager(InMemoryStore())
    manager.checkpoint("run-1", "node-1", output_state)
    resumed = manager.resume("run-1", "node-1", OutputSchema)
    ```
    """

    def __init__(self, store: CheckpointStore) -> None:
        self._store = store

    def checkpoint(self, run_id: str, node_id: str, state: BaseModel) -> None:
        """Save a checkpoint for the given run/node pair."""
        self._store.save(run_id, node_id, state)

    def resume(self, run_id: str, node_id: str, schema: type[BaseModel]) -> BaseModel | None:
        """Load a checkpoint, coercing to *schema* if the store supports typed loading.

        Returns `None` if no checkpoint exists. Raises `TypeError` if the
        loaded state does not match *schema* and the store does not support
        typed loading.
        """
        load_typed = getattr(self._store, "load_typed", None)
        if load_typed is not None:
            result: BaseModel | None = load_typed(run_id, node_id, schema)
            return result
        result = self._store.load(run_id, node_id)
        if result is None:
            return None
        if not isinstance(result, schema):
            raise TypeError("loaded state does not match schema")
        return result

    def clear(self, run_id: str) -> None:
        """Delete all checkpoints for a run."""
        self._store.delete(run_id)
