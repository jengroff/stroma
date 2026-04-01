"""Failure classification, retry policies, and retry budget tracking."""

from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum

from pydantic import BaseModel

from stroma.contracts import ContractViolation
from stroma.cost import BudgetExceeded


class FailureClass(StrEnum):
    """Classification of a pipeline failure for deciding retry behavior.

    - ``RECOVERABLE``: The failure is transient and the node should be retried.
    - ``TERMINAL``: The failure is permanent and the pipeline should stop.
    - ``AMBIGUOUS``: The failure may or may not be recoverable; limited retries are attempted.
    """

    RECOVERABLE = "RECOVERABLE"
    TERMINAL = "TERMINAL"
    AMBIGUOUS = "AMBIGUOUS"


class FailurePolicy(BaseModel):
    """Retry behavior for a given failure class.

    Attributes:
        max_retries: Maximum number of retry attempts before giving up.
        backoff_seconds: Maximum backoff duration in seconds (actual delay is jittered).
        fallback_node_id: Optional node to route to instead of retrying.

    Example::

        # Aggressive retries for recoverable errors
        policy = FailurePolicy(max_retries=5, backoff_seconds=2.0)

        # No retries for terminal errors
        policy = FailurePolicy(max_retries=0, backoff_seconds=0.0)
    """

    max_retries: int = 3
    backoff_seconds: float = 1.0
    fallback_node_id: str | None = None


PolicyMap = dict[FailureClass, FailurePolicy]


def default_policy_map() -> PolicyMap:
    """Return the default retry policies for each failure class.

    - ``RECOVERABLE``: 3 retries, 1s backoff
    - ``TERMINAL``: 0 retries, no backoff
    - ``AMBIGUOUS``: 1 retry, 0.5s backoff
    """
    return {
        FailureClass.RECOVERABLE: FailurePolicy(max_retries=3, backoff_seconds=1.0),
        FailureClass.TERMINAL: FailurePolicy(max_retries=0, backoff_seconds=0.0),
        FailureClass.AMBIGUOUS: FailurePolicy(max_retries=1, backoff_seconds=0.5),
    }


@dataclass
class NodeContext:
    """Context passed to failure classifiers for making classification decisions.

    Attributes:
        node_id: The node that raised the exception.
        attempt: The attempt number (1-based) when the failure occurred.
        run_id: The pipeline run identifier.
    """

    node_id: str
    attempt: int
    run_id: str


Classifier = Callable[[Exception, NodeContext], FailureClass | None]
"""A callable that inspects an exception and context, returning a FailureClass or None to defer."""


def classify(exc: Exception, context: NodeContext, classifiers: list[Classifier] | None = None) -> FailureClass:
    """Determine the failure class of an exception.

    Custom classifiers are checked first in order. If none return a result,
    built-in rules apply:

    - :class:`~stroma.contracts.ContractViolation` → ``TERMINAL``
    - :class:`~stroma.cost.BudgetExceeded` → ``RECOVERABLE``
    - :class:`TimeoutError` → ``RECOVERABLE``
    - :class:`ValueError` → ``AMBIGUOUS``
    - Everything else → ``AMBIGUOUS``

    Args:
        exc: The exception to classify.
        context: Execution context at the time of failure.
        classifiers: Optional list of custom classifiers to check first.

    Returns:
        The determined failure class.
    """
    if classifiers:
        for classifier in classifiers:
            result = classifier(exc, context)
            if result is not None:
                return result
    if isinstance(exc, ContractViolation):
        return FailureClass.TERMINAL
    if isinstance(exc, BudgetExceeded):
        return FailureClass.RECOVERABLE
    if isinstance(exc, TimeoutError):
        return FailureClass.RECOVERABLE
    if isinstance(exc, ValueError):
        return FailureClass.AMBIGUOUS
    return FailureClass.AMBIGUOUS


class RetryBudget:
    """Tracks retry counts per (run_id, node_id) pair and enforces limits."""

    def __init__(self) -> None:
        self._counts: defaultdict[tuple[str, str], int] = defaultdict(int)

    def increment(self, run_id: str, node_id: str) -> int:
        """Increment and return the retry count for the given run/node pair."""
        self._counts[(run_id, node_id)] += 1
        return self._counts[(run_id, node_id)]

    def exhausted(self, run_id: str, node_id: str, policy: FailurePolicy) -> bool:
        """Return ``True`` if the retry count has reached the policy's max_retries."""
        return self._counts[(run_id, node_id)] >= policy.max_retries
