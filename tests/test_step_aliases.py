from datetime import UTC, datetime

from pydantic import BaseModel

from stroma.contracts import NodeContract, StepContract, StepViolation
from stroma.cost import NodeUsage, StepUsage
from stroma.failures import NodeContext, StepContext
from stroma.runner import NodeHooks, StepHooks, stroma_node, stroma_step
from stroma.trace import FailureClass, TraceEvent


def test_step_contract_is_node_contract():
    assert StepContract is NodeContract


def test_step_violation_is_contract_violation():
    from stroma.contracts import ContractViolation

    assert StepViolation is ContractViolation


def test_step_usage_is_node_usage():
    assert StepUsage is NodeUsage


def test_step_context_is_node_context():
    assert StepContext is NodeContext


def test_step_hooks_is_node_hooks():
    assert StepHooks is NodeHooks


def test_stroma_step_decorator_attaches_metadata():
    class In(BaseModel):
        x: int

    class Out(BaseModel):
        y: int

    contract = NodeContract(node_id="add", input_schema=In, output_schema=Out)

    @stroma_step("add", contract)
    async def add(state: In) -> dict:
        return {"y": state.x + 1}

    assert add._stroma_node_id == "add"
    assert add._stroma_contract is contract


def test_stroma_step_produces_same_result_as_stroma_node():
    class In(BaseModel):
        x: int

    class Out(BaseModel):
        y: int

    contract = NodeContract(node_id="double", input_schema=In, output_schema=Out)

    @stroma_node("double", contract)
    async def via_node(state: In) -> dict:
        return {"y": state.x * 2}

    @stroma_step("double", contract)
    async def via_step(state: In) -> dict:
        return {"y": state.x * 2}

    assert via_node._stroma_node_id == via_step._stroma_node_id
    assert via_node._stroma_contract is via_step._stroma_contract


def test_trace_event_step_id_property():
    event = TraceEvent(
        node_id="extract",
        run_id="run-1",
        attempt=1,
        timestamp_utc=datetime.now(UTC),
        input_state={"x": 1},
        output_state={"y": 2},
        duration_ms=100,
    )
    assert event.step_id == "extract"
    assert event.step_id == event.node_id


def test_trace_event_step_id_with_failure():
    event = TraceEvent(
        node_id="flaky",
        run_id="run-2",
        attempt=3,
        timestamp_utc=datetime.now(UTC),
        input_state={},
        output_state=None,
        duration_ms=50,
        failure=FailureClass.RECOVERABLE,
        failure_message="timeout",
    )
    assert event.step_id == "flaky"


def test_all_aliases_importable_from_top_level():
    from stroma import (
        StepContext,
        StepContract,
        StepHooks,
        StepUsage,
        StepViolation,
        stroma_step,
    )

    assert StepContract is not None
    assert StepViolation is not None
    assert StepUsage is not None
    assert StepContext is not None
    assert StepHooks is not None
    assert stroma_step is not None
