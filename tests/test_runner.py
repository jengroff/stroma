import pytest
from pydantic import BaseModel

from stroma.checkpoint import CheckpointManager, InMemoryStore
from stroma.contracts import ContractRegistry, NodeContract
from stroma.cost import ExecutionBudget
from stroma.failures import FailureClass, FailurePolicy, default_policy_map
from stroma.runner import RunConfig, StromaRunner, stroma_node
from stroma.trace import RunStatus


class InputState(BaseModel):
    value: int


class NodeOneOutput(BaseModel):
    result: int


class NodeTwoOutput(BaseModel):
    total: int


@pytest.mark.asyncio
async def test_happy_path_full_sequence():
    registry = ContractRegistry()
    registry.register(NodeContract(node_id="node1", input_schema=InputState, output_schema=NodeOneOutput))
    registry.register(NodeContract(node_id="node2", input_schema=NodeOneOutput, output_schema=NodeTwoOutput))
    store = InMemoryStore()
    manager = CheckpointManager(store)

    @stroma_node("node1", NodeContract(node_id="node1", input_schema=InputState, output_schema=NodeOneOutput))
    async def node1(state: InputState) -> dict:
        return {"result": state.value + 1}

    @stroma_node("node2", NodeContract(node_id="node2", input_schema=NodeOneOutput, output_schema=NodeTwoOutput))
    async def node2(state: NodeOneOutput) -> dict:
        return {"total": state.result * 2}

    config = RunConfig(run_id="run1", budget=ExecutionBudget.unlimited(), policy_map=default_policy_map())
    runner = StromaRunner(registry, manager, config)
    result = await runner.run([node1, node2], InputState(value=3))

    assert result.status == RunStatus.COMPLETED
    assert result.final_state.total == 8
    assert len(result.trace) == 2
    assert result.total_tokens == 0


@pytest.mark.asyncio
async def test_terminal_failure_returns_failed_with_partial_trace():
    registry = ContractRegistry()
    registry.register(NodeContract(node_id="node1", input_schema=InputState, output_schema=NodeOneOutput))
    store = InMemoryStore()
    manager = CheckpointManager(store)

    @stroma_node("node1", NodeContract(node_id="node1", input_schema=InputState, output_schema=NodeOneOutput))
    async def node1(state: InputState) -> dict:
        return {"bad": "value"}

    config = RunConfig(run_id="run2", budget=ExecutionBudget.unlimited(), policy_map=default_policy_map())
    runner = StromaRunner(registry, manager, config)
    result = await runner.run([node1], InputState(value=1))

    assert result.status == RunStatus.FAILED
    assert len(result.trace) == 1
    assert next(iter(result.trace)).failure == FailureClass.TERMINAL
    # On failure, final_state should be the last valid state (the input)
    assert result.final_state is not None


@pytest.mark.asyncio
async def test_recoverable_retries_then_returns_partial():
    registry = ContractRegistry()
    registry.register(NodeContract(node_id="node1", input_schema=InputState, output_schema=NodeOneOutput))
    store = InMemoryStore()
    manager = CheckpointManager(store)

    call_count = {"node1": 0}

    @stroma_node("node1", NodeContract(node_id="node1", input_schema=InputState, output_schema=NodeOneOutput))
    async def node1(state: InputState) -> dict:
        call_count["node1"] += 1
        raise TimeoutError("transient")

    policy_map = default_policy_map()
    policy_map[FailureClass.RECOVERABLE] = FailurePolicy(max_retries=3, backoff_seconds=0.0)
    config = RunConfig(run_id="run3", budget=ExecutionBudget.unlimited(), policy_map=policy_map)
    runner = StromaRunner(registry, manager, config)
    result = await runner.run([node1], InputState(value=1))

    assert result.status == RunStatus.PARTIAL
    assert call_count["node1"] == 3
    assert len(result.trace) == 3
    assert all(event.failure == FailureClass.RECOVERABLE for event in result.trace)


@pytest.mark.asyncio
async def test_resume_skips_completed_nodes_and_loads_checkpoint():
    registry = ContractRegistry()
    registry.register(NodeContract(node_id="node1", input_schema=InputState, output_schema=NodeOneOutput))
    registry.register(NodeContract(node_id="node2", input_schema=NodeOneOutput, output_schema=NodeTwoOutput))
    store = InMemoryStore()
    manager = CheckpointManager(store)

    @stroma_node("node1", NodeContract(node_id="node1", input_schema=InputState, output_schema=NodeOneOutput))
    async def node1(state: InputState) -> dict:
        return {"result": state.value + 2}

    @stroma_node("node2", NodeContract(node_id="node2", input_schema=NodeOneOutput, output_schema=NodeTwoOutput))
    async def node2(state: NodeOneOutput) -> dict:
        return {"total": state.result * 3}

    config1 = RunConfig(run_id="run4", budget=ExecutionBudget.unlimited(), policy_map=default_policy_map())
    runner1 = StromaRunner(registry, manager, config1)
    first = await runner1.run([node1, node2], InputState(value=1))
    assert first.status == RunStatus.COMPLETED
    assert len(first.trace) == 2

    call_count = {"node1": 0, "node2": 0}

    @stroma_node("node2", NodeContract(node_id="node2", input_schema=NodeOneOutput, output_schema=NodeTwoOutput))
    async def resumed_node2(state: NodeOneOutput) -> dict:
        call_count["node2"] += 1
        return {"total": state.result * 5}

    @stroma_node("node1", NodeContract(node_id="node1", input_schema=InputState, output_schema=NodeOneOutput))
    async def counted_node1(state: InputState) -> dict:
        call_count["node1"] += 1
        raise AssertionError("node1 should not run")

    config2 = RunConfig(
        run_id="run4",
        budget=ExecutionBudget.unlimited(),
        policy_map=default_policy_map(),
        resume_from="node2",
    )
    runner2 = StromaRunner(registry, manager, config2)
    result = await runner2.run([counted_node1, resumed_node2], InputState(value=1))

    assert result.status == RunStatus.RESUMED
    assert len(result.trace) == 1
    assert result.final_state.total == 15
    assert call_count["node1"] == 0
    assert call_count["node2"] == 1


@pytest.mark.asyncio
async def test_custom_classifier_is_used():
    """Verify custom classifiers from RunConfig are passed to classify()."""
    registry = ContractRegistry()
    registry.register(NodeContract(node_id="node1", input_schema=InputState, output_schema=NodeOneOutput))
    store = InMemoryStore()
    manager = CheckpointManager(store)

    @stroma_node("node1", NodeContract(node_id="node1", input_schema=InputState, output_schema=NodeOneOutput))
    async def node1(state: InputState) -> dict:
        raise ValueError("custom classified")

    def make_terminal(exc, ctx):
        if isinstance(exc, ValueError):
            return FailureClass.TERMINAL
        return None

    config = RunConfig(
        run_id="run_classifier",
        budget=ExecutionBudget.unlimited(),
        classifiers=[make_terminal],
    )
    runner = StromaRunner(registry, manager, config)
    result = await runner.run([node1], InputState(value=1))

    # ValueError would normally be AMBIGUOUS (1 retry), but our classifier makes it TERMINAL
    assert result.status == RunStatus.FAILED
    assert len(result.trace) == 1
    assert next(iter(result.trace)).failure == FailureClass.TERMINAL


@pytest.mark.asyncio
async def test_budget_exceeded_during_run():
    """Verify budget enforcement triggers during a run."""
    registry = ContractRegistry()
    registry.register(NodeContract(node_id="node1", input_schema=InputState, output_schema=NodeOneOutput))
    store = InMemoryStore()
    manager = CheckpointManager(store)

    @stroma_node("node1", NodeContract(node_id="node1", input_schema=InputState, output_schema=NodeOneOutput))
    async def node1(state: InputState) -> dict:
        return ({"result": state.value + 1}, 100)  # 100 tokens

    config = RunConfig(
        run_id="run_budget",
        budget=ExecutionBudget(max_tokens_total=50),
        policy_map={
            FailureClass.RECOVERABLE: FailurePolicy(max_retries=0, backoff_seconds=0.0),
            FailureClass.TERMINAL: FailurePolicy(max_retries=0, backoff_seconds=0.0),
            FailureClass.AMBIGUOUS: FailurePolicy(max_retries=0, backoff_seconds=0.0),
        },
    )
    runner = StromaRunner(registry, manager, config)
    result = await runner.run([node1], InputState(value=1))

    # BudgetExceeded is RECOVERABLE, but with 0 retries it becomes PARTIAL
    assert result.status == RunStatus.PARTIAL


@pytest.mark.asyncio
async def test_empty_node_sequence():
    """An empty node sequence should complete immediately with the initial state."""
    registry = ContractRegistry()
    store = InMemoryStore()
    manager = CheckpointManager(store)

    config = RunConfig(run_id="run_empty", budget=ExecutionBudget.unlimited())
    runner = StromaRunner(registry, manager, config)
    result = await runner.run([], InputState(value=42))

    assert result.status == RunStatus.COMPLETED
    assert result.final_state.value == 42
    assert len(result.trace) == 0


@pytest.mark.asyncio
async def test_tuple_return_with_tokens():
    """Verify nodes can return (dict, tokens) tuples."""
    registry = ContractRegistry()
    registry.register(NodeContract(node_id="node1", input_schema=InputState, output_schema=NodeOneOutput))
    store = InMemoryStore()
    manager = CheckpointManager(store)

    @stroma_node("node1", NodeContract(node_id="node1", input_schema=InputState, output_schema=NodeOneOutput))
    async def node1(state: InputState) -> dict:
        return ({"result": state.value + 1}, 42)

    config = RunConfig(run_id="run_tokens", budget=ExecutionBudget.unlimited())
    runner = StromaRunner(registry, manager, config)
    result = await runner.run([node1], InputState(value=1))

    assert result.status == RunStatus.COMPLETED
    assert result.total_tokens == 42
    assert result.final_state.result == 2


@pytest.mark.asyncio
async def test_cost_usd_computed_from_model_string():
    registry = ContractRegistry()
    registry.register(NodeContract(node_id="node1", input_schema=InputState, output_schema=NodeOneOutput))
    store = InMemoryStore()
    manager = CheckpointManager(store)

    @stroma_node("node1", NodeContract(node_id="node1", input_schema=InputState, output_schema=NodeOneOutput))
    async def node1(state: InputState) -> tuple:
        return ({"result": state.value + 1}, 1_000_000, 0, "gpt-4o")

    config = RunConfig(run_id="run_cost", budget=ExecutionBudget.unlimited())
    runner = StromaRunner(registry, manager, config)
    result = await runner.run([node1], InputState(value=1))

    assert result.status == RunStatus.COMPLETED
    assert result.total_cost_usd == pytest.approx(2.50)


@pytest.mark.asyncio
async def test_runner_reuse_does_not_accumulate_state():
    registry = ContractRegistry()
    registry.register(NodeContract(node_id="node1", input_schema=InputState, output_schema=NodeOneOutput))
    store = InMemoryStore()
    manager = CheckpointManager(store)

    @stroma_node("node1", NodeContract(node_id="node1", input_schema=InputState, output_schema=NodeOneOutput))
    async def node1(state: InputState) -> tuple:
        return ({"result": state.value + 1}, 10)

    config = RunConfig(run_id="run_reuse", budget=ExecutionBudget.unlimited())
    runner = StromaRunner(registry, manager, config)

    result1 = await runner.run([node1], InputState(value=1))
    result2 = await runner.run([node1], InputState(value=2))

    assert result1.total_tokens == 10
    assert result2.total_tokens == 10
    assert len(result1.trace) == 1
    assert len(result2.trace) == 1


@pytest.mark.asyncio
async def test_per_node_policy_overrides_global():
    registry = ContractRegistry()
    registry.register(NodeContract(node_id="node1", input_schema=InputState, output_schema=NodeOneOutput))
    store = InMemoryStore()
    manager = CheckpointManager(store)
    call_count = {"n": 0}

    @stroma_node("node1", NodeContract(node_id="node1", input_schema=InputState, output_schema=NodeOneOutput))
    async def node1(state: InputState) -> dict:
        call_count["n"] += 1
        raise TimeoutError("always fails")

    config = RunConfig(
        run_id="run_per_node",
        budget=ExecutionBudget.unlimited(),
        policy_map={
            FailureClass.RECOVERABLE: FailurePolicy(max_retries=3, backoff_seconds=0.0),
            FailureClass.TERMINAL: FailurePolicy(max_retries=0),
            FailureClass.AMBIGUOUS: FailurePolicy(max_retries=1, backoff_seconds=0.0),
        },
        node_policies={
            "node1": {
                FailureClass.RECOVERABLE: FailurePolicy(max_retries=1, backoff_seconds=0.0),
            }
        },
    )
    runner = StromaRunner(registry, manager, config)
    result = await runner.run([node1], InputState(value=1))

    assert result.status == RunStatus.PARTIAL
    assert call_count["n"] == 1


@pytest.mark.asyncio
async def test_global_policy_applies_when_no_node_override():
    registry = ContractRegistry()
    registry.register(NodeContract(node_id="node1", input_schema=InputState, output_schema=NodeOneOutput))
    store = InMemoryStore()
    manager = CheckpointManager(store)
    call_count = {"n": 0}

    @stroma_node("node1", NodeContract(node_id="node1", input_schema=InputState, output_schema=NodeOneOutput))
    async def node1(state: InputState) -> dict:
        call_count["n"] += 1
        raise TimeoutError("always fails")

    config = RunConfig(
        run_id="run_global_fallback",
        budget=ExecutionBudget.unlimited(),
        policy_map={
            FailureClass.RECOVERABLE: FailurePolicy(max_retries=2, backoff_seconds=0.0),
            FailureClass.TERMINAL: FailurePolicy(max_retries=0),
            FailureClass.AMBIGUOUS: FailurePolicy(max_retries=0, backoff_seconds=0.0),
        },
        node_policies={},
    )
    runner = StromaRunner(registry, manager, config)
    result = await runner.run([node1], InputState(value=1))

    assert result.status == RunStatus.PARTIAL
    assert call_count["n"] == 2


@pytest.mark.asyncio
async def test_on_node_start_hook_called():
    from unittest.mock import AsyncMock

    from stroma.runner import NodeHooks

    registry = ContractRegistry()
    registry.register(NodeContract(node_id="node1", input_schema=InputState, output_schema=NodeOneOutput))
    store = InMemoryStore()
    manager = CheckpointManager(store)

    @stroma_node("node1", NodeContract(node_id="node1", input_schema=InputState, output_schema=NodeOneOutput))
    async def node1(state: InputState) -> dict:
        return {"result": state.value + 1}

    on_start = AsyncMock()
    on_success = AsyncMock()

    config = RunConfig(
        run_id="run_hooks",
        budget=ExecutionBudget.unlimited(),
        hooks=NodeHooks(on_node_start=on_start, on_node_success=on_success),
    )
    runner = StromaRunner(registry, manager, config)
    result = await runner.run([node1], InputState(value=5))

    assert result.status == RunStatus.COMPLETED
    on_start.assert_awaited_once()
    call_args = on_start.call_args[0]
    assert call_args[1] == "node1"
    assert call_args[2] == {"value": 5}

    on_success.assert_awaited_once()
    success_args = on_success.call_args[0]
    assert success_args[1] == "node1"
    assert success_args[2] == {"result": 6}


@pytest.mark.asyncio
async def test_on_node_failure_hook_called():
    from unittest.mock import AsyncMock

    from stroma.runner import NodeHooks

    registry = ContractRegistry()
    registry.register(NodeContract(node_id="node1", input_schema=InputState, output_schema=NodeOneOutput))
    store = InMemoryStore()
    manager = CheckpointManager(store)

    @stroma_node("node1", NodeContract(node_id="node1", input_schema=InputState, output_schema=NodeOneOutput))
    async def node1(state: InputState) -> dict:
        return {"bad": "data"}

    on_failure = AsyncMock()

    config = RunConfig(
        run_id="run_hooks_failure",
        budget=ExecutionBudget.unlimited(),
        hooks=NodeHooks(on_node_failure=on_failure),
    )
    runner = StromaRunner(registry, manager, config)
    result = await runner.run([node1], InputState(value=1))

    assert result.status == RunStatus.FAILED
    on_failure.assert_awaited_once()
    failure_args = on_failure.call_args[0]
    assert failure_args[1] == "node1"
    assert failure_args[3] == FailureClass.TERMINAL


@pytest.mark.asyncio
async def test_no_hooks_does_not_error():
    registry = ContractRegistry()
    registry.register(NodeContract(node_id="node1", input_schema=InputState, output_schema=NodeOneOutput))
    store = InMemoryStore()
    manager = CheckpointManager(store)

    @stroma_node("node1", NodeContract(node_id="node1", input_schema=InputState, output_schema=NodeOneOutput))
    async def node1(state: InputState) -> dict:
        return {"result": state.value + 1}

    config = RunConfig(run_id="run_no_hooks", budget=ExecutionBudget.unlimited())
    runner = StromaRunner(registry, manager, config)
    result = await runner.run([node1], InputState(value=1))
    assert result.status == RunStatus.COMPLETED


@pytest.mark.asyncio
async def test_context_passed_to_node():
    registry = ContractRegistry()
    registry.register(NodeContract(node_id="node1", input_schema=InputState, output_schema=NodeOneOutput))
    store = InMemoryStore()
    manager = CheckpointManager(store)

    @stroma_node("node1", NodeContract(node_id="node1", input_schema=InputState, output_schema=NodeOneOutput))
    async def node1(state: InputState, ctx: dict) -> dict:
        multiplier = ctx.get("multiplier", 1)
        return {"result": state.value * multiplier}

    config = RunConfig(
        run_id="run_ctx",
        budget=ExecutionBudget.unlimited(),
        context={"multiplier": 7},
    )
    runner = StromaRunner(registry, manager, config)
    result = await runner.run([node1], InputState(value=6))

    assert result.status == RunStatus.COMPLETED
    assert result.final_state.result == 42


@pytest.mark.asyncio
async def test_context_mutations_visible_across_nodes():
    registry = ContractRegistry()
    registry.register(NodeContract(node_id="node1", input_schema=InputState, output_schema=NodeOneOutput))
    registry.register(NodeContract(node_id="node2", input_schema=NodeOneOutput, output_schema=NodeTwoOutput))
    store = InMemoryStore()
    manager = CheckpointManager(store)

    @stroma_node("node1", NodeContract(node_id="node1", input_schema=InputState, output_schema=NodeOneOutput))
    async def node1(state: InputState, ctx: dict) -> dict:
        ctx["seen_by_node1"] = True
        return {"result": state.value + 1}

    @stroma_node("node2", NodeContract(node_id="node2", input_schema=NodeOneOutput, output_schema=NodeTwoOutput))
    async def node2(state: NodeOneOutput, ctx: dict) -> dict:
        assert ctx.get("seen_by_node1") is True
        return {"total": state.result * 2}

    config = RunConfig(run_id="run_ctx_mut", budget=ExecutionBudget.unlimited())
    runner = StromaRunner(registry, manager, config)
    result = await runner.run([node1, node2], InputState(value=5))
    assert result.status == RunStatus.COMPLETED


@pytest.mark.asyncio
async def test_nodes_without_context_arg_still_work():
    registry = ContractRegistry()
    registry.register(NodeContract(node_id="node1", input_schema=InputState, output_schema=NodeOneOutput))
    store = InMemoryStore()
    manager = CheckpointManager(store)

    @stroma_node("node1", NodeContract(node_id="node1", input_schema=InputState, output_schema=NodeOneOutput))
    async def node1(state: InputState) -> dict:
        return {"result": state.value + 1}

    config = RunConfig(run_id="run_no_ctx", budget=ExecutionBudget.unlimited(), context={"ignored": True})
    runner = StromaRunner(registry, manager, config)
    result = await runner.run([node1], InputState(value=3))
    assert result.status == RunStatus.COMPLETED
    assert result.final_state.result == 4


@pytest.mark.asyncio
async def test_parallel_nodes_run_concurrently_and_merge():
    from stroma.runner import parallel

    registry = ContractRegistry()
    registry.register(NodeContract(node_id="node1", input_schema=InputState, output_schema=NodeOneOutput))
    registry.register(NodeContract(node_id="node2", input_schema=InputState, output_schema=NodeTwoOutput))
    store = InMemoryStore()
    manager = CheckpointManager(store)

    execution_order = []

    @stroma_node("node1", NodeContract(node_id="node1", input_schema=InputState, output_schema=NodeOneOutput))
    async def node_a(state: InputState) -> dict:
        execution_order.append("a")
        return {"result": state.value + 1}

    @stroma_node("node2", NodeContract(node_id="node2", input_schema=InputState, output_schema=NodeTwoOutput))
    async def node_b(state: InputState) -> dict:
        execution_order.append("b")
        return {"total": state.value * 2}

    config = RunConfig(run_id="run_parallel", budget=ExecutionBudget.unlimited())
    runner = StromaRunner(registry, manager, config)

    result = await runner.run([parallel(node_a, node_b)], InputState(value=5))
    assert result.status == RunStatus.COMPLETED
    merged = result.final_state
    assert merged.result == 6
    assert merged.total == 10
    assert set(execution_order) == {"a", "b"}


@pytest.mark.asyncio
async def test_parallel_failure_propagates():
    from stroma.runner import parallel

    registry = ContractRegistry()
    store = InMemoryStore()
    manager = CheckpointManager(store)

    @stroma_node("node1", NodeContract(node_id="node1", input_schema=InputState, output_schema=NodeOneOutput))
    async def node_ok(state: InputState) -> dict:
        return {"result": state.value + 1}

    @stroma_node("node2", NodeContract(node_id="node2", input_schema=InputState, output_schema=NodeTwoOutput))
    async def node_fail(state: InputState) -> dict:
        raise RuntimeError("child node exploded")

    config = RunConfig(run_id="run_parallel_fail", budget=ExecutionBudget.unlimited())
    runner = StromaRunner(registry, manager, config)

    result = await runner.run([parallel(node_ok, node_fail)], InputState(value=5))
    assert result.status == RunStatus.PARTIAL


@pytest.mark.asyncio
async def test_parallel_trace_event_recorded():
    from stroma.runner import parallel

    registry = ContractRegistry()
    store = InMemoryStore()
    manager = CheckpointManager(store)

    @stroma_node("node1", NodeContract(node_id="node1", input_schema=InputState, output_schema=NodeOneOutput))
    async def node_a(state: InputState) -> dict:
        return {"result": state.value + 1}

    config = RunConfig(run_id="run_parallel_trace", budget=ExecutionBudget.unlimited())
    runner = StromaRunner(registry, manager, config)
    result = await runner.run([parallel(node_a)], InputState(value=1))

    assert len(result.trace) == 1
    event = next(iter(result.trace))
    assert "parallel" in event.node_id


# --- Parallel instrumentation tests ---


@pytest.mark.asyncio
async def test_parallel_hooks_called():
    from unittest.mock import AsyncMock

    from stroma.runner import NodeHooks, parallel

    registry = ContractRegistry()
    registry.register(NodeContract(node_id="node1", input_schema=InputState, output_schema=NodeOneOutput))
    store = InMemoryStore()
    manager = CheckpointManager(store)

    @stroma_node("node1", NodeContract(node_id="node1", input_schema=InputState, output_schema=NodeOneOutput))
    async def node_a(state: InputState) -> dict:
        return {"result": state.value + 1}

    on_start = AsyncMock()
    on_success = AsyncMock()

    config = RunConfig(
        run_id="run_parallel_hooks",
        budget=ExecutionBudget.unlimited(),
        hooks=NodeHooks(on_node_start=on_start, on_node_success=on_success),
    )
    runner = StromaRunner(registry, manager, config)
    result = await runner.run([parallel(node_a)], InputState(value=5))

    assert result.status == RunStatus.COMPLETED
    on_start.assert_awaited()
    on_success.assert_awaited()
    success_args = on_success.call_args[0]
    assert "parallel" in success_args[1]


@pytest.mark.asyncio
async def test_parallel_failure_hook_called():
    from unittest.mock import AsyncMock

    from stroma.runner import NodeHooks, parallel

    registry = ContractRegistry()
    store = InMemoryStore()
    manager = CheckpointManager(store)

    @stroma_node("node1", NodeContract(node_id="node1", input_schema=InputState, output_schema=NodeOneOutput))
    async def node_fail(state: InputState) -> dict:
        raise RuntimeError("boom")

    on_failure = AsyncMock()

    config = RunConfig(
        run_id="run_parallel_fail_hook",
        budget=ExecutionBudget.unlimited(),
        hooks=NodeHooks(on_node_failure=on_failure),
    )
    runner = StromaRunner(registry, manager, config)
    result = await runner.run([parallel(node_fail)], InputState(value=1))

    assert result.status == RunStatus.PARTIAL
    assert on_failure.await_count >= 1


@pytest.mark.asyncio
async def test_parallel_cost_tracking():
    from stroma.runner import parallel

    registry = ContractRegistry()
    registry.register(NodeContract(node_id="node1", input_schema=InputState, output_schema=NodeOneOutput))
    registry.register(NodeContract(node_id="node2", input_schema=InputState, output_schema=NodeTwoOutput))
    store = InMemoryStore()
    manager = CheckpointManager(store)

    @stroma_node("node1", NodeContract(node_id="node1", input_schema=InputState, output_schema=NodeOneOutput))
    async def node_a(state: InputState) -> tuple:
        return ({"result": state.value + 1}, 100, 50, "gpt-4o")

    @stroma_node("node2", NodeContract(node_id="node2", input_schema=InputState, output_schema=NodeTwoOutput))
    async def node_b(state: InputState) -> tuple:
        return ({"total": state.value * 2}, 200, 100, "gpt-4o")

    config = RunConfig(run_id="run_parallel_cost", budget=ExecutionBudget.unlimited())
    runner = StromaRunner(registry, manager, config)
    result = await runner.run([parallel(node_a, node_b)], InputState(value=5))

    assert result.status == RunStatus.COMPLETED
    assert result.total_tokens == 450


@pytest.mark.asyncio
async def test_parallel_checkpoints_output():
    from stroma.runner import parallel

    registry = ContractRegistry()
    registry.register(NodeContract(node_id="node1", input_schema=InputState, output_schema=NodeOneOutput))
    store = InMemoryStore()
    manager = CheckpointManager(store)

    @stroma_node("node1", NodeContract(node_id="node1", input_schema=InputState, output_schema=NodeOneOutput))
    async def node_a(state: InputState) -> dict:
        return {"result": state.value + 1}

    config = RunConfig(run_id="run_parallel_ckpt", budget=ExecutionBudget.unlimited())
    runner = StromaRunner(registry, manager, config)
    result = await runner.run([parallel(node_a)], InputState(value=5))

    assert result.status == RunStatus.COMPLETED
    loaded = await manager.resume("run_parallel_ckpt", "parallel(node1)", result.final_state.__class__)
    assert loaded is not None


@pytest.mark.asyncio
async def test_parallel_child_contract_violation():
    from stroma.runner import parallel

    registry = ContractRegistry()
    registry.register(NodeContract(node_id="node1", input_schema=InputState, output_schema=NodeOneOutput))
    store = InMemoryStore()
    manager = CheckpointManager(store)

    @stroma_node("node1", NodeContract(node_id="node1", input_schema=InputState, output_schema=NodeOneOutput))
    async def bad_node(state: InputState) -> dict:
        return {"wrong_field": "oops"}

    config = RunConfig(run_id="run_parallel_cv", budget=ExecutionBudget.unlimited())
    runner = StromaRunner(registry, manager, config)
    result = await runner.run([parallel(bad_node)], InputState(value=1))

    assert result.status == RunStatus.FAILED
    failure_events = list(result.trace.failures())
    assert len(failure_events) == 1


# --- Task 11: Fluent builder API tests ---


@pytest.mark.asyncio
async def test_with_budget_builder_enforces_cost():
    registry = ContractRegistry()
    registry.register(NodeContract(node_id="node1", input_schema=InputState, output_schema=NodeOneOutput))
    store = InMemoryStore()
    manager = CheckpointManager(store)

    @stroma_node("node1", NodeContract(node_id="node1", input_schema=InputState, output_schema=NodeOneOutput))
    async def node1(state: InputState) -> tuple:
        # 1M input tokens at gpt-4o = $2.50, budget is $0.01 — should exceed
        return ({"result": state.value + 1}, 1_000_000, 0, "gpt-4o")

    runner = StromaRunner(registry, manager, RunConfig()).with_budget(cost_usd=0.01)
    # BudgetExceeded is RECOVERABLE; with default retries it becomes PARTIAL
    result = await runner.run([node1], InputState(value=1))
    assert result.status in (RunStatus.PARTIAL, RunStatus.FAILED)


@pytest.mark.asyncio
async def test_with_classifiers_builder():
    registry = ContractRegistry()
    registry.register(NodeContract(node_id="node1", input_schema=InputState, output_schema=NodeOneOutput))
    store = InMemoryStore()
    manager = CheckpointManager(store)

    @stroma_node("node1", NodeContract(node_id="node1", input_schema=InputState, output_schema=NodeOneOutput))
    async def node1(state: InputState) -> dict:
        raise ValueError("classified as terminal by custom classifier")

    def make_terminal(exc, ctx):
        if isinstance(exc, ValueError):
            return FailureClass.TERMINAL
        return None

    runner = StromaRunner(registry, manager, RunConfig()).with_classifiers([make_terminal])
    result = await runner.run([node1], InputState(value=1))
    assert result.status == RunStatus.FAILED
    assert len(result.trace) == 1


@pytest.mark.asyncio
async def test_with_context_builder():
    registry = ContractRegistry()
    registry.register(NodeContract(node_id="node1", input_schema=InputState, output_schema=NodeOneOutput))
    store = InMemoryStore()
    manager = CheckpointManager(store)

    @stroma_node("node1", NodeContract(node_id="node1", input_schema=InputState, output_schema=NodeOneOutput))
    async def node1(state: InputState, ctx: dict) -> dict:
        return {"result": state.value * ctx["factor"]}

    runner = StromaRunner(registry, manager, RunConfig()).with_context({"factor": 3})
    result = await runner.run([node1], InputState(value=4))
    assert result.status == RunStatus.COMPLETED
    assert result.final_state.result == 12


def test_with_budget_chain_sets_fields():
    runner = StromaRunner.quick().with_budget(tokens=100_000, cost_usd=1.50)
    assert runner.config.budget.max_tokens_total == 100_000
    assert runner.config.budget.max_cost_usd == 1.50


def test_with_context_chain_sets_fields():
    runner = StromaRunner.quick().with_context({"key": "value"})
    assert runner.config.context == {"key": "value"}


def test_with_hooks_chain_sets_fields():
    from unittest.mock import AsyncMock

    from stroma.runner import NodeHooks

    on_success = AsyncMock()
    runner = StromaRunner.quick().with_hooks(NodeHooks(on_node_success=on_success))
    assert runner.config.hooks.on_node_success is on_success


def test_quick_accepts_hooks_kwarg():
    from unittest.mock import AsyncMock

    from stroma.runner import NodeHooks

    on_success = AsyncMock()
    runner = StromaRunner.quick(hooks=NodeHooks(on_node_success=on_success))
    assert runner.config.hooks.on_node_success is on_success


def test_full_builder_chain_is_fluent():
    from unittest.mock import AsyncMock

    from stroma.runner import NodeHooks

    on_success = AsyncMock()
    runner = (
        StromaRunner.quick()
        .with_budget(tokens=100_000)
        .with_context({"key": "value"})
        .with_hooks(NodeHooks(on_node_success=on_success))
    )
    assert runner.config.budget.max_tokens_total == 100_000
    assert runner.config.context == {"key": "value"}
    assert runner.config.hooks.on_node_success is on_success


def test_with_redis_builder_raises_import_error_when_redis_missing(monkeypatch):
    import builtins

    real_import = builtins.__import__

    def fake_import(name, globals=None, locals=None, fromlist=(), level=0):
        if "redis" in name:
            raise ImportError("No module named redis")
        return real_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    runner = StromaRunner.quick()
    with pytest.raises(ImportError, match="redis is required"):
        runner.with_redis("redis://localhost")


# --- Per-node timeout tests ---


@pytest.mark.asyncio
async def test_node_timeout_triggers_retry():
    """A node that exceeds its configured timeout is retried as RECOVERABLE."""
    import asyncio

    registry = ContractRegistry()
    registry.register(NodeContract(node_id="node1", input_schema=InputState, output_schema=NodeOneOutput))
    store = InMemoryStore()
    manager = CheckpointManager(store)

    call_count = {"node1": 0}

    @stroma_node("node1", NodeContract(node_id="node1", input_schema=InputState, output_schema=NodeOneOutput))
    async def slow_node(state: InputState) -> dict:
        call_count["node1"] += 1
        if call_count["node1"] < 2:
            await asyncio.sleep(5)
        return {"result": state.value + 1}

    policy_map = default_policy_map()
    policy_map[FailureClass.RECOVERABLE] = FailurePolicy(max_retries=3, backoff_seconds=0.0)
    config = RunConfig(
        run_id="run_timeout",
        budget=ExecutionBudget.unlimited(),
        policy_map=policy_map,
        node_timeouts={"node1": 50},  # 50ms — first call sleeps 5s, will timeout
    )
    runner = StromaRunner(registry, manager, config)
    result = await runner.run([slow_node], InputState(value=7))

    assert result.status == RunStatus.COMPLETED
    assert call_count["node1"] == 2
    assert result.final_state.result == 8


@pytest.mark.asyncio
async def test_node_timeout_exhausts_retries():
    """A node that always times out exhausts retries and returns PARTIAL."""
    import asyncio

    registry = ContractRegistry()
    registry.register(NodeContract(node_id="node1", input_schema=InputState, output_schema=NodeOneOutput))
    store = InMemoryStore()
    manager = CheckpointManager(store)

    @stroma_node("node1", NodeContract(node_id="node1", input_schema=InputState, output_schema=NodeOneOutput))
    async def always_slow(state: InputState) -> dict:
        await asyncio.sleep(5)
        return {"result": 0}

    policy_map = default_policy_map()
    policy_map[FailureClass.RECOVERABLE] = FailurePolicy(max_retries=2, backoff_seconds=0.0)
    config = RunConfig(
        run_id="run_timeout_exhaust",
        budget=ExecutionBudget.unlimited(),
        policy_map=policy_map,
        node_timeouts={"node1": 50},
    )
    runner = StromaRunner(registry, manager, config)
    result = await runner.run([always_slow], InputState(value=1))

    assert result.status == RunStatus.PARTIAL
    assert all(event.failure == FailureClass.RECOVERABLE for event in result.trace)


def test_with_node_timeouts_builder():
    runner = StromaRunner.quick().with_node_timeouts({"embed": 60_000})
    assert runner.config.node_timeouts == {"embed": 60_000}


# --- Model fallback tests ---


@pytest.mark.asyncio
async def test_model_fallback_injects_context_at_threshold():
    registry = ContractRegistry()
    registry.register(NodeContract(node_id="node1", input_schema=InputState, output_schema=NodeOneOutput))
    registry.register(NodeContract(node_id="node2", input_schema=NodeOneOutput, output_schema=NodeTwoOutput))
    store = InMemoryStore()
    manager = CheckpointManager(store)

    observed_models = []

    @stroma_node("node1", NodeContract(node_id="node1", input_schema=InputState, output_schema=NodeOneOutput))
    async def node1(state: InputState, ctx: dict) -> tuple:
        observed_models.append(ctx.get("_stroma_model"))
        # 320k input tokens at gpt-4o ($2.50/1M) = $0.80 = exactly 80% of $1.00 budget
        return ({"result": state.value + 1}, 320_000, 0, "gpt-4o")

    @stroma_node("node2", NodeContract(node_id="node2", input_schema=NodeOneOutput, output_schema=NodeTwoOutput))
    async def node2(state: NodeOneOutput, ctx: dict) -> tuple:
        observed_models.append(ctx.get("_stroma_model"))
        return ({"total": state.result * 2}, 100, 0, "gpt-4o")

    runner = (
        StromaRunner(registry, manager, RunConfig())
        .with_budget(cost_usd=1.00)
        .with_model_fallback("gpt-4o", to="gpt-4o-mini", at_budget_pct=0.80)
    )
    result = await runner.run([node1, node2], InputState(value=1))

    assert result.status == RunStatus.COMPLETED
    # node1 runs before any spend, so no fallback signal
    assert observed_models[0] is None
    # node2 runs after node1 spent $0.80, which is 80% of $1.00 — fallback fires
    assert observed_models[1] == "gpt-4o-mini"
