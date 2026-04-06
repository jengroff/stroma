import asyncio

from pydantic import BaseModel


class ToolCall(BaseModel):
    action: str
    query: str


class ToolResult(BaseModel):
    action: str
    content: str
    tokens_used: int


class AgentState(BaseModel):
    question: str
    steps: list[ToolResult]
    done: bool


_fetch_call_count: dict[str, int] = {"n": 0}


async def search(query: str) -> ToolResult:
    return ToolResult(action="search", content=f"Found 3 results for: {query}", tokens_used=50)


async def fetch(query: str) -> ToolResult:
    _fetch_call_count["n"] += 1
    if _fetch_call_count["n"] == 1:
        raise TimeoutError("upstream timeout")
    return ToolResult(action="fetch", content=f"Page content for: {query}", tokens_used=120)


async def synthesize(query: str) -> ToolResult:
    return ToolResult(action="synthesize", content=f"Summary: {query} involves multiple concepts", tokens_used=200)


TOOL_REGISTRY: dict[str, object] = {"search": search, "fetch": fetch, "synthesize": synthesize}


def mock_model_decision(state: AgentState) -> ToolCall:
    n = len(state.steps)
    if n == 0:
        return ToolCall(action="search", query=state.question)
    if n == 1:
        return ToolCall(action="fetch", query=state.question)
    if n == 2:
        return ToolCall(action="fetch", query=state.question)
    if n == 3:
        return ToolCall(action="synthesize", query=state.question)
    return ToolCall(action="done", query="")


async def run_agent(question: str) -> AgentState:
    state = AgentState(question=question, steps=[], done=False)
    while len(state.steps) < 10:
        call = mock_model_decision(state)
        if call.action == "done":
            break
        tool_fn = TOOL_REGISTRY[call.action]
        result = await tool_fn(call.query)
        state = state.model_copy(update={"steps": [*state.steps, result]})
    return state.model_copy(update={"done": True})


async def main() -> None:
    try:
        state = await run_agent("What is Stroma?")
        for step in state.steps:
            print(f"  {step.action}: {step.content}")
    except TimeoutError as exc:
        print(f"  Agent crashed: {exc}")
        print("  (This is the problem Stroma solves — see with_stroma.py)")


if __name__ == "__main__":
    asyncio.run(main())
