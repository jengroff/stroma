import asyncio
import importlib
from collections.abc import Callable
from typing import Any

from pydantic import BaseModel

from stroma.contracts import BoundaryValidator, ContractRegistry, NodeContract


def extract_state_dict(state: Any) -> dict[str, Any]:
    """Convert a LangGraph state object to a plain dict.

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
    raise TypeError("Unable to extract state dict from LangGraph state")


def stroma_langgraph_node(node_id: str, contract: NodeContract) -> Callable[..., Any]:
    """Decorator that attaches stroma contract metadata to a LangGraph node function.

    Binds *node_id* and *contract* as attributes on the decorated function so
    `LangGraphAdapter` can discover and validate it.
    """

    def decorator(fn: Any) -> Any:
        fn._stroma_node_id = node_id  # type: ignore[attr-defined]
        fn._stroma_contract = contract  # type: ignore[attr-defined]
        return fn

    return decorator


# Backwards-compatible alias
armature_langgraph_node = stroma_langgraph_node


class LangGraphAdapter:
    """Wraps a LangGraph graph to apply stroma contract validation on each node.

    Takes a `ContractRegistry` for validation and a runner instance for
    future cost/trace integration.
    """

    def __init__(self, registry: ContractRegistry, runner: Any) -> None:
        self.registry = registry
        self.runner = runner
        self._validator = BoundaryValidator()

    def wrap(self, graph: Any) -> Any:
        """Discover stroma-decorated nodes in *graph* and replace them with validating wrappers."""
        module_name = type(graph).__module__
        if module_name.startswith("langgraph"):
            try:
                importlib.import_module("langgraph")
            except ImportError as exc:
                raise ImportError(
                    "LangGraph is required for LangGraphAdapter; install with pip install stroma[langgraph]"
                ) from exc
        nodes = self._discover_nodes(graph)
        for name, fn in nodes.items():
            wrapped = self._wrap_node(fn)
            self._replace_node(graph, name, wrapped)
        return graph

    def _discover_nodes(self, graph: Any) -> dict[str, Any]:
        """Find all stroma-decorated nodes in a graph."""
        for attr in ("nodes", "_nodes"):
            nodes = getattr(graph, attr, None)
            if isinstance(nodes, dict):
                return {
                    name: fn
                    for name, fn in nodes.items()
                    if hasattr(fn, "_stroma_node_id") or hasattr(fn, "_armature_node_id")
                }
        if hasattr(graph, "iter_nodes"):
            return {
                name: fn
                for name, fn in graph.iter_nodes()
                if hasattr(fn, "_stroma_node_id") or hasattr(fn, "_armature_node_id")
            }
        raise AttributeError("Unable to discover LangGraph nodes")

    def _replace_node(self, graph: Any, name: str, fn: Any) -> None:
        """Replace a node function in the graph."""
        for attr in ("nodes", "_nodes"):
            nodes = getattr(graph, attr, None)
            if isinstance(nodes, dict) and name in nodes:
                nodes[name] = fn
                return
        if hasattr(graph, "add_node"):
            graph.add_node(name, fn)
            return
        raise AttributeError("Unable to replace LangGraph node")

    def _wrap_node(self, fn: Any) -> Any:
        """Create a validating async wrapper around a node function."""
        contract = getattr(fn, "_stroma_contract", None) or getattr(fn, "_armature_contract", None)
        if contract is None:
            raise TypeError(
                f"Function '{getattr(fn, '__name__', repr(fn))}' is missing a stroma contract. "
                "Did you forget the @stroma_langgraph_node decorator?"
            )

        async def wrapper(state: Any) -> Any:
            input_dict = extract_state_dict(state)
            input_model = self._validator(contract, "input", input_dict)
            result = fn(input_model)
            if asyncio.iscoroutine(result):
                result = await result
            output_dict = extract_state_dict(result)
            output_model = self._validator(contract, "output", output_dict)
            return output_model.model_dump()

        return wrapper
