# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.2.0] - 2026-04-01

### Added
- `KNOWN_MODELS` pricing dict and `estimate_cost_usd()` for computing cost from model name and token counts (Task 01)
- `AsyncCheckpointStore` protocol, `AsyncInMemoryStore`, and async `RedisStore` for non-blocking checkpoint I/O (Task 02)
- `SyncRedisStore` alias for the original synchronous Redis store (Task 02)
- `NodeHooks` dataclass with `on_node_start`, `on_node_success`, and `on_node_failure` async callbacks (Task 06)
- `RunConfig.node_policies` for per-node retry policy overrides (Task 05)
- `RunConfig.context` shared dict passed to nodes that accept a second argument (Task 08)
- `parallel()` fan-out primitive for running nodes concurrently with merged output (Task 10)
- Per-run `logging.LoggerAdapter` with `run_id` in structured extra fields (Task 09)

### Changed
- `NodeUsage` now carries `model` and `output_tokens` fields; `_unpack_output` supports 2/3/4-tuple and bare dict returns (Task 01)
- `CheckpointManager.checkpoint`, `.resume`, `.clear` are now async; call sites in runner updated (Task 02)
- `StromaRunner.quick()` defaults to `AsyncInMemoryStore` instead of `InMemoryStore` (Task 02)
- `ContractViolation.__str__` now surfaces field-level Pydantic errors (up to 5, then truncated) (Task 03)
- `CostTracker`, `RetryBudget`, `ExecutionTrace` instantiated per-run in `run()` instead of `__init__`, preventing state accumulation across calls (Task 04)
- `_handle_failure` looks up per-node policy overrides before falling back to global `policy_map` (Task 05)
- `LangGraphAdapter._wrap_node` raises `TypeError` with the function name when contract is missing, instead of a silent `AttributeError` (Task 07)
- Runner logger calls in `_execute_node` and `_handle_failure` use per-run `LoggerAdapter`, removing inline `run_id` from format strings (Task 09)

### Added
- `StromaRunner` (replaces `ArmatureRunner`) with decomposed `_execute_node` / `_handle_failure` methods
- `stroma_node` decorator (replaces `armature_node`)
- `stroma_langgraph_node` decorator (replaces `armature_langgraph_node`)
- Custom failure classifiers via `RunConfig.classifiers`
- `Classifier` type alias exported from top-level package
- `CostTracker.total_latency_ms` property for aggregate latency tracking
- Structured logging via `logging.getLogger(__name__)` in the runner
- `pytest-cov` with 85% coverage floor in CI
- `ty` for type checking (replaces `mypy`)
- Expanded ruff rules: `B`, `SIM`, `RUF` for catching real bugs
- Pre-commit hooks for ruff, ruff-format, ty, and general file checks (large files, merge conflicts, trailing whitespace, debug statements)
- CHANGELOG.md
- MkDocs documentation site with mkdocstrings

### Changed
- Moved source from `src/` to `src/stroma/` for proper namespace packaging
- Moved `mkdocs` from core dependencies to `docs` optional extra
- CI and publish workflows use `uv` instead of `pip`/`python -m build`
- CI workflow triggers on `main` branch (was incorrectly set to `master`)
- Docstrings reformatted to markdown prose style, removing sectioned formats (`Args:`, `Returns:`, `Raises:`, `Attributes:`)
- Removed module-level docstrings from all files
- All budget dimensions (tokens, cost, latency) now check **aggregate** totals, not per-node values
- `RedisStore.delete()` now uses a pipeline for batched key deletion
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
