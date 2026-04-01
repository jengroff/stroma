"""Stroma — framework-agnostic reliability primitives for agent pipelines.

Provides contracts, checkpointing, cost tracking, failure classification,
and execution tracing for building robust LLM agent systems.
"""

from stroma.checkpoint import CheckpointManager, CheckpointStore, InMemoryStore, RedisStore
from stroma.contracts import BoundaryValidator, ContractRegistry, ContractViolation, NodeContract
from stroma.cost import BudgetExceeded, CostTracker, ExecutionBudget, ModelHint, NodeUsage
from stroma.failures import (
    Classifier,
    FailureClass,
    FailurePolicy,
    NodeContext,
    RetryBudget,
    classify,
    default_policy_map,
)
from stroma.runner import ArmatureRunner, RunConfig, StromaRunner, armature_node, stroma_node
from stroma.trace import ExecutionResult, ExecutionTrace, RunStatus, TraceEvent

__version__ = "0.1.1"

__all__ = [
    "ArmatureRunner",  # backwards-compatible alias
    # Contracts
    "BoundaryValidator",
    # Cost
    "BudgetExceeded",
    # Checkpointing
    "CheckpointManager",
    "CheckpointStore",
    # Failures
    "Classifier",
    "ContractRegistry",
    "ContractViolation",
    "CostTracker",
    "ExecutionBudget",
    # Trace
    "ExecutionResult",
    "ExecutionTrace",
    "FailureClass",
    "FailurePolicy",
    "InMemoryStore",
    "ModelHint",
    "NodeContext",
    "NodeContract",
    "NodeUsage",
    "RedisStore",
    "RetryBudget",
    "RunConfig",
    "RunStatus",
    # Runner
    "StromaRunner",
    "TraceEvent",
    "armature_node",  # backwards-compatible alias
    "classify",
    "default_policy_map",
    "stroma_node",
]
