import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))))

from docs.examples.agentic_loop.agent import (
    TOOL_REGISTRY,
    AgentState,
    ToolCall,
    ToolResult,
    mock_model_decision,
)
from stroma.checkpoint import AsyncInMemoryStore, CheckpointManager
from stroma.contracts import ContractRegistry, NodeContract
from stroma.cost import ExecutionBudget
from stroma.middleware import ReliabilityContext, execute_step
from stroma.runner import RunConfig

search_contract = NodeContract(node_id="search", input_schema=ToolCall, output_schema=ToolResult)
fetch_contract = NodeContract(node_id="fetch", input_schema=ToolCall, output_schema=ToolResult)
synthesize_contract = NodeContract(node_id="synthesize", input_schema=ToolCall, output_schema=ToolResult)


async def search_step(tc: ToolCall) -> dict:
    result = await TOOL_REGISTRY["search"](tc.query)
    return result.model_dump()


async def fetch_step(tc: ToolCall) -> dict:
    result = await TOOL_REGISTRY["fetch"](tc.query)
    return result.model_dump()


async def synthesize_step(tc: ToolCall) -> dict:
    result = await TOOL_REGISTRY["synthesize"](tc.query)
    return result.model_dump()


STEP_REGISTRY: dict[str, object] = {
    "search": search_step,
    "fetch": fetch_step,
    "synthesize": synthesize_step,
}

CONTRACT_REGISTRY_MAP: dict[str, NodeContract] = {
    "search": search_contract,
    "fetch": fetch_contract,
    "synthesize": synthesize_contract,
}


async def main() -> None:
    registry = ContractRegistry()
    registry.register(search_contract)
    registry.register(fetch_contract)
    registry.register(synthesize_contract)

    store = AsyncInMemoryStore()
    manager = CheckpointManager(store)
    config = RunConfig(run_id="research-agent-1", budget=ExecutionBudget(max_tokens_total=5000))
    ctx = ReliabilityContext.for_run(config, registry, manager)

    state = AgentState(question="What is Stroma?", steps=[], done=False)

    while len(state.steps) < 10:
        call = mock_model_decision(state)
        if call.action == "done":
            break

        step_fn = STEP_REGISTRY[call.action]
        contract = CONTRACT_REGISTRY_MAP[call.action]

        step_result = await execute_step(call.action, step_fn, call, ctx, contract=contract)
        tool_result = step_result.final_state

        state = state.model_copy(update={"steps": [*state.steps, tool_result]})
        print(f"  {tool_result.action}: {tool_result.content}")

    print(f"\nTotal steps: {len(state.steps)}")
    print(f"Total tokens used: {ctx.cost_tracker.total_tokens}")
    retries = any(event.attempt > 1 for event in ctx.trace)
    print(f"Retries occurred: {retries}")
    print(f"Final answer: {state.steps[-1].content}")


if __name__ == "__main__":
    asyncio.run(main())
