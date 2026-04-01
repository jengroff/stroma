import asyncio
import logging
import random
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field

from stroma.checkpoint import CheckpointManager
from stroma.contracts import ContractRegistry, NodeContract
from stroma.cost import CostTracker, ExecutionBudget, ModelHint, NodeUsage
from stroma.failures import (
    Classifier,
    FailureClass,
    NodeContext,
    PolicyMap,
    RetryBudget,
    classify,
    default_policy_map,
)
from stroma.trace import ExecutionResult, ExecutionTrace, RunStatus, TraceEvent

logger = logging.getLogger(__name__)


class RunConfig(BaseModel):
    """Configuration for a single pipeline run.

    A `run_id` is auto-generated if not provided. Set `budget`, `policy_map`,
    `model_hints`, `classifiers`, or `resume_from` to customize behavior.
    """

    run_id: str = Field(default_factory=lambda: str(uuid4()))
    budget: ExecutionBudget = Field(default_factory=ExecutionBudget.unlimited)
    policy_map: PolicyMap = Field(default_factory=default_policy_map)
    model_hints: dict[str, ModelHint] = Field(default_factory=dict)
    classifiers: list[Classifier] = Field(default_factory=list)
    resume_from: str | None = None

    model_config = {"arbitrary_types_allowed": True}


NodeFunc = Callable[[BaseModel], Awaitable[dict[str, Any]]]
"""Type alias for an async node function that takes a Pydantic model and returns a dict."""


def stroma_node(node_id: str, contract: NodeContract) -> Callable[..., Any]:
    """Decorator that attaches contract metadata to an async node function.

    Binds *node_id* and *contract* as attributes on the decorated function,
    returning a decorator that marks it as a stroma pipeline node.

    ## Example

    ```python
    @stroma_node("extract", NodeContract(node_id="extract", input_schema=In, output_schema=Out))
    async def extract(state: In) -> dict:
        return {"url": state.url, "content": "..."}
    ```
    """

    def decorator(func: Any) -> Any:
        func._stroma_node_id = node_id
        func._stroma_contract = contract
        return func

    return decorator


# Keep old name as alias for backwards compatibility during transition
armature_node = stroma_node


class StromaRunner:
    """Orchestrates sequential node execution with reliability primitives.

    Runs a sequence of async node functions, applying contract validation,
    retry policies, cost tracking, and checkpointing at each step. Requires
    a `ContractRegistry` for input/output validation, a `CheckpointManager`
    for persistence, and a `RunConfig` with budget, policies, and classifiers.

    ## Example

    ```python
    runner = StromaRunner(registry, checkpoint_manager, config)
    result = await runner.run([node1, node2], initial_state)
    print(result.status, result.final_state)
    ```
    """

    def __init__(self, registry: ContractRegistry, checkpoint_manager: CheckpointManager, config: RunConfig) -> None:
        self.registry = registry
        self.checkpoint_manager = checkpoint_manager
        self.config = config
        self.cost_tracker = CostTracker()
        self.retry_budget = RetryBudget()
        self.trace = ExecutionTrace()

    @classmethod
    def quick(
        cls,
        *,
        store: Any | None = None,
        budget: ExecutionBudget | None = None,
        policy_map: PolicyMap | None = None,
        classifiers: list[Classifier] | None = None,
        **config_kwargs: Any,
    ) -> "StromaRunner":
        """Create a runner with sensible defaults — no boilerplate required.

        Sets up an `InMemoryStore`, unlimited `ExecutionBudget`, and
        `default_policy_map()` retry policies. Pass *store*, *budget*,
        *policy_map*, or *classifiers* to override any of these. Additional
        keyword arguments are forwarded to `RunConfig`.

        Returns a fully configured `StromaRunner` ready to use.

        ## Example

        ```python
        runner = StromaRunner.quick()

        @runner.node("double", input=InputState, output=OutputState)
        async def double(state: InputState) -> dict:
            return {"result": state.value * 2}

        result = await runner.run([double], InputState(value=5))
        ```
        """
        from stroma.checkpoint import InMemoryStore

        registry = ContractRegistry()
        checkpoint_store = store if store is not None else InMemoryStore()
        checkpoint_manager = CheckpointManager(checkpoint_store)
        config = RunConfig(
            budget=budget if budget is not None else ExecutionBudget.unlimited(),
            policy_map=policy_map if policy_map is not None else default_policy_map(),
            classifiers=classifiers if classifiers is not None else [],
            **config_kwargs,
        )
        return cls(registry, checkpoint_manager, config)

    def node(
        self,
        node_id: str,
        *,
        input: type[BaseModel],
        output: type[BaseModel],
    ) -> Callable[..., Any]:
        """Decorator that creates a contract, registers it, and marks the function as a node.

        Combines `stroma_node`, `NodeContract` creation, and
        `ContractRegistry.register` into a single step. Pass the *node_id*,
        *input* schema, and *output* schema and the returned decorator handles
        the rest.

        ## Example

        ```python
        runner = StromaRunner.quick()

        @runner.node("extract", input=Document, output=Entities)
        async def extract(state: Document) -> dict:
            return {"entities": ["Python", "Pydantic"]}
        ```
        """
        contract = NodeContract(node_id=node_id, input_schema=input, output_schema=output)
        self.registry.register(contract)

        def decorator(func: Any) -> Any:
            func._stroma_node_id = node_id
            func._stroma_contract = contract
            return func

        return decorator

    async def run(self, node_sequence: list[NodeFunc], initial_state: BaseModel) -> ExecutionResult:
        """Execute a sequence of nodes with full reliability instrumentation.

        Runs each node in *node_sequence* starting from *initial_state*,
        returning an `ExecutionResult` with the final state, trace, and
        cost info.
        """
        current_state = initial_state
        start_index = self._resolve_resume_index(node_sequence)
        if start_index is None:
            return self._build_result(RunStatus.PARTIAL, current_state)

        current_state = self._load_resume_state(node_sequence, start_index, current_state)

        for node in node_sequence[start_index:]:
            node_id = self._node_id(node)
            contract = self._node_contract(node)
            logger.debug("Executing node %s (run=%s)", node_id, self.config.run_id)

            result = await self._execute_node(node, node_id, contract, current_state)  # type: ignore[arg-type]
            if result.status != RunStatus.COMPLETED:
                return result
            assert result.final_state is not None
            current_state = result.final_state

        status = RunStatus.RESUMED if self.config.resume_from is not None else RunStatus.COMPLETED
        return self._build_result(status, current_state)

    async def _execute_node(
        self, node: NodeFunc, node_id: str, contract: NodeContract, current_state: BaseModel
    ) -> ExecutionResult:
        """Execute a single node with retries, validation, and tracking."""
        attempt = 1
        input_model: BaseModel | None = None
        while True:
            input_model = self.registry.validate_input(node_id, current_state.model_dump())
            start_ts = datetime.now(UTC)
            try:
                output_raw, tokens_used = self._unpack_output(await node(input_model))
                output_model = self.registry.validate_output(node_id, output_raw)
                duration_ms = self._elapsed_ms(start_ts)

                self.cost_tracker.record(
                    NodeUsage(node_id=node_id, tokens_used=tokens_used, cost_usd=0.0, latency_ms=duration_ms)
                )
                self.cost_tracker.check_budget(self.config.budget, node_id)
                self.checkpoint_manager.checkpoint(self.config.run_id, node_id, output_model)

                self.trace.append(
                    TraceEvent(
                        node_id=node_id,
                        run_id=self.config.run_id,
                        attempt=attempt,
                        timestamp_utc=start_ts,
                        input_state=input_model.model_dump(),
                        output_state=output_model.model_dump(),
                        duration_ms=duration_ms,
                    )
                )
                logger.info("Node %s completed (attempt=%d, tokens=%d)", node_id, attempt, tokens_used)
                return self._build_result(RunStatus.COMPLETED, output_model)

            except Exception as exc:
                result = await self._handle_failure(exc, node_id, attempt, start_ts, input_model, current_state)
                if result is not None:
                    return result
                attempt += 1

    async def _handle_failure(
        self,
        exc: Exception,
        node_id: str,
        attempt: int,
        start_ts: datetime,
        input_model: BaseModel | None,
        current_state: BaseModel,
    ) -> ExecutionResult | None:
        """Classify a failure and decide whether to retry or stop.

        Returns an ExecutionResult if the pipeline should stop, or None to continue retrying.
        """
        duration_ms = self._elapsed_ms(start_ts)
        context = NodeContext(node_id=node_id, attempt=attempt, run_id=self.config.run_id)
        failure_class = classify(exc, context, self.config.classifiers)

        self.trace.append(
            TraceEvent(
                node_id=node_id,
                run_id=self.config.run_id,
                attempt=attempt,
                timestamp_utc=start_ts,
                input_state=input_model.model_dump() if input_model is not None else {},
                output_state=None,
                duration_ms=duration_ms,
                failure=failure_class,
                failure_message=str(exc),
            )
        )
        logger.warning("Node %s failed (attempt=%d, class=%s): %s", node_id, attempt, failure_class, exc)

        policy = self.config.policy_map.get(failure_class) or default_policy_map()[failure_class]

        if failure_class is FailureClass.TERMINAL:
            return self._build_result(RunStatus.FAILED, current_state)

        self.retry_budget.increment(self.config.run_id, node_id)
        if self.retry_budget.exhausted(self.config.run_id, node_id, policy):
            logger.error("Node %s retries exhausted after %d attempts", node_id, attempt)
            return self._build_result(RunStatus.PARTIAL, current_state)

        if policy.backoff_seconds > 0:
            await asyncio.sleep(random.uniform(0, policy.backoff_seconds))
        return None

    def _resolve_resume_index(self, node_sequence: list[NodeFunc]) -> int | None:
        """Find the start index for resume, or 0 for fresh runs. Returns None if resume target not found."""
        if self.config.resume_from is None:
            return 0
        for index, node in enumerate(node_sequence):
            if self._node_id(node) == self.config.resume_from:
                return index
        logger.error("Resume target node %s not found in sequence", self.config.resume_from)
        return None

    def _load_resume_state(
        self, node_sequence: list[NodeFunc], start_index: int, current_state: BaseModel
    ) -> BaseModel:
        """Load checkpoint state from the node before the resume point."""
        if self.config.resume_from is None or start_index == 0:
            return current_state
        previous = node_sequence[start_index - 1]
        prev_contract = self._node_contract(previous)
        loaded = self.checkpoint_manager.resume(
            self.config.run_id, self._node_id(previous), prev_contract.output_schema
        )
        if loaded is not None:
            logger.info("Resumed from checkpoint at node %s", self._node_id(previous))
            return loaded
        return current_state

    def _build_result(self, status: RunStatus, final_state: BaseModel | None) -> ExecutionResult:
        """Construct an ExecutionResult from the current tracker/trace state."""
        return ExecutionResult(
            run_id=self.config.run_id,
            status=status,
            final_state=final_state,
            trace=self.trace,
            total_cost_usd=self.cost_tracker.total_cost_usd,
            total_tokens=self.cost_tracker.total_tokens,
        )

    @staticmethod
    def _unpack_output(output: Any) -> tuple[dict[str, Any], int]:
        """Normalize node output to (dict, tokens_used)."""
        if isinstance(output, tuple) and len(output) == 2:
            return output[0], output[1]
        return output, 0

    @staticmethod
    def _elapsed_ms(start: datetime) -> int:
        """Milliseconds elapsed since *start*."""
        return int((datetime.now(UTC) - start).total_seconds() * 1000)

    def _node_id(self, node: Callable[..., Any]) -> str:
        """Extract the stroma node ID from a decorated function."""
        node_id: str | None = getattr(node, "_stroma_node_id", None) or getattr(node, "_armature_node_id", None)
        if node_id is None:
            raise TypeError("Node is missing stroma node_id — did you forget the @stroma_node decorator?")
        return node_id

    def _node_contract(self, node: Callable[..., Any]) -> NodeContract:
        """Extract the contract from a decorated function, falling back to the registry."""
        contract: NodeContract | None = (
            getattr(node, "_stroma_contract", None) or getattr(node, "_armature_contract", None)
        )
        if contract is not None:
            return contract
        return self.registry.get(self._node_id(node))


# Backwards-compatible alias
ArmatureRunner = StromaRunner
