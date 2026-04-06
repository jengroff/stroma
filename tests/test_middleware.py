import pytest
from pydantic import BaseModel

from stroma.checkpoint import AsyncInMemoryStore, CheckpointManager
from stroma.contracts import ContractRegistry, NodeContract
from stroma.cost import ExecutionBudget
from stroma.failures import FailureClass, FailurePolicy, default_policy_map
from stroma.middleware import ReliabilityContext, StromaStep, execute_step
from stroma.runner import RunConfig
from stroma.trace import RunStatus


class StepIn(BaseModel):
    x: int


class StepOut(BaseModel):
    y: int


CONTRACT = NodeContract(node_id="double", input_schema=StepIn, output_schema=StepOut)


def _make_ctx(*, budget: ExecutionBudget | None = None, policy_map=None, **overrides) -> ReliabilityContext:
    registry = ContractRegistry()
    registry.register(CONTRACT)
    config = RunConfig(
        budget=budget if budget is not None else ExecutionBudget.unlimited(),
        policy_map=policy_map if policy_map is not None else default_policy_map(),
        **overrides,
    )
    store = AsyncInMemoryStore()
    manager = CheckpointManager(store)
    return ReliabilityContext.for_run(config, registry, manager)


async def test_execute_step_happy_path():
    ctx = _make_ctx()

    async def double(state: StepIn) -> dict:
        return {"y": state.x * 2}

    result = await execute_step("double", double, StepIn(x=5), ctx, contract=CONTRACT)
    assert result.status == RunStatus.COMPLETED
    assert result.final_state.y == 10


async def test_execute_step_contract_violation():
    ctx = _make_ctx()

    async def bad(state: StepIn) -> dict:
        return {"wrong": "field"}

    result = await execute_step("double", bad, StepIn(x=1), ctx, contract=CONTRACT)
    assert result.status == RunStatus.FAILED
    assert len(ctx.trace) == 1
    assert ctx.trace._events[0].failure == FailureClass.TERMINAL


async def test_execute_step_retry_on_timeout():
    call_count = {"n": 0}

    async def flaky(state: StepIn) -> dict:
        call_count["n"] += 1
        if call_count["n"] < 2:
            raise TimeoutError("transient")
        return {"y": state.x + 1}

    policy_map = default_policy_map()
    policy_map[FailureClass.RECOVERABLE] = FailurePolicy(max_retries=3, backoff_seconds=0.0)
    ctx = _make_ctx(policy_map=policy_map)

    result = await execute_step("double", flaky, StepIn(x=7), ctx, contract=CONTRACT)
    assert result.status == RunStatus.COMPLETED
    assert call_count["n"] == 2
    assert result.final_state.y == 8


async def test_execute_step_cost_tracking():
    ctx = _make_ctx()

    async def with_cost(state: StepIn) -> tuple:
        return ({"y": state.x}, 1_000_000, 0, "gpt-4o")

    result = await execute_step("double", with_cost, StepIn(x=3), ctx, contract=CONTRACT)
    assert result.status == RunStatus.COMPLETED
    assert result.total_cost_usd == pytest.approx(2.50)
    assert result.total_tokens == 1_000_000


async def test_execute_step_without_contract():
    ctx = _make_ctx()

    async def no_contract(state: StepIn) -> dict:
        return {"x": state.x + 10}

    result = await execute_step("unvalidated", no_contract, StepIn(x=1), ctx)
    assert result.status == RunStatus.COMPLETED
    assert result.final_state.x == 11


async def test_execute_step_with_context():
    ctx = _make_ctx(context={"factor": 3})

    async def uses_ctx(state: StepIn, ctx_dict: dict) -> dict:
        return {"y": state.x * ctx_dict["factor"]}

    result = await execute_step("double", uses_ctx, StepIn(x=4), ctx, contract=CONTRACT)
    assert result.status == RunStatus.COMPLETED
    assert result.final_state.y == 12


async def test_execute_step_trace_recorded():
    ctx = _make_ctx()

    async def step(state: StepIn) -> dict:
        return {"y": state.x}

    await execute_step("double", step, StepIn(x=1), ctx, contract=CONTRACT)
    assert len(ctx.trace) == 1
    assert ctx.trace._events[0].node_id == "double"
    assert ctx.trace._events[0].step_id == "double"


async def test_execute_step_checkpoints():
    ctx = _make_ctx()

    async def step(state: StepIn) -> dict:
        return {"y": state.x}

    await execute_step("double", step, StepIn(x=42), ctx, contract=CONTRACT)
    loaded = await ctx.checkpoint_manager.resume(ctx.run_id, "double", StepOut)
    assert loaded is not None
    assert loaded.y == 42


# --- StromaStep ---


async def test_stroma_step_wrap():
    ctx = _make_ctx()
    step = StromaStep(ctx)

    async def double(state: StepIn) -> dict:
        return {"y": state.x * 2}

    wrapped = step.wrap("double", double, contract=CONTRACT)
    result = await wrapped(StepIn(x=7))
    assert result.status == RunStatus.COMPLETED
    assert result.final_state.y == 14


async def test_stroma_step_wrap_attaches_metadata():
    ctx = _make_ctx()
    step = StromaStep(ctx)

    async def noop(state: StepIn) -> dict:
        return {"y": 0}

    wrapped = step.wrap("double", noop, contract=CONTRACT)
    assert wrapped._stroma_node_id == "double"
    assert wrapped._stroma_contract is CONTRACT


async def test_stroma_step_decorator_form():
    ctx = _make_ctx()
    step = StromaStep(ctx)

    @step("double", input=StepIn, output=StepOut)
    async def double(state: StepIn) -> dict:
        return {"y": state.x * 2}

    result = await double(StepIn(x=6))
    assert result.status == RunStatus.COMPLETED
    assert result.final_state.y == 12


async def test_stroma_step_decorator_registers_contract():
    ctx = _make_ctx()
    step = StromaStep(ctx)

    @step("custom_step", input=StepIn, output=StepOut)
    async def custom(state: StepIn) -> dict:
        return {"y": state.x}

    registered = ctx.registry.get("custom_step")
    assert registered.input_schema is StepIn
    assert registered.output_schema is StepOut


async def test_stroma_step_importable_from_top_level():
    from stroma import ReliabilityContext, StromaStep, execute_step

    assert StromaStep is not None
    assert ReliabilityContext is not None
    assert execute_step is not None
