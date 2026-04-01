import json
from datetime import UTC, datetime

from pydantic import BaseModel

from stroma.failures import FailureClass
from stroma.trace import ExecutionResult, ExecutionTrace, RunStatus, TraceEvent


class FinalState(BaseModel):
    status: str


def _make_event(node_id="node1", run_id="run1", attempt=1, **kwargs):
    defaults = dict(
        node_id=node_id,
        run_id=run_id,
        attempt=attempt,
        timestamp_utc=datetime.now(UTC),
        input_state={},
        output_state=None,
        duration_ms=10,
    )
    defaults.update(kwargs)
    return TraceEvent(**defaults)


def test_append_and_iterate():
    trace = ExecutionTrace()
    event = _make_event(input_state={"foo": "bar"}, output_state={"baz": 1}, duration_ms=50)
    trace.append(event)
    assert len(trace) == 1
    assert next(iter(trace)) is event


def test_events_for_filters_by_node():
    trace = ExecutionTrace()
    trace.append(_make_event(node_id="a"))
    trace.append(_make_event(node_id="b"))
    trace.append(_make_event(node_id="a", attempt=2))
    assert len(trace.events_for("a")) == 2
    assert len(trace.events_for("b")) == 1
    assert len(trace.events_for("c")) == 0


def test_failures_filters_correctly():
    trace = ExecutionTrace()
    trace.append(_make_event(failure=FailureClass.TERMINAL, failure_message="oops"))
    trace.append(_make_event(attempt=2, output_state={"ok": True}, duration_ms=20))
    failures = trace.failures()
    assert len(failures) == 1
    assert failures[0].failure == FailureClass.TERMINAL


def test_diff_detects_node_id_mismatch():
    left = ExecutionTrace()
    right = ExecutionTrace()
    left.append(_make_event(node_id="node1", input_state={"a": 1}))
    right.append(_make_event(node_id="node2", input_state={"a": 1}))
    diffs = left.diff(right)
    assert any("Missing event in other trace: node1 attempt 1" in item for item in diffs)
    assert any("Extra event in other trace: node2 attempt 1" in item for item in diffs)


def test_diff_ignores_timestamp_and_duration():
    left = ExecutionTrace()
    right = ExecutionTrace()
    left.append(_make_event(input_state={"x": 1}, output_state={"y": 2}, duration_ms=10))
    right.append(_make_event(input_state={"x": 1}, output_state={"y": 2}, duration_ms=999))
    diffs = left.diff(right)
    assert diffs == []


def test_diff_detects_output_state_difference():
    left = ExecutionTrace()
    right = ExecutionTrace()
    left.append(_make_event(output_state={"a": 1}))
    right.append(_make_event(output_state={"a": 2}))
    diffs = left.diff(right)
    assert len(diffs) == 1
    assert "Difference" in diffs[0]


def test_diff_detects_extra_event():
    left = ExecutionTrace()
    right = ExecutionTrace()
    left.append(_make_event(attempt=1))
    left.append(_make_event(attempt=2))
    right.append(_make_event(attempt=1))
    diffs = left.diff(right)
    assert any("Missing" in d for d in diffs)


def test_to_json_round_trips_with_base_model_in_state():
    trace = ExecutionTrace()
    trace.append(_make_event(input_state={"state": FinalState(status="ok")}))
    payload = trace.to_json()
    loaded = json.loads(payload)
    assert isinstance(loaded, list)
    assert loaded[0]["node_id"] == "node1"
    assert loaded[0]["input_state"]["state"]["status"] == "ok"


def test_to_json_handles_datetime_and_dataclass():
    trace = ExecutionTrace()
    trace.append(_make_event())
    payload = trace.to_json()
    loaded = json.loads(payload)
    assert "timestamp_utc" in loaded[0]
    # datetime should be ISO format string
    assert isinstance(loaded[0]["timestamp_utc"], str)


def test_replay_yields_events_in_order():
    trace = ExecutionTrace()
    event1 = _make_event(attempt=1, duration_ms=5)
    event2 = _make_event(attempt=2, duration_ms=6)
    trace.append(event1)
    trace.append(event2)
    assert list(trace.replay()) == [event1, event2]


def test_execution_result_dataclass():
    trace = ExecutionTrace()
    result = ExecutionResult(
        run_id="run1",
        status=RunStatus.COMPLETED,
        final_state=FinalState(status="done"),
        trace=trace,
        total_cost_usd=0.0,
        total_tokens=0,
    )
    assert result.run_id == "run1"
    assert result.status == RunStatus.COMPLETED
    assert result.final_state.status == "done"


def test_run_status_values():
    assert RunStatus.COMPLETED == "COMPLETED"
    assert RunStatus.FAILED == "FAILED"
    assert RunStatus.PARTIAL == "PARTIAL"
    assert RunStatus.RESUMED == "RESUMED"
