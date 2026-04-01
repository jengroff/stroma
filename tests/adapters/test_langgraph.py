import asyncio
from typing import Any

import pytest
from pydantic import BaseModel

from stroma.adapters.langgraph import (
    LangGraphAdapter,
    armature_langgraph_node,
    extract_state_dict,
    stroma_langgraph_node,
)
from stroma.contracts import ContractRegistry, ContractViolation, NodeContract


class StateModel(BaseModel):
    x: int


class OutputModel(BaseModel):
    y: int


NODE1_CONTRACT = NodeContract(node_id="node1", input_schema=StateModel, output_schema=OutputModel)


class MockStateGraph:
    def __init__(self) -> None:
        self.nodes: dict[str, Any] = {}

    def add_node(self, name: str, fn: Any) -> None:
        self.nodes[name] = fn

    def execute(self, name: str, state: Any) -> Any:
        result = self.nodes[name](state)
        if asyncio.iscoroutine(result):
            return asyncio.run(result)
        return result


class MockGraphWithPrivateNodes:
    """Graph that uses _nodes instead of nodes."""

    def __init__(self) -> None:
        self._nodes: dict[str, Any] = {}

    def add_node(self, name: str, fn: Any) -> None:
        self._nodes[name] = fn


class MockGraphWithIterNodes:
    """Graph that uses iter_nodes() instead of a dict."""

    def __init__(self) -> None:
        self._store: dict[str, Any] = {}

    def iter_nodes(self):  # type: ignore[no-untyped-def]
        return list(self._store.items())

    def add_node(self, name: str, fn: Any) -> None:
        self._store[name] = fn


@pytest.fixture
def registry():
    reg = ContractRegistry()
    reg.register(NODE1_CONTRACT)
    return reg


def test_wrap_intercepts_node_and_validates(registry):
    graph = MockStateGraph()

    @stroma_langgraph_node("node1", NODE1_CONTRACT)
    async def node1(state: StateModel) -> dict:
        return {"y": state.x + 1}

    graph.add_node("node1", node1)
    adapter = LangGraphAdapter(registry, object())
    wrapped = adapter.wrap(graph)
    output = wrapped.execute("node1", StateModel(x=1))
    assert output == {"y": 2}


def test_wrap_raises_contract_violation_on_bad_output(registry):
    graph = MockStateGraph()

    @stroma_langgraph_node("node1", NODE1_CONTRACT)
    async def node1(state: StateModel) -> dict:
        return {"z": state.x}

    graph.add_node("node1", node1)
    adapter = LangGraphAdapter(registry, object())
    wrapped = adapter.wrap(graph)

    with pytest.raises(ContractViolation):
        wrapped.execute("node1", StateModel(x=1))


def test_wrap_passthrough_on_valid_state(registry):
    graph = MockStateGraph()

    @stroma_langgraph_node("node1", NODE1_CONTRACT)
    async def node1(state: StateModel) -> dict:
        return {"y": state.x * 2}

    graph.add_node("node1", node1)
    adapter = LangGraphAdapter(registry, object())
    wrapped = adapter.wrap(graph)
    assert wrapped.execute("node1", {"x": 2}) == {"y": 4}


def test_backwards_compat_alias():
    """Verify armature_langgraph_node still works."""
    assert armature_langgraph_node is stroma_langgraph_node


# --- extract_state_dict edge cases ---


def test_extract_state_dict_from_dict():
    result = extract_state_dict({"a": 1})
    assert result == {"a": 1}


def test_extract_state_dict_from_basemodel():
    result = extract_state_dict(StateModel(x=5))
    assert result == {"x": 5}


def test_extract_state_dict_from_object_with_dict_method():
    class OldStyle:
        def __init__(self):  # type: ignore[no-untyped-def]
            self.val = 10

        def dict(self):  # type: ignore[no-untyped-def]
            return {"val": self.val}

    result = extract_state_dict(OldStyle())
    assert result == {"val": 10}


def test_extract_state_dict_from_plain_object():
    class Plain:
        def __init__(self):  # type: ignore[no-untyped-def]
            self.a = 1
            self._private = 2

    result = extract_state_dict(Plain())
    assert result == {"a": 1}  # _private excluded


def test_extract_state_dict_raises_for_unsupported_type():
    with pytest.raises(TypeError, match="Unable to extract state dict"):
        extract_state_dict(42)


# --- Graph discovery edge cases ---


@pytest.mark.asyncio
async def test_discover_nodes_from_private_nodes(registry):
    graph = MockGraphWithPrivateNodes()

    @stroma_langgraph_node("node1", NODE1_CONTRACT)
    async def node1(state: StateModel) -> dict:
        return {"y": state.x + 1}

    graph._nodes["node1"] = node1
    adapter = LangGraphAdapter(registry, object())
    adapter.wrap(graph)
    result = await graph._nodes["node1"](StateModel(x=1))
    assert result == {"y": 2}


def test_discover_nodes_from_iter_nodes(registry):
    graph = MockGraphWithIterNodes()

    @stroma_langgraph_node("node1", NODE1_CONTRACT)
    async def node1(state: StateModel) -> dict:
        return {"y": state.x + 1}

    graph._store["node1"] = node1
    adapter = LangGraphAdapter(registry, object())
    adapter.wrap(graph)


def test_discover_nodes_raises_for_unknown_graph(registry):
    class UnknownGraph:
        pass

    adapter = LangGraphAdapter(registry, object())
    with pytest.raises(AttributeError, match="Unable to discover"):
        adapter.wrap(UnknownGraph())


def test_replace_node_raises_for_unknown_graph(registry):
    class NoReplace:
        nodes = None
        _nodes = None

    adapter = LangGraphAdapter(registry, object())
    with pytest.raises(AttributeError, match="Unable to replace"):
        adapter._replace_node(NoReplace(), "test", lambda: None)


def test_wrap_node_raises_type_error_for_undecorated_function(registry):
    adapter = LangGraphAdapter(registry, object())

    async def undecorated(state):
        return {"y": 1}

    with pytest.raises(TypeError, match="undecorated"):
        adapter._wrap_node(undecorated)


def test_wrap_node_error_message_contains_function_name(registry):
    adapter = LangGraphAdapter(registry, object())

    async def my_special_node(state):
        return {}

    with pytest.raises(TypeError) as exc_info:
        adapter._wrap_node(my_special_node)

    assert "my_special_node" in str(exc_info.value)
    assert "stroma_langgraph_node" in str(exc_info.value)
