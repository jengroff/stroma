"""Cost tracking and budget enforcement for pipeline execution."""

from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel


@dataclass
class ModelHint:
    """Hint for model selection on a per-node basis.

    Attributes:
        node_id: Node this hint applies to.
        preferred_model: Primary model identifier to use.
        fallback_model: Model to fall back to if the preferred model is unavailable.
        max_tokens: Optional token limit for this node's LLM call.
    """

    node_id: str
    preferred_model: str
    fallback_model: str | None = None
    max_tokens: int | None = None


class ExecutionBudget(BaseModel):
    """Optional budget constraints for a pipeline run.

    All fields are optional — ``None`` means no limit on that dimension.

    Attributes:
        max_tokens_total: Maximum total tokens across all nodes.
        max_cost_usd: Maximum total cost in USD across all nodes.
        max_latency_ms: Maximum total latency in milliseconds across all nodes.

    Example::

        # No limits (default)
        budget = ExecutionBudget.unlimited()

        # Constrain tokens and cost
        budget = ExecutionBudget(max_tokens_total=10_000, max_cost_usd=0.50)
    """

    max_tokens_total: int | None = None
    max_cost_usd: float | None = None
    max_latency_ms: int | None = None

    @classmethod
    def unlimited(cls) -> "ExecutionBudget":
        """Return a budget with no constraints on any dimension."""
        return cls(max_tokens_total=None, max_cost_usd=None, max_latency_ms=None)


@dataclass
class NodeUsage:
    """Observed resource usage for a single node execution.

    Attributes:
        node_id: The node that was executed.
        tokens_used: Number of tokens consumed.
        cost_usd: Cost in USD for this execution.
        latency_ms: Wall-clock duration in milliseconds.
    """

    node_id: str
    tokens_used: int
    cost_usd: float
    latency_ms: int


class BudgetExceeded(Exception):
    """Raised when cumulative resource usage exceeds a budget limit.

    Attributes:
        dimension: Which budget dimension was exceeded (``"tokens"``, ``"cost"``, or ``"latency"``).
        limit: The budget cap that was exceeded.
        actual: The actual cumulative value that triggered the violation.
        node_id: The node whose execution caused the budget to be exceeded.
    """

    def __init__(self, dimension: Literal["tokens", "cost", "latency"], limit: float, actual: float, node_id: str):
        self.dimension = dimension
        self.limit = limit
        self.actual = actual
        self.node_id = node_id
        super().__init__(f"Budget exceeded {dimension} for {node_id}: {actual} > {limit}")


class CostTracker:
    """Accumulates per-node resource usage and checks it against budgets.

    Usage is keyed by ``node_id`` and accumulated across multiple calls to
    :meth:`record` for the same node.

    Example::

        tracker = CostTracker()
        tracker.record(NodeUsage(node_id="llm", tokens_used=500, cost_usd=0.01, latency_ms=200))
        tracker.check_budget(ExecutionBudget(max_tokens_total=1000), "llm")
        print(tracker.total_tokens)  # 500
    """

    def __init__(self) -> None:
        self._usage: dict[str, NodeUsage] = {}

    def record(self, usage: NodeUsage) -> None:
        """Record a node execution's resource usage, accumulating with any prior usage for that node."""
        existing = self._usage.get(usage.node_id)
        if existing is None:
            self._usage[usage.node_id] = usage
            return
        self._usage[usage.node_id] = NodeUsage(
            node_id=usage.node_id,
            tokens_used=existing.tokens_used + usage.tokens_used,
            cost_usd=existing.cost_usd + usage.cost_usd,
            latency_ms=existing.latency_ms + usage.latency_ms,
        )

    def check_budget(self, budget: ExecutionBudget, node_id: str) -> None:
        """Check aggregate usage across all nodes against the budget.

        Raises:
            BudgetExceeded: If any budget dimension is exceeded.
        """
        if budget.max_tokens_total is not None and self.total_tokens > budget.max_tokens_total:
            raise BudgetExceeded("tokens", float(budget.max_tokens_total), float(self.total_tokens), node_id)
        if budget.max_cost_usd is not None and self.total_cost_usd > budget.max_cost_usd:
            raise BudgetExceeded("cost", float(budget.max_cost_usd), float(self.total_cost_usd), node_id)
        if budget.max_latency_ms is not None and self.total_latency_ms > budget.max_latency_ms:
            raise BudgetExceeded("latency", float(budget.max_latency_ms), float(self.total_latency_ms), node_id)

    @property
    def total_tokens(self) -> int:
        """Total tokens consumed across all nodes."""
        return sum(usage.tokens_used for usage in self._usage.values())

    @property
    def total_cost_usd(self) -> float:
        """Total cost in USD across all nodes."""
        return sum(usage.cost_usd for usage in self._usage.values())

    @property
    def total_latency_ms(self) -> int:
        """Total latency in milliseconds across all nodes."""
        return sum(usage.latency_ms for usage in self._usage.values())

    def summary(self) -> dict[str, NodeUsage]:
        """Return a copy of the per-node usage map."""
        return dict(self._usage)
