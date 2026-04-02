"""Minimal two-node pipeline with contract validation."""

import asyncio

from pydantic import BaseModel

from stroma import StromaRunner


class Input(BaseModel):
    text: str


class WordCount(BaseModel):
    text: str
    count: int


class Result(BaseModel):
    text: str
    count: int
    is_long: bool


runner = StromaRunner.quick()


@runner.node("count_words", input=Input, output=WordCount)
async def count_words(state: Input) -> dict:
    words = state.text.split()
    return {"text": state.text, "count": len(words)}


@runner.node("classify", input=WordCount, output=Result)
async def classify(state: WordCount) -> dict:
    return {"text": state.text, "count": state.count, "is_long": state.count > 10}


async def main():
    result = await runner.run(
        [count_words, classify],
        Input(text="Stroma adds contracts retries checkpoints and traceability to async agent pipelines"),
    )
    print(f"Status: {result.status}")
    print(f"Output: {result.final_state}")
    print(f"Trace events: {len(result.trace)}")


if __name__ == "__main__":
    asyncio.run(main())
