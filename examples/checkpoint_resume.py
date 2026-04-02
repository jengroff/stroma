"""Demonstrates checkpoint and resume after a mid-pipeline failure."""

import asyncio

from pydantic import BaseModel

from stroma import StromaRunner
from stroma.checkpoint import AsyncInMemoryStore, CheckpointManager
from stroma.contracts import ContractRegistry, NodeContract
from stroma.runner import RunConfig, stroma_node


class RawData(BaseModel):
    text: str


class Processed(BaseModel):
    words: list[str]


class Final(BaseModel):
    word_count: int


store = AsyncInMemoryStore()
manager = CheckpointManager(store)
registry = ContractRegistry()

registry.register(NodeContract(node_id="process", input_schema=RawData, output_schema=Processed))
registry.register(NodeContract(node_id="finalize", input_schema=Processed, output_schema=Final))

run_count = {"finalize": 0}


@stroma_node("process", NodeContract(node_id="process", input_schema=RawData, output_schema=Processed))
async def process(state: RawData) -> dict:
    print("  Running process node...")
    return {"words": state.text.split()}


@stroma_node("finalize", NodeContract(node_id="finalize", input_schema=Processed, output_schema=Final))
async def finalize_failing(state: Processed) -> dict:
    run_count["finalize"] += 1
    raise RuntimeError("Simulated crash in finalize")


@stroma_node("finalize", NodeContract(node_id="finalize", input_schema=Processed, output_schema=Final))
async def finalize_fixed(state: Processed) -> dict:
    run_count["finalize"] += 1
    print("  Running finalize node...")
    return {"word_count": len(state.words)}


async def main():
    # First run — process succeeds, finalize crashes
    print("Run 1: process succeeds, finalize crashes")
    config1 = RunConfig(run_id="demo-run")
    runner1 = StromaRunner(registry, manager, config1)
    result1 = await runner1.run([process, finalize_failing], RawData(text="hello world from stroma"))
    print(f"  Status: {result1.status}")
    print()

    # Resume from finalize — process is skipped, its checkpoint is loaded
    print("Run 2: resume from finalize (process is skipped)")
    config2 = RunConfig(run_id="demo-run", resume_from="finalize")
    runner2 = StromaRunner(registry, manager, config2)
    result2 = await runner2.run([process, finalize_fixed], RawData(text="hello world from stroma"))
    print(f"  Status: {result2.status}")
    print(f"  Result: {result2.final_state}")
    print(f"  Finalize ran {run_count['finalize']} times total (1 failed + 1 resumed)")


if __name__ == "__main__":
    asyncio.run(main())
