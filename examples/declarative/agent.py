import asyncio

import dspy
from dspy.utils import DummyLM


class RetrieveContext(dspy.Signature):
    question: str = dspy.InputField()
    context: str = dspy.OutputField()


class AnswerQuestion(dspy.Signature):
    question: str = dspy.InputField()
    context: str = dspy.InputField()
    answer: str = dspy.OutputField()


class QAPipeline(dspy.Module):
    def __init__(self) -> None:
        super().__init__()
        self.retrieve = dspy.Predict(RetrieveContext)
        self.answer = dspy.ChainOfThought(AnswerQuestion)

    def forward(self, question: str) -> dspy.Prediction:
        retrieval = self.retrieve(question=question)
        response = self.answer(question=question, context=retrieval.context)
        return dspy.Prediction(context=retrieval.context, answer=response.answer)


lm = DummyLM(
    [
        {"context": "Python is a high-level programming language created by Guido van Rossum"},
        {
            "reasoning": "The context describes Python as a high-level language",
            "answer": "Python is a high-level programming language created by Guido van Rossum",
        },
    ]
)
dspy.configure(lm=lm)

pipeline = QAPipeline()


async def run_pipeline(question: str) -> dspy.Prediction:
    return pipeline.forward(question)


async def main() -> None:
    print("Running uncompiled pipeline (compilation requires real LM calls)")
    prediction = await run_pipeline("What is Python?")
    print(f"  Context: {prediction.context}")
    print(f"  Answer: {prediction.answer}")


if __name__ == "__main__":
    asyncio.run(main())
