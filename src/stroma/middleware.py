from __future__ import annotations

import asyncio
import inspect
import logging
import random
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel

from stroma.checkpoint import CheckpointManager
from stroma.contracts import ContractRegistry, NodeContract
from stroma.cost import CostTracker, ExecutionBudget, FallbackPolicy, NodeUsage, estimate_cost_usd, resolve_model
from stroma.failures import Classifier, FailureClass, NodeContext, PolicyMap, RetryBudget, classify, default_policy_map
from stroma.trace import ExecutionResult, ExecutionTrace, RunStatus, TraceEvent

if TYPE_CHECKING:
    from stroma.runner import RunConfig

logger = logging.getLogger(__name__)


@dataclass
class ReliabilityContext:
    """Per-run bundle of every reliability primitive the execution loop needs.

    Decouples the reliability instrumentation from any particular execution
    strategy (linear runner, parallel fan-out, agentic loop, etc.).  Created
    once per pipeline run via `for_run()`, then threaded through whichever
    execution strategy drives the steps.
    """

    run_id: str
    registry: ContractRegistry
    checkpoint_manager: CheckpointManager
    cost_tracker: CostTracker
    retry_budget: RetryBudget
    trace: ExecutionTrace
    budget: ExecutionBudget
    policy_map: PolicyMap
    step_policies: dict[str, PolicyMap]
    classifiers: list[Classifier]
    step_timeouts: dict[str, int]
    model_fallbacks: list[FallbackPolicy]
    hooks: Any  # NodeHooks — typed as Any to avoid circular import
    context: dict[str, Any]
    run_logger: logging.LoggerAdapter = field(init=False)  # type: ignore[type-arg]

    def __post_init__(self) -> None:
        self.run_logger = logging.LoggerAdapter(logger, {"run_id": self.run_id})

    @classmethod
    def for_run(
        cls,
        config: RunConfig,
        registry: ContractRegistry,
        checkpoint_manager: CheckpointManager,
    ) -> ReliabilityContext:
        """Create a fresh context for a single pipeline run."""
        return cls(
            run_id=config.run_id,
            registry=registry,
            checkpoint_manager=checkpoint_manager,
            cost_tracker=CostTracker(),
            retry_budget=RetryBudget(),
            trace=ExecutionTrace(),
            budget=config.budget,
            policy_map=config.policy_map,
            step_policies=config.node_policies,
            classifiers=config.classifiers,
            step_timeouts=config.node_timeouts,
            model_fallbacks=config.model_fallbacks,
            hooks=config.hooks,
            context=config.context,
        )

    def build_result(self, status: RunStatus, final_state: Any) -> ExecutionResult:
        """Construct an `ExecutionResult` from the current tracker/trace state."""
        return ExecutionResult(
            run_id=self.run_id,
            status=status,
            final_state=final_state,
            trace=self.trace,
            total_cost_usd=self.cost_tracker.total_cost_usd,
            total_tokens=self.cost_tracker.total_tokens,
        )


def _step_accepts_context(func: Any) -> bool:
    try:
        sig = inspect.signature(func)
        return len(sig.parameters) >= 2
    except (ValueError, TypeError):
        return False


def _unpack_step_output(output: Any) -> tuple[dict[str, Any], int, int, str | None]:
    """Normalize step output to `(dict, input_tokens, output_tokens, model)`."""
    if isinstance(output, tuple):
        if len(output) == 4:
            return output[0], output[1], output[2], output[3]
        if len(output) == 3:
            return output[0], output[1], 0, output[2]
        if len(output) == 2:
            return output[0], output[1], 0, None
    return output, 0, 0, None


def _elapsed_ms(start: datetime) -> int:
    return int((datetime.now(UTC) - start).total_seconds() * 1000)


async def execute_step(
    step_id: str,
    func: Callable[..., Awaitable[Any]],
    input_state: BaseModel,
    ctx: ReliabilityContext,
    *,
    contract: NodeContract | None = None,
) -> ExecutionResult:
    """Execute a single step with full reliability instrumentation.

    Runs *func* with retry logic, contract validation, cost tracking, budget
    enforcement, model fallback, checkpointing, trace recording, and failure
    classification. Works independently of any orchestration framework —
    this is the freestanding reliability loop that `StromaRunner` delegates
    to internally.

    If *contract* is provided, input and output are validated against it.
    Otherwise the step runs without schema validation.
    """
    attempt = 1
    input_model: BaseModel | None = None
    while True:
        if contract is not None:
            input_model = ctx.registry.validate_input(step_id, input_state.model_dump())
        else:
            input_model = input_state
        start_ts = datetime.now(UTC)
        try:
            if ctx.model_fallbacks and ctx.budget.max_cost_usd:
                pct_used = ctx.cost_tracker.total_cost_usd / ctx.budget.max_cost_usd
                active_fallback = next(
                    (p for p in ctx.model_fallbacks if pct_used >= p.at_budget_pct),
                    None,
                )
                if active_fallback is not None:
                    ctx.context["_stroma_model"] = active_fallback.fallback_model
                else:
                    ctx.context.pop("_stroma_model", None)

            if ctx.hooks.on_node_start is not None:
                await ctx.hooks.on_node_start(ctx.run_id, step_id, input_model.model_dump())

            coro = func(input_model, ctx.context) if _step_accepts_context(func) else func(input_model)
            timeout_ms = ctx.step_timeouts.get(step_id)
            if timeout_ms is not None:
                raw_output = await asyncio.wait_for(coro, timeout=timeout_ms / 1000)
            else:
                raw_output = await coro

            output_raw, input_tokens, output_tokens, declared_model = _unpack_step_output(raw_output)
            model = resolve_model(declared_model, ctx.cost_tracker, ctx.budget, ctx.model_fallbacks)

            if contract is not None:
                output_model = ctx.registry.validate_output(step_id, output_raw)
            else:
                output_model = input_state.__class__(**output_raw)

            duration_ms = _elapsed_ms(start_ts)
            cost_usd = estimate_cost_usd(model, input_tokens, output_tokens) if model else 0.0
            tokens_used = input_tokens + output_tokens

            ctx.cost_tracker.record(
                NodeUsage(
                    node_id=step_id,
                    tokens_used=tokens_used,
                    cost_usd=cost_usd,
                    latency_ms=duration_ms,
                    model=model,
                    output_tokens=output_tokens,
                )
            )
            ctx.cost_tracker.check_budget(ctx.budget, step_id)
            await ctx.checkpoint_manager.checkpoint(ctx.run_id, step_id, output_model)

            ctx.trace.append(
                TraceEvent(
                    node_id=step_id,
                    run_id=ctx.run_id,
                    attempt=attempt,
                    timestamp_utc=start_ts,
                    input_state=input_model.model_dump(),
                    output_state=output_model.model_dump(),
                    duration_ms=duration_ms,
                )
            )
            ctx.run_logger.info("Step %s completed (attempt=%d, tokens=%d)", step_id, attempt, tokens_used)
            if ctx.hooks.on_node_success is not None:
                await ctx.hooks.on_node_success(ctx.run_id, step_id, output_model.model_dump(), tokens_used)
            return ctx.build_result(RunStatus.COMPLETED, output_model)

        except Exception as exc:
            result = await _handle_step_failure(exc, step_id, attempt, start_ts, input_model, input_state, ctx)
            if result is not None:
                return result
            attempt += 1


async def _handle_step_failure(
    exc: Exception,
    step_id: str,
    attempt: int,
    start_ts: datetime,
    input_model: BaseModel | None,
    fallback_state: BaseModel,
    ctx: ReliabilityContext,
) -> ExecutionResult | None:
    """Classify a failure and decide whether to retry or stop.

    Returns an `ExecutionResult` if execution should stop, or `None` to retry.
    """
    duration_ms = _elapsed_ms(start_ts)
    context = NodeContext(node_id=step_id, attempt=attempt, run_id=ctx.run_id)
    failure_class = classify(exc, context, ctx.classifiers)

    ctx.trace.append(
        TraceEvent(
            node_id=step_id,
            run_id=ctx.run_id,
            attempt=attempt,
            timestamp_utc=start_ts,
            input_state=input_model.model_dump() if input_model is not None else {},
            output_state=None,
            duration_ms=duration_ms,
            failure=failure_class,
            failure_message=str(exc),
        )
    )
    ctx.run_logger.warning("Step %s failed (attempt=%d, class=%s): %s", step_id, attempt, failure_class, exc)

    if ctx.hooks.on_node_failure is not None:
        await ctx.hooks.on_node_failure(ctx.run_id, step_id, exc, failure_class)

    step_override = ctx.step_policies.get(step_id, {})
    policy = (
        step_override.get(failure_class) or ctx.policy_map.get(failure_class) or default_policy_map()[failure_class]
    )

    if failure_class is FailureClass.TERMINAL:
        return ctx.build_result(RunStatus.FAILED, fallback_state)

    ctx.retry_budget.increment(ctx.run_id, step_id)
    if ctx.retry_budget.exhausted(ctx.run_id, step_id, policy):
        ctx.run_logger.error("Step %s retries exhausted after %d attempts", step_id, attempt)
        return ctx.build_result(RunStatus.PARTIAL, fallback_state)

    if policy.backoff_seconds > 0:
        await asyncio.sleep(random.uniform(0, policy.backoff_seconds))
    return None


class StromaStep:
    """Wraps any async callable with Stroma's full reliability suite.

    Provides a paradigm-agnostic way to apply contract validation, cost
    tracking, retry logic, checkpointing, and tracing to individual
    execution steps — without requiring `StromaRunner` or any framework
    adapter.

    Use `wrap()` to get back a decorated async callable, or use the
    instance as a decorator factory via `__call__()`.

    ## Example

    ```python
    ctx = ReliabilityContext.for_run(config, registry, manager)
    step = StromaStep(ctx)

    @step("summarize", input=DocInput, output=Summary)
    async def summarize(state: DocInput) -> dict:
        return {"text": "..."}

    result = await summarize(DocInput(text="hello"))
    ```
    """

    def __init__(self, ctx: ReliabilityContext) -> None:
        self._ctx = ctx

    def wrap(
        self,
        step_id: str,
        func: Callable[..., Awaitable[Any]],
        *,
        contract: NodeContract | None = None,
    ) -> Callable[..., Awaitable[ExecutionResult]]:
        """Wrap *func* so that calling it runs `execute_step` with full instrumentation."""

        async def wrapped(input_state: BaseModel) -> ExecutionResult:
            return await execute_step(step_id, func, input_state, self._ctx, contract=contract)

        wrapped._stroma_node_id = step_id  # type: ignore[attr-defined]  # ty: ignore[unresolved-attribute]
        wrapped._stroma_contract = contract  # type: ignore[attr-defined]  # ty: ignore[unresolved-attribute]
        return wrapped

    def __call__(
        self,
        step_id: str,
        *,
        input: type[BaseModel],
        output: type[BaseModel],
    ) -> Callable[..., Any]:
        """Decorator that creates a contract, registers it, and wraps the function.

        Paradigm-agnostic equivalent of `StromaRunner.node()`.
        """
        contract = NodeContract(node_id=step_id, input_schema=input, output_schema=output)
        self._ctx.registry.register(contract)

        def decorator(func: Callable[..., Awaitable[Any]]) -> Callable[..., Awaitable[ExecutionResult]]:
            return self.wrap(step_id, func, contract=contract)

        return decorator
