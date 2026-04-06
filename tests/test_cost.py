import pytest

from stroma.cost import (
    KNOWN_MODELS,
    BudgetExceeded,
    CostTracker,
    ExecutionBudget,
    FallbackPolicy,
    NodeUsage,
    estimate_cost_usd,
    resolve_model,
)


def test_record_and_accumulate_usage():
    tracker = CostTracker()
    tracker.record(NodeUsage(node_id="node1", tokens_used=10, cost_usd=0.5, latency_ms=50))
    tracker.record(NodeUsage(node_id="node1", tokens_used=5, cost_usd=0.2, latency_ms=30))
    assert tracker.total_tokens == 15
    assert tracker.total_cost_usd == 0.7
    assert tracker.total_latency_ms == 80
    assert tracker.summary()["node1"].latency_ms == 80


def test_budget_not_exceeded():
    tracker = CostTracker()
    tracker.record(NodeUsage(node_id="node1", tokens_used=10, cost_usd=0.5, latency_ms=50))
    budget = ExecutionBudget(max_tokens_total=20, max_cost_usd=1.0, max_latency_ms=100)
    tracker.check_budget(budget, "node1")


def test_budget_exceeded_tokens():
    tracker = CostTracker()
    tracker.record(NodeUsage(node_id="node1", tokens_used=25, cost_usd=0.5, latency_ms=50))
    budget = ExecutionBudget(max_tokens_total=20)
    with pytest.raises(BudgetExceeded) as exc_info:
        tracker.check_budget(budget, "node1")
    exc = exc_info.value
    assert exc.dimension == "tokens"
    assert exc.limit == 20.0
    assert exc.actual == 25.0
    assert exc.node_id == "node1"


def test_budget_exceeded_cost_is_aggregate():
    """Cost budget checks total cost across all nodes, not per-node."""
    tracker = CostTracker()
    tracker.record(NodeUsage(node_id="node1", tokens_used=10, cost_usd=0.6, latency_ms=50))
    tracker.record(NodeUsage(node_id="node2", tokens_used=10, cost_usd=0.6, latency_ms=50))
    budget = ExecutionBudget(max_cost_usd=1.0)
    with pytest.raises(BudgetExceeded) as exc_info:
        tracker.check_budget(budget, "node2")
    assert exc_info.value.dimension == "cost"
    assert exc_info.value.actual == 1.2


def test_budget_exceeded_latency_is_aggregate():
    """Latency budget checks total latency across all nodes."""
    tracker = CostTracker()
    tracker.record(NodeUsage(node_id="node1", tokens_used=10, cost_usd=0.5, latency_ms=60))
    tracker.record(NodeUsage(node_id="node2", tokens_used=10, cost_usd=0.5, latency_ms=60))
    budget = ExecutionBudget(max_latency_ms=100)
    with pytest.raises(BudgetExceeded) as exc_info:
        tracker.check_budget(budget, "node2")
    assert exc_info.value.dimension == "latency"
    assert exc_info.value.actual == 120


def test_unlimited_budget_never_raises():
    tracker = CostTracker()
    tracker.record(NodeUsage(node_id="node1", tokens_used=1000, cost_usd=100.0, latency_ms=5000))
    budget = ExecutionBudget.unlimited()
    tracker.check_budget(budget, "node1")


def test_summary_keyed_by_node_id():
    tracker = CostTracker()
    tracker.record(NodeUsage(node_id="node1", tokens_used=10, cost_usd=0.5, latency_ms=20))
    tracker.record(NodeUsage(node_id="node2", tokens_used=5, cost_usd=0.25, latency_ms=10))
    summary = tracker.summary()
    assert set(summary) == {"node1", "node2"}
    assert summary["node2"].tokens_used == 5


def test_estimate_cost_known_model():
    cost = estimate_cost_usd("gpt-4o", input_tokens=1_000_000, output_tokens=0)
    assert cost == pytest.approx(2.50)


def test_estimate_cost_known_model_output_tokens():
    cost = estimate_cost_usd("gpt-4o-mini", input_tokens=0, output_tokens=1_000_000)
    assert cost == pytest.approx(0.60)


def test_estimate_cost_unknown_model_returns_zero():
    assert estimate_cost_usd("unknown-model-xyz", 100, 100) == 0.0


def test_record_accumulates_model_and_output_tokens():
    """model and output_tokens must survive accumulation across retries."""
    tracker = CostTracker()
    tracker.record(
        NodeUsage(node_id="llm", tokens_used=100, cost_usd=0.01, latency_ms=200, model="gpt-4o", output_tokens=50)
    )
    tracker.record(
        NodeUsage(node_id="llm", tokens_used=80, cost_usd=0.008, latency_ms=150, model="gpt-4o", output_tokens=40)
    )
    usage = tracker.summary()["llm"]
    assert usage.model == "gpt-4o"
    assert usage.output_tokens == 90
    assert usage.tokens_used == 180


def test_record_accumulates_model_fallback_when_none():
    """If a retry omits model, the existing model is preserved."""
    tracker = CostTracker()
    tracker.record(
        NodeUsage(node_id="llm", tokens_used=100, cost_usd=0.01, latency_ms=200, model="gpt-4o", output_tokens=50)
    )
    tracker.record(
        NodeUsage(node_id="llm", tokens_used=80, cost_usd=0.008, latency_ms=150, model=None, output_tokens=30)
    )
    usage = tracker.summary()["llm"]
    assert usage.model == "gpt-4o"
    assert usage.output_tokens == 80


def test_known_models_registry_is_not_empty():
    assert len(KNOWN_MODELS) > 0
    assert all(len(v) == 2 for v in KNOWN_MODELS.values())


# --- resolve_model / FallbackPolicy ---


def test_resolve_model_below_threshold_no_swap():
    tracker = CostTracker()
    tracker.record(NodeUsage(node_id="n1", tokens_used=0, cost_usd=0.50, latency_ms=10))
    budget = ExecutionBudget(max_cost_usd=1.00)
    policy = FallbackPolicy(preferred_model="gpt-4o", fallback_model="gpt-4o-mini", at_budget_pct=0.80)
    result = resolve_model("gpt-4o", tracker, budget, [policy])
    assert result == "gpt-4o"


def test_resolve_model_at_threshold_swaps():
    tracker = CostTracker()
    tracker.record(NodeUsage(node_id="n1", tokens_used=0, cost_usd=0.80, latency_ms=10))
    budget = ExecutionBudget(max_cost_usd=1.00)
    policy = FallbackPolicy(preferred_model="gpt-4o", fallback_model="gpt-4o-mini", at_budget_pct=0.80)
    result = resolve_model("gpt-4o", tracker, budget, [policy])
    assert result == "gpt-4o-mini"


def test_resolve_model_no_budget_no_swap():
    tracker = CostTracker()
    tracker.record(NodeUsage(node_id="n1", tokens_used=0, cost_usd=999.0, latency_ms=10))
    budget = ExecutionBudget.unlimited()
    policy = FallbackPolicy(preferred_model="gpt-4o", fallback_model="gpt-4o-mini")
    result = resolve_model("gpt-4o", tracker, budget, [policy])
    assert result == "gpt-4o"


def test_resolve_model_mismatch_no_swap():
    tracker = CostTracker()
    tracker.record(NodeUsage(node_id="n1", tokens_used=0, cost_usd=0.90, latency_ms=10))
    budget = ExecutionBudget(max_cost_usd=1.00)
    policy = FallbackPolicy(preferred_model="gpt-4o", fallback_model="gpt-4o-mini")
    result = resolve_model("claude-sonnet-4-6", tracker, budget, [policy])
    assert result == "claude-sonnet-4-6"


def test_resolve_model_none_declared_passes_through():
    tracker = CostTracker()
    budget = ExecutionBudget(max_cost_usd=1.00)
    policy = FallbackPolicy(preferred_model="gpt-4o", fallback_model="gpt-4o-mini")
    result = resolve_model(None, tracker, budget, [policy])
    assert result is None
