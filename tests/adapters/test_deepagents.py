import asyncio
from typing import Any
from unittest.mock import patch

import pytest
from pydantic import BaseModel

from stroma.adapters.deepagents import (
    DeepAgentsAdapter,
    stroma_deepagents_node,
)
from stroma.adapters.langgraph import extract_state_dict
from stroma.contracts import ContractRegistry, ContractViolation, NodeContract


class StateModel(BaseModel):
    x: int


class OutputModel(BaseModel):
    y: int


NODE1_CONTRACT = NodeContract(node_id="node1", input_schema=StateModel, output_schema=OutputModel)


class MockDeepAgentGraph:
    def __init__(self) -> None:
        self.nodes: dict[str, Any] = {}

    def add_node(self, name: str, fn: Any) -> None:
        self.nodes[name] = fn

    def execute(self, name: str, state: Any) -> Any:
        result = self.nodes[name](state)
        if asyncio.iscoroutine(result):
            return asyncio.run(result)
        return result


@pytest.fixture
def registry():
    reg = ContractRegistry()
    reg.register(NODE1_CONTRACT)
    return reg


def test_wrap_intercepts_node_and_validates(registry):
    graph = MockDeepAgentGraph()

    @stroma_deepagents_node("node1", NODE1_CONTRACT)
    async def node1(state: StateModel) -> dict:
        return {"y": state.x + 1}

    graph.add_node("node1", node1)
    adapter = DeepAgentsAdapter(registry)
    wrapped = adapter.wrap(graph)
    output = wrapped.execute("node1", StateModel(x=1))
    assert output == {"y": 2}


def test_wrap_raises_contract_violation_on_bad_output(registry):
    graph = MockDeepAgentGraph()

    @stroma_deepagents_node("node1", NODE1_CONTRACT)
    async def node1(state: StateModel) -> dict:
        return {"z": state.x}

    graph.add_node("node1", node1)
    adapter = DeepAgentsAdapter(registry)
    wrapped = adapter.wrap(graph)

    with pytest.raises(ContractViolation):
        wrapped.execute("node1", StateModel(x=1))


def test_undecorated_nodes_left_untouched(registry):
    graph = MockDeepAgentGraph()

    async def plain_node(state: Any) -> dict:
        return {"result": "untouched"}

    @stroma_deepagents_node("node1", NODE1_CONTRACT)
    async def node1(state: StateModel) -> dict:
        return {"y": state.x + 1}

    graph.add_node("plain", plain_node)
    graph.add_node("node1", node1)
    adapter = DeepAgentsAdapter(registry)
    adapter.wrap(graph)

    assert graph.nodes["plain"] is plain_node


def test_cost_tuple_4_shape_parsed(registry):
    graph = MockDeepAgentGraph()

    @stroma_deepagents_node("node1", NODE1_CONTRACT)
    async def node1(state: StateModel) -> Any:
        return ({"y": state.x + 1}, 100, 50, "gpt-4o")

    graph.add_node("node1", node1)
    adapter = DeepAgentsAdapter(registry)
    wrapped = adapter.wrap(graph)
    output = wrapped.execute("node1", StateModel(x=1))
    assert output == {"y": 2}

    summary = adapter.cost_tracker.summary()
    assert "node1" in summary
    usage = summary["node1"]
    assert usage.tokens_used == 150
    assert usage.output_tokens == 50
    assert usage.model == "gpt-4o"
    assert usage.cost_usd > 0


def test_plain_dict_return_records_zero_tokens(registry):
    graph = MockDeepAgentGraph()

    @stroma_deepagents_node("node1", NODE1_CONTRACT)
    async def node1(state: StateModel) -> dict:
        return {"y": state.x + 1}

    graph.add_node("node1", node1)
    adapter = DeepAgentsAdapter(registry)
    wrapped = adapter.wrap(graph)
    output = wrapped.execute("node1", StateModel(x=1))
    assert output == {"y": 2}

    summary = adapter.cost_tracker.summary()
    assert "node1" in summary
    assert summary["node1"].tokens_used == 0
    assert summary["node1"].cost_usd == 0.0


def test_extract_state_dict_all_formats():
    assert extract_state_dict({"a": 1}) == {"a": 1}
    assert extract_state_dict(StateModel(x=5)) == {"x": 5}

    class WithDictMethod:
        def dict(self):  # type: ignore[no-untyped-def]
            return {"val": 10}

    assert extract_state_dict(WithDictMethod()) == {"val": 10}

    class Plain:
        def __init__(self):  # type: ignore[no-untyped-def]
            self.a = 1
            self._private = 2

    assert extract_state_dict(Plain()) == {"a": 1}


def test_wrap_raises_import_error_when_deepagents_missing(registry):
    class FakeDeepAgentGraph(MockDeepAgentGraph):
        __module__ = "deepagents.core"

    graph = FakeDeepAgentGraph()

    @stroma_deepagents_node("node1", NODE1_CONTRACT)
    async def node1(state: StateModel) -> dict:
        return {"y": state.x + 1}

    graph.add_node("node1", node1)
    adapter = DeepAgentsAdapter(registry)

    with (
        patch("importlib.import_module", side_effect=ImportError("no module")),
        pytest.raises(ImportError, match="uv add stroma\\[deepagents\\]"),
    ):
        adapter.wrap(graph)


def test_wrap_passthrough_on_valid_dict_state(registry):
    graph = MockDeepAgentGraph()

    @stroma_deepagents_node("node1", NODE1_CONTRACT)
    async def node1(state: StateModel) -> dict:
        return {"y": state.x * 2}

    graph.add_node("node1", node1)
    adapter = DeepAgentsAdapter(registry)
    wrapped = adapter.wrap(graph)
    assert wrapped.execute("node1", {"x": 2}) == {"y": 4}
