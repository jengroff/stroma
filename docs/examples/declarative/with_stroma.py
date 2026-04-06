import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))))

from pydantic import BaseModel

from docs.examples.declarative.agent import pipeline
from stroma.checkpoint import AsyncInMemoryStore, CheckpointManager
from stroma.contracts import ContractRegistry, NodeContract
from stroma.middleware import ReliabilityContext, execute_step
from stroma.runner import RunConfig


class RetrieveInput(BaseModel):
    question: str


class RetrieveOutput(BaseModel):
    context: str


class AnswerInput(BaseModel):
    question: str
    context: str


class AnswerOutput(BaseModel):
    answer: str


retrieve_contract = NodeContract(node_id="retrieve", input_schema=RetrieveInput, output_schema=RetrieveOutput)
answer_contract = NodeContract(node_id="answer", input_schema=AnswerInput, output_schema=AnswerOutput)


async def retrieve_fn(state: RetrieveInput) -> dict:
    pred = pipeline.retrieve(question=state.question)
    return {"context": pred.context}


async def answer_fn(state: AnswerInput) -> dict:
    pred = pipeline.answer(question=state.question, context=state.context)
    return {"answer": pred.answer}


async def broken_retrieve(state: RetrieveInput) -> dict:
    return {"wrong_field": "mutated by optimizer"}


async def main() -> None:
    registry = ContractRegistry()
    registry.register(retrieve_contract)
    registry.register(answer_contract)

    store = AsyncInMemoryStore()
    manager = CheckpointManager(store)
    config = RunConfig(run_id="dspy-qa-1")
    ctx = ReliabilityContext.for_run(config, registry, manager)

    question = "What is Python?"

    retrieve_result = await execute_step(
        "retrieve", retrieve_fn, RetrieveInput(question=question), ctx, contract=retrieve_contract
    )
    retrieve_output = retrieve_result.final_state
    print(f"  Context: {retrieve_output.context}")

    answer_result = await execute_step(
        "answer",
        answer_fn,
        AnswerInput(question=question, context=retrieve_output.context),
        ctx,
        contract=answer_contract,
    )
    print(f"  Answer: {answer_result.final_state.answer}")

    print("\nSuccessful trace:")
    for event in ctx.trace:
        print(f"  {event.node_id} (attempt {event.attempt}): status={'ok' if event.failure is None else event.failure}")

    registry2 = ContractRegistry()
    registry2.register(retrieve_contract)
    config2 = RunConfig(run_id="dspy-qa-broken")
    ctx2 = ReliabilityContext.for_run(config2, registry2, manager)

    broken_result = await execute_step(
        "retrieve", broken_retrieve, RetrieveInput(question=question), ctx2, contract=retrieve_contract
    )
    print(f"\nBroken pipeline status: {broken_result.status}")
    print(f"Failure: {ctx2.trace.failures()[0].failure_message}")


if __name__ == "__main__":
    asyncio.run(main())
