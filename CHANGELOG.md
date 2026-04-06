# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.3.2] - 2026-04-05

### Added
- `ReliabilityContext` dataclass in `stroma.middleware` — per-run bundle of all reliability primitives, decoupled from `StromaRunner`
- `execute_step()` standalone async function — the full reliability loop (contracts, cost, retries, checkpoints, tracing) as a freestanding primitive usable without `StromaRunner`
- `StromaStep` class — paradigm-agnostic decorator/wrapper backed by `execute_step()`, equivalent to `StromaRunner.node()` but independent of any execution strategy
- `StepInterceptor`, `LoopAdapter`, `TurnAdapter` protocols in `stroma.adapters.base` — adapter shapes for agentic-loop, conversation-driven, and step-wrapping paradigms
- Step aliases for paradigm-neutral naming: `StepContract`, `StepViolation`, `StepUsage`, `StepContext`, `StepHooks`, `stroma_step`, and `TraceEvent.step_id` property
- `FallbackPolicy` and `resolve_model()` for budget-aware model downgrade during execution
- `StromaRunner.with_model_fallback()` fluent builder for configuring model fallback rules
- `RunConfig.model_fallbacks` field for specifying fallback policies

### Changed
- `StromaRunner` internals refactored to use `ReliabilityContext` — no public API changes, all existing behavior preserved

## [0.3.1] - 2026-04-05

### Added
- `FrameworkAdapter` Protocol in `stroma.adapters.base` — shared contract that all framework adapters implement
- `extract_state_dict()` moved to `stroma.adapters.base` as framework-agnostic utility (re-exported from `stroma.adapters.langgraph` for backwards compatibility)
- `CrewAIAdapter` and `@stroma_crewai_step` decorator for wrapping CrewAI Flow methods with contract validation
- `stroma[crewai]` optional install extra (`crewai>=0.70`)
- Conditional adapter export in `stroma.adapters.__init__` for CrewAI

## [0.3.0] - 2026-04-05

### Added
- Per-node timeout support via `RunConfig.node_timeouts` — wraps node execution with `asyncio.wait_for`, raising `TimeoutError` (classified as `RECOVERABLE`) when exceeded
- `StromaRunner.with_node_timeouts()` fluent builder method
- Retry support for parallel nodes — `_execute_parallel_node` now uses the same `_handle_failure` retry/backoff path as sequential nodes

### Fixed
- `CostTracker.record()` now preserves `model` and `output_tokens` fields when accumulating retries (previously dropped silently)

### Changed
- Parallel node failure tests updated to expect `PARTIAL` (retries exhausted) instead of `FAILED` (immediate), matching the new retry behavior
- Added regression tests for `CostTracker.record()` field accumulation (`model`, `output_tokens`, `None` fallback)
- Added tests for per-node timeout behavior (retry on timeout, exhaustion, fluent builder)
- Updated parallel execution and retry/failure tutorial docs to cover timeouts and parallel retries

### Removed
- `RunConfig.model_hints` field — was accepted but never read by the runner; removed to avoid implying unimplemented capability
- Duplicate `StromaRunner._unpack_output` static method — consolidated to module-level `_unpack_output`

## [0.2.7] - 2026-04-02

### Changed
- Project description unified to "Reliability primitives for agent pipelines." across pyproject.toml, mkdocs.yml, README, and docs homepage

## [0.2.6] - 2026-04-02

### Added
- Per-child contract validation in `parallel()` — each child's output is validated against its declared contract before merging
- Full instrumentation for parallel nodes: hooks (`on_node_start`/`on_node_success`/`on_node_failure`), cost tracking, budget checking, and checkpointing

### Changed
- Parallel failure classification now uses the runner's classifiers instead of hardcoding `AMBIGUOUS`
- Rewrote "Stroma vs. LangGraph" page as an honest comparison with known limitations section

### Removed
- `FailurePolicy.fallback_node_id` — was declared in the model but never implemented in the runner; removed to avoid implying unimplemented capability

## [0.2.5] - 2026-04-02

### Added
- `DeepAgentsAdapter` and `@stroma_deepagents_node` decorator for wrapping deepagents graphs with contract validation and cost tracking
- `stroma[deepagents]` optional install extra (`deepagents>=0.4.0`, `langgraph>=0.2`)
- DeepAgents adapter tab in homepage install section
- DeepAgents tutorial and API reference docs
- Conditional adapter exports in `stroma.adapters.__init__` for both LangGraph and DeepAgents

### Changed
- Homepage rewritten with dbt analogy framing and crash/resume/diff hero example
- README tagline updated to match new homepage positioning
- All `pip install` references across docs, README, source docstrings, and examples replaced with `uv add`
- README Development section now uses `uv sync --extra dev` instead of `uv pip install -e`
- `CLAUDE.md` expanded with project layout, quality gate commands, optional extras pattern, testing, and docs conventions

## [0.2.4] - 2026-04-01

### Added
- Quickstart page with contract, retry, checkpoint/resume, and trace demos
- "Stroma vs. LangGraph" comparison page
- Stability section in Concepts (stable / beta / experimental primitives)
- Homepage before/after section and focused "what you get" bullets
- Runnable examples: `simple_pipeline.py`, `retry_demo.py`, `checkpoint_resume.py`, `langgraph_integration.py`
- AGENTS.md with Claude Code agent instructions

### Fixed
- `RunConfig` API reference now shows per-field descriptions
- OTel example in `extending.md` no longer silently drops spans when a node is retried
- README "What You Get" bullets now include the fluent builder API
- `parallel()` contract bypass documented as an explicit warning admonition in Concepts
- `on_node_success` `tokens_used` argument semantics documented (input + output tokens, `0` if unreported)
- `KNOWN_MODELS` pricing table added to Concepts page so models and prices are discoverable without reading source
- README Install section now states the Python 3.12+ requirement
- Home page Next Steps section replaced broken table-as-cards with a clean bullet list
- API reference for `stroma_node` now explains when to use it vs `@runner.node`
- Softened vs-LangGraph tone, added side-by-side capability table

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
