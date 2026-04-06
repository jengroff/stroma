from collections.abc import Callable
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

from pydantic import BaseModel

from stroma.contracts import NodeContract

if TYPE_CHECKING:
    from stroma.middleware import ReliabilityContext


@runtime_checkable
class FrameworkAdapter(Protocol):
    """Protocol for graph-based framework adapters (LangGraph, CrewAI Flows).

    Implementations provide two capabilities: wrapping an entire framework
    graph with contract validation, and producing a decorator that attaches
    stroma metadata to individual node functions.
    """

    def wrap(self, graph: Any) -> Any:
        """Attach contract validation to a framework graph or flow instance."""
        ...

    def node_decorator(self, node_id: str, contract: NodeContract) -> Callable[..., Any]:
        """Return a decorator that attaches stroma metadata to a framework node function."""
        ...


@runtime_checkable
class StepInterceptor(Protocol):
    """Protocol for adapters that wrap individual step functions with reliability middleware.

    Unlike `FrameworkAdapter` (which discovers and wraps nodes on a graph
    object), a `StepInterceptor` wraps one function at a time. This is the
    right shape for paradigms where there is no single graph object to wrap
    — e.g. composing steps in a notebook, a custom orchestrator, or a
    framework that doesn't expose an inspectable graph.
    """

    def wrap_step(
        self, step_id: str, func: Callable[..., Any], contract: NodeContract | None = None
    ) -> Callable[..., Any]:
        """Wrap *func* with reliability instrumentation for the given *step_id*."""
        ...


@runtime_checkable
class LoopAdapter(Protocol):
    """Protocol for agentic-loop paradigms (Claude Agent SDK, OpenAI Agents SDK).

    In an agentic loop the model decides what to do next via tool calls.
    The adapter intercepts tool call boundaries to apply contract validation,
    cost tracking, and failure handling.
    """

    def on_tool_call(self, tool_name: str, args: dict[str, Any], ctx: "ReliabilityContext") -> dict[str, Any]:
        """Intercept an outbound tool call before execution."""
        ...

    def on_tool_result(self, tool_name: str, result: Any, ctx: "ReliabilityContext") -> Any:
        """Intercept a tool result after execution."""
        ...


@runtime_checkable
class TurnAdapter(Protocol):
    """Protocol for conversation-driven paradigms (AutoGen).

    In a conversation-driven system, agents exchange messages in turns.
    The adapter intercepts turn boundaries to apply reliability primitives.
    """

    def on_turn_start(self, turn_id: str, message: Any, ctx: "ReliabilityContext") -> Any:
        """Intercept the start of a conversation turn."""
        ...

    def on_turn_end(self, turn_id: str, result: Any, ctx: "ReliabilityContext") -> Any:
        """Intercept the end of a conversation turn."""
        ...


def extract_state_dict(state: Any) -> dict[str, Any]:
    """Convert a framework state object to a plain dict.

    Supports dicts, Pydantic models, objects with a `.dict()` method,
    and plain objects with `__dict__`. Raises `TypeError` if the state
    cannot be converted.
    """
    if isinstance(state, dict):
        return dict(state)
    if isinstance(state, BaseModel):
        return state.model_dump()
    if hasattr(state, "dict"):
        result = state.dict()
        if isinstance(result, dict):
            return result
    if hasattr(state, "__dict__"):
        return {k: v for k, v in vars(state).items() if not k.startswith("_")}
    raise TypeError("Unable to extract state dict from state object")
