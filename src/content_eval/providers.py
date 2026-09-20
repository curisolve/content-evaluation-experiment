"""Offline fixtures, intentionally not quality or pricing benchmarks."""

import random
from typing import Protocol

from pydantic import JsonValue

from content_eval.models import Arm, Candidate, Evaluation, Frozen, Manifest, Usage


class ProviderResult(Frozen):
    model: str
    evaluation: Evaluation
    usage: Usage


class ProviderError(Exception):
    def __init__(self, category: str, transient: bool = False) -> None:
        super().__init__(category)
        self.category = category
        self.transient = transient


class Evaluator(Protocol):
    model: str

    def evaluate(self, candidate: Candidate, attempt: int) -> ProviderResult: ...


class FakeEvaluator:
    def __init__(self, arm: Arm, failure_mode: str = "none") -> None:
        self.model = f"fake-{arm}-v1"
        self.failure_mode = failure_mode

    def evaluate(self, candidate: Candidate, attempt: int) -> ProviderResult:
        if self.failure_mode == "unavailable":
            raise ProviderError("unavailable", transient=True)
        if self.failure_mode == "transient" and attempt == 1:
            raise ProviderError("timeout", transient=True)
        # This deterministic fixture checks only the toy arithmetic format.
        # It is NOT an implementation of JEV or an LLM judge.
        words = candidate.stem.split()
        expected = int(words[2]) + int(words[4].rstrip("?"))
        correct = candidate.options[candidate.answer_key] == str(expected)
        consistent = candidate.rationale == f"The sum is {expected}."
        return ProviderResult(
            model=self.model,
            evaluation=Evaluation(
                checks={
                    "answer_correct": float(correct),
                    "rationale_consistent": float(consistent),
                }
            ),
            usage=Usage(
                uncached_input=len(candidate.model_dump_json().encode()) // 4 + 1,
                output=24,
                reasoning=0,
                raw={"method": "synthetic byte-length estimate; not a provider tokenizer"},
            ),
        )


def generate(manifest: Manifest) -> list[dict[str, JsonValue]]:
    rng = random.Random(manifest.seed)
    result: list[dict[str, JsonValue]] = []
    for index in range(manifest.count):
        if index % 6 == 5:
            raw = dict(result[index - 1])
            raw["id"] = f"candidate-{index:04d}"
        else:
            a, b = rng.randrange(1, 50), rng.randrange(1, 50)
            answer = a + b
            item = Candidate(
                id=f"candidate-{index:04d}",
                family_id=f"family-{index:04d}",
                topic="addition",
                stem=f"What is {a} + {b}?",
                options={
                    "A": str(answer),
                    "B": str(answer + 1),
                    "C": str(answer + 2),
                    "D": str(answer + 3),
                },
                answer_key="B" if index % 6 == 1 else "A",
                rationale=f"The sum is {answer}.",
            )
            raw = item.model_dump(mode="json")
            if index % 6 == 2:
                raw["options"] = {"A": str(answer)}
        result.append(raw)
    return result
