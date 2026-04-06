import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))))

from docs.examples.conversation_driven.agent import (
    CodeSubmission,
    MessageBus,
    ReviewMessage,
    RevisionPlan,
    responder_agent,
    reviewer_agent,
)
from stroma.checkpoint import AsyncInMemoryStore, CheckpointManager
from stroma.contracts import ContractRegistry
from stroma.middleware import ReliabilityContext, StromaStep
from stroma.runner import RunConfig


async def main() -> None:
    registry = ContractRegistry()
    store = AsyncInMemoryStore()
    manager = CheckpointManager(store)
    config = RunConfig(run_id="code-review-1")
    ctx = ReliabilityContext.for_run(config, registry, manager)

    step = StromaStep(ctx)
    bus = MessageBus()

    submission = CodeSubmission(
        filename="app.py",
        code="def load(path):\n  return open(path).read()",
        language="python",
    )

    @step("reviewer_turn1", input=CodeSubmission, output=ReviewMessage)
    async def reviewer_turn1(sub: CodeSubmission) -> dict:
        msg = await reviewer_agent(sub, bus, 1)
        return msg.model_dump()

    @step("responder_turn1", input=ReviewMessage, output=RevisionPlan)
    async def responder_turn1(review: ReviewMessage) -> dict:
        plan = await responder_agent(bus, 1)
        return plan.model_dump()

    result = await reviewer_turn1(submission)
    review1 = result.final_state
    await bus.post(review1)
    print(f"  Review (turn 1): {review1.summary}")

    result = await responder_turn1(review1)
    revision1 = result.final_state
    await bus.post(revision1)
    print(f"  Revision (turn 1): {revision1.changes}")

    @step("reviewer_turn2_broken", input=CodeSubmission, output=ReviewMessage)
    async def reviewer_turn2_broken(sub: CodeSubmission) -> dict:
        return {"turn": 2, "issues": ["error handling too broad"], "summary": "Nearly ready"}

    caught_violation = None
    result = await reviewer_turn2_broken(submission)
    if result.status.value == "FAILED":
        failure_event = ctx.trace.failures()[-1]
        caught_violation = failure_event
        print(f"  ContractViolation caught: {failure_event.node_id} — {failure_event.failure_message}")

    @step("reviewer_turn2", input=CodeSubmission, output=ReviewMessage)
    async def reviewer_turn2(sub: CodeSubmission) -> dict:
        msg = await reviewer_agent(sub, bus, 2)
        return msg.model_dump()

    @step("responder_turn2", input=ReviewMessage, output=RevisionPlan)
    async def responder_turn2(review: ReviewMessage) -> dict:
        plan = await responder_agent(bus, 2)
        return plan.model_dump()

    result = await reviewer_turn2(submission)
    review2 = result.final_state
    await bus.post(review2)
    print(f"  Review (turn 2): {review2.summary}")

    result = await responder_turn2(review2)
    revision2 = result.final_state
    await bus.post(revision2)
    print(f"  Revision (turn 2): {revision2.changes}")

    print("\nTurns completed: 2")
    if caught_violation:
        print(f"ContractViolation caught: {caught_violation.node_id} — {caught_violation.failure_message}")
    print(f"Final revision plan: {revision2.changes}")


if __name__ == "__main__":
    asyncio.run(main())
