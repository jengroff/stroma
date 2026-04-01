# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- `StromaRunner` (replaces `ArmatureRunner`) with decomposed `_execute_node` / `_handle_failure` methods
- `stroma_node` decorator (replaces `armature_node`)
- `stroma_langgraph_node` decorator (replaces `armature_langgraph_node`)
- Custom failure classifiers via `RunConfig.classifiers`
- `Classifier` type alias exported from top-level package
- `CostTracker.total_latency_ms` property for aggregate latency tracking
- Structured logging via `logging.getLogger(__name__)` in the runner
- Comprehensive docstrings on all public classes, methods, and functions
- `pytest-cov` with 90% coverage floor in CI
- `ty` for type checking (replaces `mypy`)
- Expanded ruff rules: `B`, `SIM`, `RUF` for catching real bugs
- Pre-commit hooks for ruff and ty
- CHANGELOG.md
- MkDocs documentation site with mkdocstrings

### Changed
- All budget dimensions (tokens, cost, latency) now check **aggregate** totals, not per-node values
- `RedisStore.delete()` now uses a pipeline for batched key deletion
- CI workflow triggers on `master` branch (was incorrectly set to `main`)
- Failed/partial runs now preserve the last valid state in `final_state` instead of `None`
- Lazy import of `BudgetExceeded` in `classify()` replaced with direct import
- Removed unused `node_id` variable in `LangGraphAdapter._wrap_node`

### Deprecated
- `ArmatureRunner` — use `StromaRunner` instead (alias retained for backwards compatibility)
- `armature_node` — use `stroma_node` instead (alias retained)
- `armature_langgraph_node` — use `stroma_langgraph_node` instead (alias retained)

## [0.1.1] - 2026-03-31

### Fixed
- `UnboundLocalError` guard for `input_model` in runner
- Retry jitter using `random.uniform(0, backoff_seconds)`
- Redis key prefix changed from `armature:` to `stroma:`
- `ExecutionTrace.diff()` now excludes `timestamp_utc` and `duration_ms`
- `LangGraphAdapter._wrap_node` returns validated model output
- `NodeContext` and `RetryBudget` added to `__all__`
- `pytest-asyncio` floor version pinned to `>=0.23`

## [0.1.0] - 2026-03-30

### Added
- Initial release
- `ArmatureRunner` for sequential node execution with retries
- `ContractRegistry` and `NodeContract` for input/output validation
- `CheckpointManager` with `InMemoryStore` and `RedisStore` backends
- `CostTracker` and `ExecutionBudget` for resource tracking
- `FailureClass`, `FailurePolicy`, and `classify()` for failure handling
- `ExecutionTrace` and `TraceEvent` for execution recording
- `LangGraphAdapter` for integrating with LangGraph pipelines
