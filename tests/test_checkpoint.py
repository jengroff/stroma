import builtins

import pytest
from pydantic import BaseModel

from stroma.checkpoint import (
    CheckpointKey,
    CheckpointManager,
    InMemoryStore,
    RedisStore,
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


def test_checkpoint_manager_resume_returns_none_on_cold_start():
    manager = CheckpointManager(InMemoryStore())
    assert manager.resume("run1", "node1", SampleState) is None


def test_checkpoint_manager_checkpoint_and_resume():
    store = InMemoryStore()
    manager = CheckpointManager(store)
    state = SampleState(value=42, label="hello")
    manager.checkpoint("run1", "node1", state)
    loaded = manager.resume("run1", "node1", SampleState)
    assert isinstance(loaded, SampleState)
    assert loaded.value == 42


def test_checkpoint_manager_clear():
    store = InMemoryStore()
    manager = CheckpointManager(store)
    manager.checkpoint("run1", "node1", SampleState(value=1, label="a"))
    manager.clear("run1")
    assert manager.resume("run1", "node1", SampleState) is None


def test_schema_ref_and_resolve_round_trip():
    ref = _schema_ref(SampleState)
    assert "SampleState" in ref
    resolved = _resolve_schema(ref)
    assert resolved is SampleState


def test_resolve_schema_rejects_non_basemodel():
    with pytest.raises(TypeError, match="resolved schema is not a BaseModel"):
        _resolve_schema("builtins:dict")


def test_redis_store_raises_import_error_when_redis_missing(monkeypatch):
    real_import = builtins.__import__

    def fake_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name == "redis" or name.startswith("redis."):
            raise ImportError("No module named redis")
        return real_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    with pytest.raises(ImportError, match="redis is required for RedisStore"):
        RedisStore("redis://localhost")
