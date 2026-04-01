import builtins

import pytest
from pydantic import BaseModel

from stroma.checkpoint import (
    AsyncInMemoryStore,
    CheckpointKey,
    CheckpointManager,
    InMemoryStore,
    RedisStore,
    SyncRedisStore,
    _resolve_schema,
    _schema_ref,
)


class SampleState(BaseModel):
    value: int
    label: str


class AltState(BaseModel):
    value: int
    label: str
    extra: str = "default"


def test_in_memory_store_save_load_round_trip():
    store = InMemoryStore()
    state = SampleState(value=7, label="seven")
    store.save("run1", "node1", state)
    loaded = store.load("run1", "node1")
    assert isinstance(loaded, SampleState)
    assert loaded.model_dump() == state.model_dump()


def test_in_memory_store_load_missing_returns_none():
    store = InMemoryStore()
    assert store.load("run1", "node1") is None


def test_in_memory_store_delete_clears_run_keys():
    store = InMemoryStore()
    store.save("run1", "node1", SampleState(value=1, label="a"))
    store.save("run1", "node2", SampleState(value=2, label="b"))
    store.delete("run1")
    assert store.load("run1", "node1") is None
    assert store.load("run1", "node2") is None


def test_in_memory_store_save_typed():
    store = InMemoryStore()
    state = SampleState(value=1, label="test")
    store.save_typed("run1", "node1", state, SampleState)
    loaded = store.load_typed("run1", "node1", SampleState)
    assert isinstance(loaded, SampleState)
    assert loaded.value == 1


def test_in_memory_store_save_typed_coerces_schema():
    store = InMemoryStore()
    state = SampleState(value=1, label="test")
    # Save with AltState schema — should coerce
    store.save_typed("run1", "node1", state, AltState)
    loaded = store.load_typed("run1", "node1", AltState)
    assert isinstance(loaded, AltState)
    assert loaded.extra == "default"


def test_in_memory_store_save_typed_rejects_non_basemodel():
    store = InMemoryStore()
    state = SampleState(value=1, label="test")
    with pytest.raises(TypeError, match="schema must be a BaseModel type"):
        store.save_typed("run1", "node1", state, dict)  # type: ignore[arg-type]


def test_in_memory_store_load_typed_returns_none_on_missing():
    store = InMemoryStore()
    assert store.load_typed("run1", "node1", SampleState) is None


def test_checkpoint_key_is_named_tuple():
    key = CheckpointKey("run1", "node1")
    assert key.run_id == "run1"
    assert key.node_id == "node1"


@pytest.mark.asyncio
async def test_checkpoint_manager_resume_returns_none_on_cold_start():
    manager = CheckpointManager(InMemoryStore())
    assert await manager.resume("run1", "node1", SampleState) is None


@pytest.mark.asyncio
async def test_checkpoint_manager_checkpoint_and_resume():
    store = InMemoryStore()
    manager = CheckpointManager(store)
    state = SampleState(value=42, label="hello")
    await manager.checkpoint("run1", "node1", state)
    loaded = await manager.resume("run1", "node1", SampleState)
    assert isinstance(loaded, SampleState)
    assert loaded.value == 42


@pytest.mark.asyncio
async def test_checkpoint_manager_clear():
    store = InMemoryStore()
    manager = CheckpointManager(store)
    await manager.checkpoint("run1", "node1", SampleState(value=1, label="a"))
    await manager.clear("run1")
    assert await manager.resume("run1", "node1", SampleState) is None


def test_schema_ref_and_resolve_round_trip():
    ref = _schema_ref(SampleState)
    assert "SampleState" in ref
    resolved = _resolve_schema(ref)
    assert resolved is SampleState


def test_resolve_schema_rejects_non_basemodel():
    with pytest.raises(TypeError, match="resolved schema is not a BaseModel"):
        _resolve_schema("builtins:dict")


def test_sync_redis_store_raises_import_error_when_redis_missing(monkeypatch):
    real_import = builtins.__import__

    def fake_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name == "redis" or name.startswith("redis."):
            raise ImportError("No module named redis")
        return real_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    with pytest.raises(ImportError, match="redis is required for SyncRedisStore"):
        SyncRedisStore("redis://localhost")


@pytest.mark.asyncio
async def test_async_in_memory_store_save_load_round_trip():
    store = AsyncInMemoryStore()
    state = SampleState(value=7, label="seven")
    await store.save("run1", "node1", state)
    loaded = await store.load("run1", "node1")
    assert isinstance(loaded, SampleState)
    assert loaded.model_dump() == state.model_dump()


@pytest.mark.asyncio
async def test_async_in_memory_store_load_missing_returns_none():
    store = AsyncInMemoryStore()
    assert await store.load("run1", "node1") is None


@pytest.mark.asyncio
async def test_async_in_memory_store_delete():
    store = AsyncInMemoryStore()
    await store.save("run1", "node1", SampleState(value=1, label="a"))
    await store.delete("run1")
    assert await store.load("run1", "node1") is None


@pytest.mark.asyncio
async def test_checkpoint_manager_async_checkpoint_and_resume():
    store = AsyncInMemoryStore()
    manager = CheckpointManager(store)
    state = SampleState(value=42, label="hello")
    await manager.checkpoint("run1", "node1", state)
    loaded = await manager.resume("run1", "node1", SampleState)
    assert isinstance(loaded, SampleState)
    assert loaded.value == 42


@pytest.mark.asyncio
async def test_checkpoint_manager_async_clear():
    store = AsyncInMemoryStore()
    manager = CheckpointManager(store)
    await manager.checkpoint("run1", "node1", SampleState(value=1, label="a"))
    await manager.clear("run1")
    assert await manager.resume("run1", "node1", SampleState) is None


@pytest.mark.asyncio
async def test_checkpoint_manager_sync_store_resume_without_load_typed():
    """Cover the sync branch of resume when the store lacks load_typed."""

    class MinimalSyncStore:
        def __init__(self) -> None:
            self._data: dict[tuple[str, str], BaseModel] = {}

        def save(self, run_id: str, node_id: str, state: BaseModel) -> None:
            self._data[(run_id, node_id)] = state

        def load(self, run_id: str, node_id: str) -> BaseModel | None:
            return self._data.get((run_id, node_id))

        def delete(self, run_id: str) -> None:
            keys = [k for k in self._data if k[0] == run_id]
            for k in keys:
                del self._data[k]

    store = MinimalSyncStore()
    manager = CheckpointManager(store)
    state = SampleState(value=99, label="test")
    await manager.checkpoint("run1", "node1", state)
    loaded = await manager.resume("run1", "node1", SampleState)
    assert isinstance(loaded, SampleState)
    assert loaded.value == 99


@pytest.mark.asyncio
async def test_redis_store_async_raises_import_error_when_redis_missing(monkeypatch):
    real_import = builtins.__import__

    def fake_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name == "redis.asyncio" or name == "redis":
            raise ImportError("No module named redis")
        return real_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    with pytest.raises(ImportError, match="redis is required"):
        RedisStore("redis://localhost")
