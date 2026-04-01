from stroma.contracts import ContractViolation
from stroma.failures import (
    FailureClass,
    FailurePolicy,
    NodeContext,
    RetryBudget,
    classify,
    default_policy_map,
)


def test_default_policy_map_contains_all_classes():
    policies = default_policy_map()
    assert set(policies) == {FailureClass.RECOVERABLE, FailureClass.TERMINAL, FailureClass.AMBIGUOUS}
    assert policies[FailureClass.TERMINAL].max_retries == 0
    assert policies[FailureClass.RECOVERABLE].backoff_seconds == 1.0
    assert policies[FailureClass.AMBIGUOUS].max_retries == 1


def test_classify_contract_violation_returns_terminal():
    context = NodeContext(node_id="node1", attempt=1, run_id="run1")
    result = classify(ContractViolation("node1", "input", {}, []), context)
    assert result is FailureClass.TERMINAL


def test_classify_timeout_error_returns_recoverable():
    context = NodeContext(node_id="node1", attempt=1, run_id="run1")
    result = classify(TimeoutError(), context)
    assert result is FailureClass.RECOVERABLE


def test_classify_value_error_returns_ambiguous():
    context = NodeContext(node_id="node1", attempt=1, run_id="run1")
    result = classify(ValueError("bad"), context)
    assert result is FailureClass.AMBIGUOUS


def test_classify_unknown_exception_returns_ambiguous():
    context = NodeContext(node_id="node1", attempt=1, run_id="run1")
    result = classify(RuntimeError("oops"), context)
    assert result is FailureClass.AMBIGUOUS


def test_classify_budget_exceeded_returns_recoverable():
    from stroma.cost import BudgetExceeded

    context = NodeContext(node_id="node1", attempt=1, run_id="run1")
    result = classify(BudgetExceeded("tokens", 10.0, 15.0, "node1"), context)
    assert result is FailureClass.RECOVERABLE


def test_custom_classifier_override():
    def always_terminal(exc, ctx):
        return FailureClass.TERMINAL

    context = NodeContext(node_id="node1", attempt=1, run_id="run1")
    result = classify(ValueError("bad"), context, classifiers=[always_terminal])
    assert result is FailureClass.TERMINAL


def test_retry_budget_exhaustion():
    budget = RetryBudget()
    policy = FailurePolicy(max_retries=2)
    budget.increment("run1", "node1")
    assert not budget.exhausted("run1", "node1", policy)
    budget.increment("run1", "node1")
    assert budget.exhausted("run1", "node1", policy)


def test_retry_budget_separate_run_node_counts():
    budget = RetryBudget()
    policy = FailurePolicy(max_retries=1)
    budget.increment("run1", "node1")
    assert budget.exhausted("run1", "node1", policy)
    assert not budget.exhausted("run2", "node1", policy)
    assert not budget.exhausted("run1", "node2", policy)
