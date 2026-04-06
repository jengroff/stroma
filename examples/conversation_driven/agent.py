import asyncio
from typing import Literal

from pydantic import BaseModel


class CodeSubmission(BaseModel):
    filename: str
    code: str
    language: str


class ReviewMessage(BaseModel):
    turn: int
    issues: list[str]
    severity: Literal["low", "medium", "high"]
    summary: str


class RevisionPlan(BaseModel):
    turn: int
    changes: list[str]
    rationale: str


class MessageBus:
    def __init__(self) -> None:
        self._messages: list[ReviewMessage | RevisionPlan] = []

    async def post(self, msg: ReviewMessage | RevisionPlan) -> None:
        self._messages.append(msg)

    @property
    def messages(self) -> list[ReviewMessage | RevisionPlan]:
        return self._messages

    def latest(self, type_: type) -> ReviewMessage | RevisionPlan | None:
        for msg in reversed(self._messages):
            if isinstance(msg, type_):
                return msg
        return None


async def reviewer_agent(submission: CodeSubmission, bus: MessageBus, turn: int) -> ReviewMessage:
    if turn == 1:
        return ReviewMessage(
            turn=1,
            issues=["no type annotations", "missing error handling"],
            severity="medium",
            summary="Needs type safety and error handling",
        )
    return ReviewMessage(
        turn=2,
        issues=["error handling too broad"],
        severity="low",
        summary="Nearly ready, tighten exception scope",
    )


async def responder_agent(bus: MessageBus, turn: int) -> RevisionPlan:
    if turn == 1:
        return RevisionPlan(
            turn=1,
            changes=["add type annotations to all functions", "wrap IO in try/except"],
            rationale="Addressing severity:medium issues first",
        )
    return RevisionPlan(
        turn=2,
        changes=["narrow except clause to OSError, ValueError"],
        rationale="Tightened as requested",
    )


async def run_conversation(submission: CodeSubmission) -> MessageBus:
    bus = MessageBus()
    for turn in [1, 2]:
        review = await reviewer_agent(submission, bus, turn)
        await bus.post(review)
        revision = await responder_agent(bus, turn)
        await bus.post(revision)
    return bus


async def main() -> None:
    submission = CodeSubmission(
        filename="app.py",
        code="def load(path):\n  return open(path).read()",
        language="python",
    )
    bus = await run_conversation(submission)
    for msg in bus.messages:
        if isinstance(msg, ReviewMessage):
            print(f"  Review (turn {msg.turn}): {msg.summary}")
        else:
            print(f"  Revision (turn {msg.turn}): {msg.changes}")


if __name__ == "__main__":
    asyncio.run(main())
