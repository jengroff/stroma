import asyncio
import importlib
from collections.abc import Callable
from typing import Any

from stroma.adapters.langgraph import extract_state_dict
from stroma.contracts import BoundaryValidator, ContractRegistry, NodeContract
from stroma.cost import CostTracker, NodeUsage, estimate_cost_usd
from stroma.runner import _unpack_output


def stroma_deepagents_node(node_id: str, contract: NodeContract) -> Callable[..., Any]:
    """Decorator that attaches stroma contract metadata to a deepagents node function.

    Binds *node_id* and *contract* as attributes on the decorated function so
    `DeepAgentsAdapter` can discover and validate it. Works identically to
    `stroma_langgraph_node` — deepagents nodes are LangGraph nodes under the hood.

    ## Example

    ```python
    from pydantic import BaseModel
    from stroma.contracts import NodeContract
    from stroma.adapters.deepagents import stroma_deepagents_node

    class Query(BaseModel):
        text: str

    class Answer(BaseModel):
        response: str

    contract = NodeContract(node_id="answer", input_schema=Query, output_schema=Answer)

    @stroma_deepagents_node("answer", contract)
    async def answer(state: Query) -> dict:
        return {"response": f"Got: {state.text}"}
    ```
    """

    def decorator(fn: Any) -> Any:
        fn._stroma_node_id = node_id  # type: ignore[attr-defined]
        fn._stroma_contract = contract  # type: ignore[attr-defined]
        return fn

    return decorator


class DeepAgentsAdapter:
    """Wraps a deepagents graph to apply stroma contract validation and cost tracking.

    deepagents builds on LangGraph internally, so the compiled graph returned by
    `deepagents.create_deep_agent()` exposes the same node interface. This adapter
    discovers nodes decorated with `@stroma_deepagents_node`, replaces them with
    async validating wrappers, and returns the modified graph.

    **Checkpointing boundary**: deepagents manages its own LangGraph checkpointer.
    Stroma does **not** inject checkpointing by default. Pass *checkpoint_store*
    only if you need a secondary stroma-managed checkpoint layer — you are then
    responsible for ensuring it does not conflict with deepagents' internal
    checkpointer.

    **Cost tracking**: if a node returns a tuple matching stroma's 4-shape cost
    convention `(dict, input_tokens, output_tokens, model)`, usage is recorded
    via the adapter's `CostTracker`. Plain dict returns record zero tokens.

    ## Example

    ```python
    from stroma.contracts import ContractRegistry
    from stroma.adapters.deepagents import DeepAgentsAdapter, stroma_deepagents_node

    registry = ContractRegistry()
    # ... register contracts, decorate nodes ...

    adapter = DeepAgentsAdapter(registry)
    agent = create_deep_agent(...)
    wrapped = adapter.wrap(agent)
    result = await wrapped.ainvoke({"text": "hello"})
    ```
    """

    def __init__(
        self,
        registry: ContractRegistry,
        checkpoint_store: Any | None = None,
    ) -> None:
        self.registry = registry
        self.checkpoint_store = checkpoint_store
        self._validator = BoundaryValidator()
        self._cost_tracker = CostTracker()

    def wrap(self, agent: Any) -> Any:
        """Discover stroma-decorated nodes in *agent* and replace them with validating wrappers.

        *agent* is the compiled graph returned by `deepagents.create_deep_agent()`.
        Raises `ImportError` if deepagents is not installed.
        """
        module_name = type(agent).__module__
        if module_name.startswith(("deepagents", "langgraph")):
            try:
                importlib.import_module("deepagents")
            except ImportError as exc:
                raise ImportError(
                    "deepagents is required for DeepAgentsAdapter; install with uv add stroma[deepagents]"
                ) from exc
        nodes = self._discover_nodes(agent)
        for name, fn in nodes.items():
            wrapped = self._wrap_node(fn)
            self._replace_node(agent, name, wrapped)
        return agent

    @property
    def cost_tracker(self) -> CostTracker:
        """The `CostTracker` accumulating usage across all wrapped node calls."""
        return self._cost_tracker

    def _discover_nodes(self, graph: Any) -> dict[str, Any]:
        for attr in ("nodes", "_nodes"):
            nodes = getattr(graph, attr, None)
            if isinstance(nodes, dict):
                return {name: fn for name, fn in nodes.items() if hasattr(fn, "_stroma_node_id")}
        if hasattr(graph, "iter_nodes"):
            return {name: fn for name, fn in graph.iter_nodes() if hasattr(fn, "_stroma_node_id")}
        raise AttributeError("Unable to discover deepagents graph nodes")

    def _replace_node(self, graph: Any, name: str, fn: Any) -> None:
        for attr in ("nodes", "_nodes"):
            nodes = getattr(graph, attr, None)
            if isinstance(nodes, dict) and name in nodes:
                nodes[name] = fn
                return
        if hasattr(graph, "add_node"):
            graph.add_node(name, fn)
            return
        raise AttributeError("Unable to replace deepagents graph node")

    def _wrap_node(self, fn: Any) -> Any:
        contract = getattr(fn, "_stroma_contract", None)
        if contract is None:
            raise TypeError(
                f"Function '{getattr(fn, '__name__', repr(fn))}' is missing a stroma contract. "
                "Did you forget the @stroma_deepagents_node decorator?"
            )

        async def wrapper(state: Any) -> Any:
            input_dict = extract_state_dict(state)
            input_model = self._validator(contract, "input", input_dict)
            result = fn(input_model)
            if asyncio.iscoroutine(result):
                result = await result

            output_dict, input_tokens, output_tokens, model = _unpack_output(result)
            if not isinstance(output_dict, dict):
                output_dict = extract_state_dict(output_dict)

            output_model = self._validator(contract, "output", output_dict)

            node_id = getattr(fn, "_stroma_node_id", "unknown")
            cost_usd = estimate_cost_usd(model, input_tokens, output_tokens) if model else 0.0
            self._cost_tracker.record(
                NodeUsage(
                    node_id=node_id,
                    tokens_used=input_tokens + output_tokens,
                    cost_usd=cost_usd,
                    latency_ms=0,
                    model=model,
                    output_tokens=output_tokens,
                )
            )

            return output_model.model_dump()

        return wrapper
