import asyncio
import logging
from collections.abc import Callable
from typing import Any

try:
    import crewai  # noqa: F401
except ImportError as exc:
    raise ImportError("CrewAI is required for CrewAIAdapter; install with uv add stroma[crewai]") from exc

from stroma.adapters.base import extract_state_dict
from stroma.contracts import BoundaryValidator, ContractRegistry, NodeContract

logger = logging.getLogger(__name__)


def stroma_crewai_step(node_id: str, contract: NodeContract) -> Callable[..., Any]:
    """Decorator that attaches stroma contract metadata to a CrewAI Flow method.

    Binds *node_id* and *contract* as attributes on the decorated method so
    `CrewAIAdapter` can discover and validate it.
    """

    def decorator(fn: Any) -> Any:
        fn._stroma_node_id = node_id  # type: ignore[attr-defined]
        fn._stroma_contract = contract  # type: ignore[attr-defined]
        return fn

    return decorator


class CrewAIAdapter:
    """Wraps a CrewAI Flow instance to apply stroma contract validation on decorated steps.

    Takes a `ContractRegistry` for validation. Call `.wrap(flow_instance)` to
    discover decorated methods and replace them with validating wrappers.
    State lives on `flow_instance.state` and is extracted/merged automatically.
    """

    def __init__(self, registry: ContractRegistry) -> None:
        self.registry = registry
        self._validator = BoundaryValidator()

    def wrap(self, flow: Any) -> Any:
        """Discover stroma-decorated methods on *flow* and replace them with validating wrappers."""
        for name in self._discover_decorated_methods(flow):
            method = getattr(flow, name)
            wrapped = self._wrap_step(flow, method)
            setattr(flow, name, wrapped)
        return flow

    def _discover_decorated_methods(self, flow: Any) -> list[str]:
        """Find all method names on *flow* that carry stroma metadata."""
        names: list[str] = []
        for attr_name in dir(flow):
            if attr_name.startswith("_"):
                continue
            attr = getattr(flow, attr_name, None)
            if callable(attr) and hasattr(attr, "_stroma_node_id"):
                names.append(attr_name)
        return names

    def _wrap_step(self, flow: Any, method: Any) -> Callable[..., Any]:
        """Create a validating wrapper around a Flow step method."""
        contract: NodeContract = method._stroma_contract
        validator = self._validator

        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            state_dict = extract_state_dict(flow.state)
            validator(contract, "input", state_dict)

            result = method(*args, **kwargs)
            if asyncio.iscoroutine(result):
                result = await result

            if result is not None:
                output_dict = extract_state_dict(result) if not isinstance(result, dict) else result
            else:
                output_dict = extract_state_dict(flow.state)

            validated = validator(contract, "output", output_dict)
            validated_dict = validated.model_dump()

            if isinstance(flow.state, dict):
                flow.state.update(validated_dict)
            else:
                for key, value in validated_dict.items():
                    if hasattr(flow.state, key):
                        setattr(flow.state, key, value)

            return result

        wrapper._stroma_node_id = contract.node_id  # type: ignore[attr-defined]  # ty: ignore[unresolved-attribute]
        wrapper._stroma_contract = contract  # type: ignore[attr-defined]  # ty: ignore[unresolved-attribute]
        return wrapper
