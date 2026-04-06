import sys
import types

import pytest
from pydantic import BaseModel

# Mock crewai before importing the adapter
crewai_mock = types.ModuleType("crewai")
sys.modules["crewai"] = crewai_mock

from stroma.adapters.base import extract_state_dict  # noqa: E402
from stroma.adapters.crewai import CrewAIAdapter, stroma_crewai_step  # noqa: E402
from stroma.contracts import ContractRegistry, ContractViolation, NodeContract  # noqa: E402


class InputState(BaseModel):
    query: str


class OutputState(BaseModel):
    answer: str


STEP_CONTRACT = NodeContract(node_id="respond", input_schema=InputState, output_schema=OutputState)


@pytest.fixture
def registry():
    reg = ContractRegistry()
    reg.register(STEP_CONTRACT)
    return reg


# --- stroma_crewai_step decorator ---


def test_decorator_attaches_node_id():
    @stroma_crewai_step("respond", STEP_CONTRACT)
    def my_step(self):
        pass

    assert my_step._stroma_node_id == "respond"


def test_decorator_attaches_contract():
    @stroma_crewai_step("respond", STEP_CONTRACT)
    def my_step(self):
        pass

    assert my_step._stroma_contract is STEP_CONTRACT


# --- CrewAIAdapter.wrap() discovery ---


def test_wrap_discovers_decorated_methods(registry):
    class FakeFlow:
        def __init__(self):  # type: ignore[no-untyped-def]
            self.state = {"query": "hello"}

        @stroma_crewai_step("respond", STEP_CONTRACT)
        def respond(self):
            return {"answer": "world"}

    flow = FakeFlow()
    adapter = CrewAIAdapter(registry)
    adapter.wrap(flow)

    assert hasattr(flow.respond, "_stroma_node_id")
    assert flow.respond._stroma_node_id == "respond"


def test_wrap_ignores_undecorated_methods(registry):
    class FakeFlow:
        def __init__(self):  # type: ignore[no-untyped-def]
            self.state = {"query": "hello"}

        @stroma_crewai_step("respond", STEP_CONTRACT)
        def respond(self):
            return {"answer": "world"}

        def undecorated(self):
            return "ignored"

    flow = FakeFlow()
    original_undecorated = flow.undecorated
    adapter = CrewAIAdapter(registry)
    adapter.wrap(flow)

    assert flow.undecorated == original_undecorated


# --- Contract validation ---


async def test_valid_output_passes_and_merges_dict_state(registry):
    class FakeFlow:
        def __init__(self):  # type: ignore[no-untyped-def]
            self.state = {"query": "hello"}

        @stroma_crewai_step("respond", STEP_CONTRACT)
        def respond(self):
            return {"answer": "world"}

    flow = FakeFlow()
    adapter = CrewAIAdapter(registry)
    adapter.wrap(flow)

    await flow.respond()
    assert flow.state["answer"] == "world"


async def test_valid_output_merges_into_pydantic_state(registry):
    class FlowState(BaseModel):
        query: str = ""
        answer: str = ""

    class FakeFlow:
        state = FlowState(query="hello")

        @stroma_crewai_step("respond", STEP_CONTRACT)
        def respond(self):
            return {"answer": "world"}

    flow = FakeFlow()
    adapter = CrewAIAdapter(registry)
    adapter.wrap(flow)

    await flow.respond()
    assert flow.state.answer == "world"


async def test_invalid_output_raises_contract_violation(registry):
    class FakeFlow:
        def __init__(self):  # type: ignore[no-untyped-def]
            self.state = {"query": "hello"}

        @stroma_crewai_step("respond", STEP_CONTRACT)
        def respond(self):
            return {"wrong_field": "oops"}

    flow = FakeFlow()
    adapter = CrewAIAdapter(registry)
    adapter.wrap(flow)

    with pytest.raises(ContractViolation):
        await flow.respond()


async def test_invalid_input_raises_contract_violation(registry):
    class FakeFlow:
        def __init__(self):  # type: ignore[no-untyped-def]
            self.state = {"bad_field": "no query here"}

        @stroma_crewai_step("respond", STEP_CONTRACT)
        def respond(self):
            return {"answer": "world"}

    flow = FakeFlow()
    adapter = CrewAIAdapter(registry)
    adapter.wrap(flow)

    with pytest.raises(ContractViolation):
        await flow.respond()


async def test_async_step_method(registry):
    class FakeFlow:
        def __init__(self):  # type: ignore[no-untyped-def]
            self.state = {"query": "hello"}

        @stroma_crewai_step("respond", STEP_CONTRACT)
        async def respond(self):
            return {"answer": "async world"}

    flow = FakeFlow()
    adapter = CrewAIAdapter(registry)
    adapter.wrap(flow)

    await flow.respond()
    assert flow.state["answer"] == "async world"


# --- extract_state_dict from base.py ---


def test_extract_state_dict_importable_from_base():
    """extract_state_dict is importable from stroma.adapters.base."""
    from stroma.adapters.base import extract_state_dict as base_fn
    from stroma.adapters.langgraph import extract_state_dict as lg_fn

    assert base_fn is lg_fn


def test_extract_state_dict_handles_dict():
    assert extract_state_dict({"a": 1}) == {"a": 1}


def test_extract_state_dict_handles_basemodel():
    assert extract_state_dict(InputState(query="hi")) == {"query": "hi"}


def test_extract_state_dict_handles_dot_dict():
    class Legacy:
        def dict(self):
            return {"val": 42}

    assert extract_state_dict(Legacy()) == {"val": 42}


def test_extract_state_dict_handles_dunder_dict():
    class Plain:
        def __init__(self):
            self.x = 1
            self._private = 2

    assert extract_state_dict(Plain()) == {"x": 1}
