"""Demonstrates adding Stroma contract validation to a LangGraph graph.

Requires: uv add stroma[langgraph]
"""

import asyncio

from pydantic import BaseModel

from stroma import ContractRegistry, NodeContract

try:
    from stroma.adapters.langgraph import LangGraphAdapter
except ImportError:
    print("This example requires the langgraph extra: uv add stroma[langgraph]")
    raise SystemExit(1)


class Query(BaseModel):
    text: str


class SearchResult(BaseModel):
    urls: list[str]


registry = ContractRegistry()
registry.register(NodeContract(node_id="search", input_schema=Query, output_schema=SearchResult))


async def main():
    adapter = LangGraphAdapter(registry)

    # In a real application you would pass your LangGraph StateGraph to:
    #   adapter.wrap(graph)
    # This validates every node's input/output against its contract.
    #
    # See the tutorial for a full walkthrough:
    #   https://jengroff.github.io/stroma/tutorial/langgraph/

    print("LangGraphAdapter is ready.")
    print(f"Registered contracts: {list(registry._contracts.keys())}")
    print()
    print("To use with a real graph:")
    print("  graph = StateGraph(YourState)")
    print("  graph.add_node('search', search_fn)")
    print("  adapter.wrap(graph)  # adds contract validation to all nodes")
    print("  app = graph.compile()")
    print("  result = await app.ainvoke({'text': 'hello'})")


if __name__ == "__main__":
    asyncio.run(main())
