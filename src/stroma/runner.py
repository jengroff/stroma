import asyncio
import inspect
import logging
import random
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field

from stroma.checkpoint import CheckpointManager
from stroma.contracts import ContractRegistry, NodeContract
from stroma.cost import CostTracker, ExecutionBudget, ModelHint, NodeUsage, estimate_cost_usd
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


@dataclass
class NodeHooks:
    """Optional async callbacks fired at node execution boundaries.

    - `on_node_start(run_id, node_id, input_state_dict)`
    - `on_node_success(run_id, node_id, output_state_dict, tokens_used)`
    - `on_node_failure(run_id, node_id, exc, failure_class)`
    """

    on_node_start: Callable[[str, str, dict[str, Any]], Awaitable[None]] | None = None
    on_node_success: Callable[[str, str, dict[str, Any], int], Awaitable[None]] | None = None
    on_node_failure: Callable[[str, str, Exception, FailureClass], Awaitable[None]] | None = None


class RunConfig(BaseModel):
    """Configuration for a single pipeline run.

    A `run_id` is auto-generated if not provided. Set `budget`, `policy_map`,
    `model_hints`, `classifiers`, or `resume_from` to customize behavior.
    """

    run_id: str = Field(
        default_factory=lambda: str(uuid4()),
        description="Unique identifier for this run. Auto-generated UUID if not provided.",
    )
    budget: ExecutionBudget = Field(
        default_factory=ExecutionBudget.unlimited,
        description="Resource limits (tokens, cost, latency). Defaults to unlimited.",
    )
    policy_map: PolicyMap = Field(
        default_factory=default_policy_map,
        description="Global retry policies keyed by `FailureClass`. Defaults to `default_policy_map()`.",
    )
    node_policies: dict[str, PolicyMap] = Field(
        default_factory=dict,
        description="Per-node policy overrides keyed by node ID. Falls back to `policy_map`.",
    )
    hooks: NodeHooks = Field(
        default_factory=NodeHooks,
        description="Async lifecycle callbacks fired at node execution boundaries.",
    )
    model_hints: dict[str, ModelHint] = Field(
        default_factory=dict,
        description="Per-node model selection hints keyed by node ID.",
    )
    classifiers: list[Classifier] = Field(
        default_factory=list,
        description="Custom failure classifiers checked before built-in rules.",
    )
    context: dict[str, Any] = Field(
        default_factory=dict,
        description="Shared mutable dict passed to nodes that accept a second argument.",
    )
    resume_from: str | None = Field(
        default=None,
        description="Node ID to resume from. Skips earlier nodes and loads checkpoint.",
    )

    model_config = {"arbitrary_types_allowed": True}


NodeFunc = Callable[[BaseModel], Awaitable[dict[str, Any]]]
"""Type alias for an async node function that takes a Pydantic model and returns a dict."""


def _node_accepts_context(node: Any) -> bool:
    try:
        sig = inspect.signature(node)
        return len(sig.parameters) >= 2
    except (ValueError, TypeError):
        return False


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


def _unpack_output(output: Any) -> tuple[dict[str, Any], int, int, str | None]:
    """Normalize node output to `(dict, input_tokens, output_tokens, model)`."""
    if isinstance(output, tuple):
        if len(output) == 4:
            return output[0], output[1], output[2], output[3]
        if len(output) == 3:
            return output[0], output[1], 0, output[2]
        if len(output) == 2:
            return output[0], output[1], 0, None
    return output, 0, 0, None


def parallel(*nodes: NodeFunc) -> NodeFunc:  # type: ignore[return-value]
    """Wrap multiple nodes to run concurrently with `asyncio.gather`.

    The returned pseudo-node fans out the current pipeline state to all child
    nodes, runs them concurrently, then merges their output dicts (last write
    wins on key conflicts). All child nodes must accept the same input schema.

    On any child failure, remaining tasks are cancelled and the exception
    propagates to the runner's failure handling.

    ## Example

    ```python
    result = await runner.run([node_a, parallel(node_b, node_c), node_d], state)
    ```
    """
    node_ids = [getattr(n, "_stroma_node_id", repr(n)) for n in nodes]
    pseudo_id = f"parallel({', '.join(node_ids)})"

    async def _parallel_node(state: BaseModel, ctx: dict[str, Any] | None = None) -> dict[str, Any]:
        async def _run_one(node: NodeFunc) -> dict[str, Any]:
            if _node_accepts_context(node) and ctx is not None:
                result = await node(state, ctx)  # type: ignore[call-arg]  # ty: ignore[too-many-positional-arguments]
            else:
                result = await node(state)  # type: ignore[call-arg]
            output, *_ = _unpack_output(result)
            return output

        results = await asyncio.gather(*[_run_one(n) for n in nodes])
        merged: dict[str, Any] = {}
        for r in results:
            merged.update(r)
        return merged

    _parallel_node._stroma_node_id = pseudo_id  # type: ignore[attr-defined]  # ty: ignore[unresolved-attribute]
    _parallel_node._stroma_is_parallel = True  # type: ignore[attr-defined]  # ty: ignore[unresolved-attribute]
    _parallel_node._stroma_child_nodes = nodes  # type: ignore[attr-defined]  # ty: ignore[unresolved-attribute]
    return _parallel_node  # type: ignore[return-value]


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

    @classmethod
    def quick(
        cls,
        *,
        store: Any | None = None,
        budget: ExecutionBudget | None = None,
        policy_map: PolicyMap | None = None,
        classifiers: list[Classifier] | None = None,
        hooks: "NodeHooks | None" = None,
        **config_kwargs: Any,
    ) -> "StromaRunner":
        """Create a runner with sensible defaults — no boilerplate required.

        Sets up an `InMemoryStore`, unlimited `ExecutionBudget`, and
        `default_policy_map()` retry policies. Pass *store*, *budget*,
        *policy_map*, *classifiers*, or *hooks* to override any of these.
        Additional keyword arguments are forwarded to `RunConfig`.

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
        from stroma.checkpoint import AsyncInMemoryStore

        registry = ContractRegistry()
        checkpoint_store = store if store is not None else AsyncInMemoryStore()
        checkpoint_manager = CheckpointManager(checkpoint_store)
        config = RunConfig(
            budget=budget if budget is not None else ExecutionBudget.unlimited(),
            policy_map=policy_map if policy_map is not None else default_policy_map(),
            classifiers=classifiers if classifiers is not None else [],
            hooks=hooks if hooks is not None else NodeHooks(),
            **config_kwargs,
        )
        return cls(registry, checkpoint_manager, config)

    def with_redis(self, redis_url: str, ttl_seconds: int = 3600) -> "StromaRunner":
        """Replace the checkpoint backend with a Redis-backed store.

        Requires the `redis` extra (`uv add stroma[redis]`).
        """
        from stroma.checkpoint import RedisStore

        self.checkpoint_manager = CheckpointManager(RedisStore(redis_url, ttl_seconds))
        return self

    def with_budget(
        self,
        *,
        tokens: int | None = None,
        cost_usd: float | None = None,
        latency_ms: int | None = None,
    ) -> "StromaRunner":
        """Set execution budget limits for token count, cost, or latency."""
        self.config = self.config.model_copy(
            update={
                "budget": ExecutionBudget(
                    max_tokens_total=tokens,
                    max_cost_usd=cost_usd,
                    max_latency_ms=latency_ms,
                )
            }
        )
        return self

    def with_classifiers(self, classifiers: list[Classifier]) -> "StromaRunner":
        """Set custom failure classifiers for error handling."""
        self.config = self.config.model_copy(update={"classifiers": classifiers})
        return self

    def with_hooks(self, hooks: "NodeHooks") -> "StromaRunner":
        """Set node lifecycle hooks for observability."""
        self.config = self.config.model_copy(update={"hooks": hooks})
        return self

    def with_context(self, context: dict[str, Any]) -> "StromaRunner":
        """Set the shared context dict passed to nodes that accept a second argument."""
        self.config = self.config.model_copy(update={"context": context})
        return self

    def with_policy_map(self, policy_map: PolicyMap) -> "StromaRunner":
        """Set the global failure policy map."""
        self.config = self.config.model_copy(update={"policy_map": policy_map})
        return self

    def with_node_policies(self, node_policies: dict[str, PolicyMap]) -> "StromaRunner":
        """Set per-node failure policy overrides."""
        self.config = self.config.model_copy(update={"node_policies": node_policies})
        return self

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
        cost_tracker = CostTracker()
        retry_budget = RetryBudget()
        trace = ExecutionTrace()
        run_logger = logging.LoggerAdapter(logger, {"run_id": self.config.run_id})

        current_state = initial_state
        start_index = self._resolve_resume_index(node_sequence)
        if start_index is None:
            return self._build_result(RunStatus.PARTIAL, current_state, cost_tracker, trace)

        current_state = await self._load_resume_state(node_sequence, start_index, current_state)

        for node in node_sequence[start_index:]:
            node_id = self._node_id(node)
            run_logger.debug("Executing node %s", node_id)

            if getattr(node, "_stroma_is_parallel", False):
                result = await self._execute_parallel_node(
                    node, node_id, current_state, cost_tracker, trace, run_logger
                )
            else:
                contract = self._node_contract(node)
                result = await self._execute_node(
                    node, node_id, contract, current_state, cost_tracker, retry_budget, trace, run_logger
                )
            if result.status != RunStatus.COMPLETED:
                return result
            assert result.final_state is not None
            current_state = result.final_state

        status = RunStatus.RESUMED if self.config.resume_from is not None else RunStatus.COMPLETED
        return self._build_result(status, current_state, cost_tracker, trace)

    async def _execute_node(
        self,
        node: NodeFunc,
        node_id: str,
        contract: NodeContract,
        current_state: BaseModel,
        cost_tracker: CostTracker,
        retry_budget: RetryBudget,
        trace: ExecutionTrace,
        run_logger: logging.LoggerAdapter,  # type: ignore[type-arg]
    ) -> ExecutionResult:
        """Execute a single node with retries, validation, and tracking."""
        attempt = 1
        input_model: BaseModel | None = None
        while True:
            input_model = self.registry.validate_input(node_id, current_state.model_dump())
            start_ts = datetime.now(UTC)
            try:
                if self.config.hooks.on_node_start is not None:
                    await self.config.hooks.on_node_start(self.config.run_id, node_id, input_model.model_dump())
                if _node_accepts_context(node):
                    raw_output = await node(input_model, self.config.context)  # type: ignore[call-arg]  # ty: ignore[too-many-positional-arguments]
                else:
                    raw_output = await node(input_model)
                output_raw, input_tokens, output_tokens, model = self._unpack_output(raw_output)
                output_model = self.registry.validate_output(node_id, output_raw)
                duration_ms = self._elapsed_ms(start_ts)
                cost_usd = estimate_cost_usd(model, input_tokens, output_tokens) if model else 0.0
                tokens_used = input_tokens + output_tokens

                cost_tracker.record(
                    NodeUsage(
                        node_id=node_id,
                        tokens_used=tokens_used,
                        cost_usd=cost_usd,
                        latency_ms=duration_ms,
                        model=model,
                        output_tokens=output_tokens,
                    )
                )
                cost_tracker.check_budget(self.config.budget, node_id)
                await self.checkpoint_manager.checkpoint(self.config.run_id, node_id, output_model)

                trace.append(
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
                run_logger.info("Node %s completed (attempt=%d, tokens=%d)", node_id, attempt, tokens_used)
                if self.config.hooks.on_node_success is not None:
                    await self.config.hooks.on_node_success(
                        self.config.run_id, node_id, output_model.model_dump(), tokens_used
                    )
                return self._build_result(RunStatus.COMPLETED, output_model, cost_tracker, trace)

            except Exception as exc:
                result = await self._handle_failure(
                    exc,
                    node_id,
                    attempt,
                    start_ts,
                    input_model,
                    current_state,
                    cost_tracker,
                    retry_budget,
                    trace,
                    run_logger,
                )
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
        cost_tracker: CostTracker,
        retry_budget: RetryBudget,
        trace: ExecutionTrace,
        run_logger: logging.LoggerAdapter,  # type: ignore[type-arg]
    ) -> ExecutionResult | None:
        """Classify a failure and decide whether to retry or stop.

        Returns an ExecutionResult if the pipeline should stop, or None to continue retrying.
        """
        duration_ms = self._elapsed_ms(start_ts)
        context = NodeContext(node_id=node_id, attempt=attempt, run_id=self.config.run_id)
        failure_class = classify(exc, context, self.config.classifiers)

        trace.append(
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
        run_logger.warning("Node %s failed (attempt=%d, class=%s): %s", node_id, attempt, failure_class, exc)

        if self.config.hooks.on_node_failure is not None:
            await self.config.hooks.on_node_failure(self.config.run_id, node_id, exc, failure_class)

        node_override = self.config.node_policies.get(node_id, {})
        policy = (
            node_override.get(failure_class)
            or self.config.policy_map.get(failure_class)
            or default_policy_map()[failure_class]
        )

        if failure_class is FailureClass.TERMINAL:
            return self._build_result(RunStatus.FAILED, current_state, cost_tracker, trace)

        retry_budget.increment(self.config.run_id, node_id)
        if retry_budget.exhausted(self.config.run_id, node_id, policy):
            run_logger.error("Node %s retries exhausted after %d attempts", node_id, attempt)
            return self._build_result(RunStatus.PARTIAL, current_state, cost_tracker, trace)

        if policy.backoff_seconds > 0:
            await asyncio.sleep(random.uniform(0, policy.backoff_seconds))
        return None

    async def _execute_parallel_node(
        self,
        node: NodeFunc,
        node_id: str,
        current_state: BaseModel,
        cost_tracker: CostTracker,
        trace: ExecutionTrace,
        run_logger: logging.LoggerAdapter,  # type: ignore[type-arg]
    ) -> ExecutionResult:
        """Execute a parallel pseudo-node, merging child outputs into a dynamic model."""
        from pydantic import create_model

        start_ts = datetime.now(UTC)
        try:
            ctx = self.config.context
            merged = await node(current_state, ctx)  # type: ignore[call-arg]  # ty: ignore[too-many-positional-arguments]

            dynamic_output = create_model(
                "ParallelOutput", **{k: (type(v), ...) for k, v in merged.items()}
            )  # ty: ignore[no-matching-overload]
            output_model = dynamic_output(**merged)

            duration_ms = self._elapsed_ms(start_ts)
            trace.append(
                TraceEvent(
                    node_id=node_id,
                    run_id=self.config.run_id,
                    attempt=1,
                    timestamp_utc=start_ts,
                    input_state=current_state.model_dump(),
                    output_state=merged,
                    duration_ms=duration_ms,
                )
            )
            run_logger.info("Parallel node %s completed", node_id)
            return self._build_result(RunStatus.COMPLETED, output_model, cost_tracker, trace)

        except Exception as exc:
            duration_ms = self._elapsed_ms(start_ts)
            trace.append(
                TraceEvent(
                    node_id=node_id,
                    run_id=self.config.run_id,
                    attempt=1,
                    timestamp_utc=start_ts,
                    input_state=current_state.model_dump(),
                    output_state=None,
                    duration_ms=duration_ms,
                    failure=FailureClass.AMBIGUOUS,
                    failure_message=str(exc),
                )
            )
            run_logger.error("Parallel node %s failed: %s", node_id, exc)
            return self._build_result(RunStatus.FAILED, current_state, cost_tracker, trace)

    def _resolve_resume_index(self, node_sequence: list[NodeFunc]) -> int | None:
        """Find the start index for resume, or 0 for fresh runs. Returns None if resume target not found."""
        if self.config.resume_from is None:
            return 0
        for index, node in enumerate(node_sequence):
            if self._node_id(node) == self.config.resume_from:
                return index
        logger.error("Resume target node %s not found in sequence", self.config.resume_from)
        return None

    async def _load_resume_state(
        self, node_sequence: list[NodeFunc], start_index: int, current_state: BaseModel
    ) -> BaseModel:
        """Load checkpoint state from the node before the resume point."""
        if self.config.resume_from is None or start_index == 0:
            return current_state
        previous = node_sequence[start_index - 1]
        prev_contract = self._node_contract(previous)
        loaded = await self.checkpoint_manager.resume(
            self.config.run_id, self._node_id(previous), prev_contract.output_schema
        )
        if loaded is not None:
            logger.info("Resumed from checkpoint at node %s", self._node_id(previous))
            return loaded
        return current_state

    def _build_result(
        self, status: RunStatus, final_state: BaseModel | None, cost_tracker: CostTracker, trace: ExecutionTrace
    ) -> ExecutionResult:
        """Construct an ExecutionResult from the current tracker/trace state."""
        return ExecutionResult(
            run_id=self.config.run_id,
            status=status,
            final_state=final_state,
            trace=trace,
            total_cost_usd=cost_tracker.total_cost_usd,
            total_tokens=cost_tracker.total_tokens,
        )

    @staticmethod
    def _unpack_output(output: Any) -> tuple[dict[str, Any], int, int, str | None]:
        """Normalize node output to `(dict, input_tokens, output_tokens, model)`.

        Handles three tuple shapes returned by node functions:

        - **4-tuple** `(dict, input_tokens, output_tokens, model)`
        - **3-tuple** `(dict, input_tokens, model)` — output_tokens defaults to `0`
        - **2-tuple** `(dict, input_tokens)` — output_tokens `0`, model `None`
        - **bare dict** — all token counts `0`, model `None`
        """
        return _unpack_output(output)

    @staticmethod
    def _elapsed_ms(start: datetime) -> int:
        """Milliseconds elapsed since *start*."""
        return int((datetime.now(UTC) - start).total_seconds() * 1000)

    def _node_id(self, node: Callable[..., Any]) -> str:
        """Extract the stroma node ID from a decorated function."""
        node_id: str | None = getattr(node, "_stroma_node_id", None)
        if node_id is None:
            raise TypeError("Node is missing stroma node_id — did you forget the @stroma_node decorator?")
        return node_id

    def _node_contract(self, node: Callable[..., Any]) -> NodeContract:
        """Extract the contract from a decorated function, falling back to the registry."""
        contract: NodeContract | None = getattr(node, "_stroma_contract", None)
        if contract is not None:
            return contract
        return self.registry.get(self._node_id(node))
