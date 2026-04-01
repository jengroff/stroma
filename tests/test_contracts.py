import pytest
from pydantic import BaseModel

from stroma.contracts import ContractRegistry, ContractViolation, NodeContract


class InputModel(BaseModel):
    text: str
    count: int


class OutputModel(BaseModel):
    success: bool
    detail: str


@pytest.fixture
def registry():
    reg = ContractRegistry()
    reg.register(NodeContract(node_id="node1", input_schema=InputModel, output_schema=OutputModel))
    return reg


def test_valid_input(registry):
    raw = {"text": "hello", "count": 1}
    model = registry.validate_input("node1", raw)
    assert isinstance(model, InputModel)
    assert model.model_dump() == raw


def test_valid_output(registry):
    raw = {"success": True, "detail": "ok"}
    model = registry.validate_output("node1", raw)
    assert isinstance(model, OutputModel)
    assert model.model_dump() == raw


def test_input_violation(registry):
    raw = {"text": 123, "count": "one"}
    with pytest.raises(ContractViolation) as exc_info:
        registry.validate_input("node1", raw)
    exc = exc_info.value
    assert exc.node_id == "node1"
    assert exc.direction == "input"
    assert exc.raw == raw
    assert isinstance(exc.errors, list)
    assert any(error["loc"] == ("text",) for error in exc.errors)
    violation_str = str(exc)
    assert "node1" in violation_str
    assert "input" in violation_str
    assert "text" in violation_str or "count" in violation_str


def test_output_violation(registry):
    raw = {"success": "yes", "detail": 5}
    with pytest.raises(ContractViolation) as exc_info:
        registry.validate_output("node1", raw)
    exc = exc_info.value
    assert exc.node_id == "node1"
    assert exc.direction == "output"
    assert exc.raw == raw
    assert isinstance(exc.errors, list)
    assert any(error["loc"] in {("success",), ("detail",)} for error in exc.errors)
    violation_str = str(exc)
    assert "node1" in violation_str
    assert "output" in violation_str


def test_missing_node_raises_key_error():
    registry = ContractRegistry()
    with pytest.raises(KeyError):
        registry.validate_input("missing", {"text": "hi", "count": 1})


def test_round_trip_dict_model_dict(registry):
    raw = {"text": "roundtrip", "count": 42}
    model = registry.validate_input("node1", raw)
    dumped = model.model_dump()
    model2 = InputModel.model_validate(dumped)
    assert dumped == raw
    assert isinstance(model2, InputModel)


def test_contract_violation_str_with_no_errors():
    exc = ContractViolation("mynode", "output", {}, [])
    s = str(exc)
    assert "mynode" in s
    assert "output" in s
