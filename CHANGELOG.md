# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.2.0] - 2026-04-01

### Added
- `KNOWN_MODELS` pricing dict and `estimate_cost_usd()` for computing cost from model name and token counts
- `AsyncCheckpointStore` protocol, `AsyncInMemoryStore`, and async `RedisStore` for non-blocking checkpoint I/O
- `SyncRedisStore` alias for the original synchronous Redis store
- `NodeHooks` dataclass with `on_node_start`, `on_node_success`, and `on_node_failure` async callbacks
- `RunConfig.node_policies` for per-node retry policy overrides
- `RunConfig.context` shared dict passed to nodes that accept a second argument
- `parallel()` fan-out primitive for running nodes concurrently with merged output
- Per-run `logging.LoggerAdapter` with `run_id` in structured extra fields
- Fluent builder methods on `StromaRunner`: `with_redis()`, `with_budget()`, `with_classifiers()`, `with_hooks()`, `with_context()`, `with_policy_map()`, `with_node_policies()`
- `StromaRunner.quick()` now accepts an explicit `hooks` keyword argument
- "Extending Stroma" documentation page covering custom checkpoint backends, failure classifiers, OTel integration, and composing all extension points

### Changed
- `NodeUsage` now carries `model` and `output_tokens` fields; `_unpack_output` supports 2/3/4-tuple and bare dict returns
- `CheckpointManager.checkpoint`, `.resume`, `.clear` are now async; call sites in runner updated
- `StromaRunner.quick()` defaults to `AsyncInMemoryStore` instead of `InMemoryStore`
- `ContractViolation.__str__` now surfaces field-level Pydantic errors (up to 5, then truncated)
- `CostTracker`, `RetryBudget`, `ExecutionTrace` instantiated per-run in `run()` instead of `__init__`, preventing state accumulation across calls
- `_handle_failure` looks up per-node policy overrides before falling back to global `policy_map`
- `LangGraphAdapter._wrap_node` raises `TypeError` with the function name when contract is missing, instead of a silent `AttributeError`
- Runner logger calls in `_execute_node` and `_handle_failure` use per-run `LoggerAdapter`, removing inline `run_id` from format strings


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
