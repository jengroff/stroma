from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel

KNOWN_MODELS: dict[str, tuple[float, float]] = {
    # model_id: (input_price_per_1m_tokens, output_price_per_1m_tokens) in USD
    "gpt-4o": (2.50, 10.00),
    "gpt-4o-mini": (0.15, 0.60),
    "gpt-4-turbo": (10.00, 30.00),
    "claude-opus-4-6": (15.00, 75.00),
    "claude-sonnet-4-6": (3.00, 15.00),
    "claude-haiku-4-5": (0.80, 4.00),
    "gemini-1.5-pro": (3.50, 10.50),
    "gemini-1.5-flash": (0.35, 1.05),
}


def estimate_cost_usd(model: str, input_tokens: int, output_tokens: int = 0) -> float:
    """Estimate the USD cost for a given model and token counts.

    Looks up the model in `KNOWN_MODELS` and calculates cost based on
    per-million-token pricing. Returns `0.0` for unknown models.
    """
    prices = KNOWN_MODELS.get(model)
    if prices is None:
        return 0.0
    input_price, output_price = prices
    return (input_tokens * input_price + output_tokens * output_price) / 1_000_000


@dataclass
class ModelHint:
    """Hint for model selection on a per-node basis.

    Binds a `node_id` to a `preferred_model` with an optional
    `fallback_model` and per-node `max_tokens` limit.
    """

    node_id: str
    preferred_model: str
    fallback_model: str | None = None
    max_tokens: int | None = None


class ExecutionBudget(BaseModel):
    """Optional budget constraints for a pipeline run.

    All fields are optional — `None` means no limit on that dimension.
    Set `max_tokens_total`, `max_cost_usd`, and/or `max_latency_ms` to
    cap resource usage across all nodes.

    ## Example

    ```python
    budget = ExecutionBudget.unlimited()
    budget = ExecutionBudget(max_tokens_total=10_000, max_cost_usd=0.50)
    ```
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

    Records `tokens_used`, `cost_usd`, and `latency_ms` for the given
    `node_id`.
    """

    node_id: str
    tokens_used: int
    cost_usd: float
    latency_ms: int
    model: str | None = None
    output_tokens: int = 0


class BudgetExceeded(Exception):
    """Raised when cumulative resource usage exceeds a budget limit.

    Carries the `dimension` (`"tokens"`, `"cost"`, or `"latency"`), the
    `limit` that was exceeded, the `actual` cumulative value, and the
    `node_id` that triggered the violation.
    """

    def __init__(self, dimension: Literal["tokens", "cost", "latency"], limit: float, actual: float, node_id: str):
        self.dimension = dimension
        self.limit = limit
        self.actual = actual
        self.node_id = node_id
        super().__init__(f"Budget exceeded {dimension} for {node_id}: {actual} > {limit}")


class CostTracker:
    """Accumulates per-node resource usage and checks it against budgets.

    Usage is keyed by `node_id` and accumulated across multiple calls to
    `record()` for the same node.

    ## Example

    ```python
    tracker = CostTracker()
    tracker.record(NodeUsage(node_id="llm", tokens_used=500, cost_usd=0.01, latency_ms=200))
    tracker.check_budget(ExecutionBudget(max_tokens_total=1000), "llm")
    print(tracker.total_tokens)  # 500
    ```
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

        Raises `BudgetExceeded` if any dimension is exceeded.
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
