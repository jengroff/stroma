"""Demonstrates retry behavior for transient vs terminal failures."""

import asyncio

from pydantic import BaseModel

from stroma import FailureClass, FailurePolicy, StromaRunner


class Input(BaseModel):
    value: int


class Output(BaseModel):
    result: int


attempt_count = 0

runner = StromaRunner.quick(
    policy_map={
        FailureClass.RECOVERABLE: FailurePolicy(max_retries=3, backoff_seconds=0.1),
        FailureClass.TERMINAL: FailurePolicy(max_retries=0),
        FailureClass.AMBIGUOUS: FailurePolicy(max_retries=1, backoff_seconds=0.1),
    }
)


@runner.node("flaky_node", input=Input, output=Output)
async def flaky_node(state: Input) -> dict:
    global attempt_count
    attempt_count += 1
    if attempt_count < 3:
        raise TimeoutError(f"Attempt {attempt_count}: API timed out")
    return {"result": state.value * 2}


async def main():
    global attempt_count

    # Transient failure — retries and succeeds on attempt 3
    attempt_count = 0
    result = await runner.run([flaky_node], Input(value=5))
    print(f"Transient failure demo:")
    print(f"  Status: {result.status}")
    print(f"  Attempts: {attempt_count}")
    print(f"  Result: {result.final_state}")
    print()

    # Inspect the trace to see each attempt
    for event in result.trace:
        status = f"FAILED ({event.failure})" if event.failure else "OK"
        print(f"  attempt={event.attempt} {status}")


if __name__ == "__main__":
    asyncio.run(main())
