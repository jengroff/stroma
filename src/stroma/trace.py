"""Execution tracing and result types for pipeline runs."""

import dataclasses
import json
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel

from stroma.failures import FailureClass


@dataclass
class TraceEvent:
    """A single recorded execution attempt for a node.

    Attributes:
        node_id: The node that was executed.
        run_id: The pipeline run this event belongs to.
        attempt: The attempt number (1-based).
        timestamp_utc: When the attempt started.
        input_state: The input dict passed to the node.
        output_state: The output dict returned, or ``None`` on failure.
        duration_ms: Wall-clock duration in milliseconds.
        failure: The failure classification, or ``None`` on success.
        failure_message: Human-readable failure description, or ``None`` on success.
    """

    node_id: str
    run_id: str
    attempt: int
    timestamp_utc: datetime
    input_state: dict[str, Any]
    output_state: dict[str, Any] | None
    duration_ms: int
    failure: FailureClass | None = None
    failure_message: str | None = None


class ExecutionTrace:
    """Ordered collection of :class:`TraceEvent` instances for a pipeline run.

    Provides filtering, diffing, serialization, and iteration over events.

    Example::

        result = await runner.run(nodes, state)

        # Inspect failures
        for event in result.trace.failures():
            print(f"{event.node_id}: {event.failure_message}")

        # Compare two traces
        diffs = trace_a.diff(trace_b)

        # Export to JSON
        json_str = result.trace.to_json()
    """

    def __init__(self) -> None:
        self._events: list[TraceEvent] = []

    def append(self, event: TraceEvent) -> None:
        """Append a trace event."""
        self._events.append(event)

    def events_for(self, node_id: str) -> list[TraceEvent]:
        """Return all events for the given node."""
        return [event for event in self._events if event.node_id == node_id]

    def failures(self) -> list[TraceEvent]:
        """Return all events that represent failures."""
        return [event for event in self._events if event.failure is not None]

    def to_json(self) -> str:
        """Serialize all events to a JSON string."""

        def default(value: Any) -> Any:
            if isinstance(value, BaseModel):
                return value.model_dump()
            if isinstance(value, datetime):
                return value.isoformat()
            if dataclasses.is_dataclass(value) and not isinstance(value, type):
                return dataclasses.asdict(value)
            raise TypeError(f"Object of type {type(value).__name__} is not JSON serializable")

        return json.dumps([dataclasses.asdict(event) for event in self._events], default=default)

    def diff(self, other: "ExecutionTrace") -> list[str]:
        """Compare this trace against *other*, ignoring timestamps and durations.

        Returns a list of human-readable difference descriptions. An empty
        list means the traces are logically equivalent.
        """
        left = {(event.node_id, event.attempt): event for event in self._events}
        right = {(event.node_id, event.attempt): event for event in other._events}
        differences: list[str] = []
        for key in sorted(set(left) | set(right)):
            if key not in left:
                differences.append(f"Extra event in other trace: {key[0]} attempt {key[1]}")
                continue
            if key not in right:
                differences.append(f"Missing event in other trace: {key[0]} attempt {key[1]}")
                continue
            left_evt, right_evt = left[key], right[key]
            logical_diff = (
                left_evt.node_id != right_evt.node_id
                or left_evt.run_id != right_evt.run_id
                or left_evt.attempt != right_evt.attempt
                or left_evt.input_state != right_evt.input_state
                or left_evt.output_state != right_evt.output_state
                or left_evt.failure != right_evt.failure
                or left_evt.failure_message != right_evt.failure_message
            )
            if logical_diff:
                differences.append(
                    f"Difference for {key[0]} attempt {key[1]}: {left_evt} != {right_evt}"
                )
        return differences

    def replay(self) -> Iterator[TraceEvent]:
        """Yield events in the order they were recorded."""
        yield from self._events

    def __len__(self) -> int:
        return len(self._events)

    def __iter__(self) -> Iterator[TraceEvent]:
        return iter(self._events)


class RunStatus(StrEnum):
    """Terminal status of a pipeline run.

    - ``COMPLETED``: All nodes executed successfully.
    - ``FAILED``: A terminal failure stopped the pipeline.
    - ``PARTIAL``: Retries were exhausted on a recoverable/ambiguous failure.
    - ``RESUMED``: The pipeline completed after resuming from a checkpoint.
    """

    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    PARTIAL = "PARTIAL"
    RESUMED = "RESUMED"


@dataclass
class ExecutionResult:
    """Final output of a pipeline run.

    Attributes:
        run_id: The unique identifier for this run.
        status: Terminal status of the run.
        final_state: The last valid state produced, or the initial state on early failure.
        trace: Complete execution trace with all attempts.
        total_cost_usd: Cumulative cost in USD across all nodes.
        total_tokens: Cumulative token usage across all nodes.
    """

    run_id: str
    status: RunStatus
    final_state: BaseModel | None
    trace: ExecutionTrace
    total_cost_usd: float
    total_tokens: int
