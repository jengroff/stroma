import pytest

from stroma.cost import (
    BudgetExceeded,
    CostTracker,
    ExecutionBudget,
    NodeUsage,
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
