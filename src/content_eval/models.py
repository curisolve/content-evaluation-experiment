"""Provider-independent contracts and deterministic serialization."""

import hashlib
import json
from decimal import Decimal
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, JsonValue, model_validator

Arm = Literal["llm", "jev"]
ARMS: tuple[Arm, ...] = ("llm", "jev")


def canonical(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def digest(value: object) -> str:
    return hashlib.sha256(canonical(value).encode()).hexdigest()


class Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class Candidate(Frozen):
    id: str
    family_id: str
    subject_version: str = "demo-arithmetic-v1"
    cohort: Literal["ordinary", "challenge"] = "ordinary"
    topic: str
    audience: str = "demo"
    difficulty: str = "foundational"
    stem: str = Field(min_length=1)
    options: dict[str, str]
    answer_key: Literal["A", "B", "C", "D"]
    rationale: str = Field(min_length=1)
    source_references: tuple[str, ...] = ("demo-arithmetic-v1",)

    @model_validator(mode="after")
    def check_options(self) -> Self:
        if set(self.options) != {"A", "B", "C", "D"}:
            raise ValueError("exactly four option IDs A-D required")
        values = [value.strip().casefold() for value in self.options.values()]
        if not all(values) or len(set(values)) != 4:
            raise ValueError("options must be nonempty and distinct")
        if not self.stem.strip() or not self.rationale.strip() or not self.source_references:
            raise ValueError("nonempty stem, rationale and source references required")
        return self

    def fingerprint(self) -> str:
        # This is exact text deduplication, not semantic equivalence.
        return digest(
            [
                " ".join(self.stem.casefold().split()),
                sorted(" ".join(v.casefold().split()) for v in self.options.values()),
            ]
        )


class Usage(Frozen):
    """Disjoint input billing buckets; reasoning is a subset of output."""

    uncached_input: int = Field(ge=0)
    cache_read: int = Field(default=0, ge=0)
    cache_write: int = Field(default=0, ge=0)
    output: int = Field(ge=0)
    reasoning: int | None = Field(default=None, ge=0)
    provenance: Literal["provider_reported", "estimated"] = "estimated"
    raw: dict[str, JsonValue] = Field(default_factory=dict)
    cache_write_1h: int = Field(default=0, ge=0)

    @model_validator(mode="after")
    def check_reasoning(self) -> Self:
        if self.reasoning is not None and self.reasoning > self.output:
            raise ValueError("reasoning is a subset of output")
        return self

    @classmethod
    def from_inclusive_input(
        cls,
        *,
        total: int,
        cache_read: int,
        cache_write: int,
        output: int,
        reasoning: int | None = None,
    ) -> Self:
        return cls(
            uncached_input=total - cache_read - cache_write,
            cache_read=cache_read,
            cache_write=cache_write,
            output=output,
            reasoning=reasoning,
        )

    @property
    def input_total(self) -> int:
        return self.uncached_input + self.cache_read + self.cache_write + self.cache_write_1h


class RateCard(Frozen):
    id: str
    currency: Literal["USD"] = "USD"
    provenance: Literal["synthetic_fixture", "published_snapshot"] = "synthetic_fixture"
    source_url: str | None = None
    retrieved_on: str | None = None
    model: str | None = None
    cache_write_1h: Decimal = Field(default=Decimal(0), ge=0)
    uncached_input: Decimal = Field(ge=0)
    cache_read: Decimal = Field(ge=0)
    cache_write: Decimal = Field(ge=0)
    output: Decimal = Field(ge=0)

    def cost(self, usage: Usage | None) -> Decimal | None:
        if usage is None:
            return None
        return sum(
            (
                self.uncached_input * usage.uncached_input,
                self.cache_read * usage.cache_read,
                self.cache_write * usage.cache_write,
                self.cache_write_1h * usage.cache_write_1h,
                self.output * usage.output,
            ),
            Decimal(0),
        ) / Decimal(1_000_000)


class Evaluation(Frozen):
    checks: dict[str, float]
    uncertain: bool = False
    critical_failures: tuple[str, ...] = ()

    @model_validator(mode="after")
    def check_scores(self) -> Self:
        if not self.checks or any(not 0 <= x <= 1 for x in self.checks.values()):
            raise ValueError("nonempty checks with higher-is-better scores in [0,1] required")
        return self


class Policy(Frozen):
    version: str = "demo-policy-v1"
    threshold: float = Field(default=0.9, gt=0, le=1)
    required_checks: tuple[str, ...] = ("answer_correct", "rationale_consistent")

    def decide(self, evaluation: Evaluation) -> tuple[str, str]:
        if set(evaluation.checks) != set(self.required_checks):
            return "unresolved", "rubric_mismatch"
        if evaluation.critical_failures:
            return "withhold", "critical_failure"
        if evaluation.uncertain:
            return "unresolved", "uncertain"
        if any(value < self.threshold for value in evaluation.checks.values()):
            return "withhold", "below_threshold"
        return "pass", "quality_gates_passed"


class Manifest(Frozen):
    version: Literal[1] = 1
    mode: Literal["fake-demo", "live-smoke", "cmto-development"] = "fake-demo"
    provider_config: dict[str, JsonValue] = Field(default_factory=dict)
    seed: int = 7
    count: int = Field(default=12, ge=1, le=1000)
    target: int = Field(default=5, ge=1, le=1000)
    max_attempts: int = Field(default=2, ge=1, le=5)
    failure_mode: Literal["none", "transient", "unavailable"] = "none"
    generator_version: Literal["demo-generator-v1", "cmto-generator-v1"] = "demo-generator-v1"
    selector_version: Literal["exact-text-v1"] = "exact-text-v1"
    source_text: str = "Demo only: addition of nonnegative integers; no CMTO authority."
    policy: Policy = Field(default_factory=Policy)
    rates: dict[Arm, RateCard] = Field(
        default_factory=lambda: {
            arm: RateCard(
                id=f"synthetic-{arm}-v1",
                uncached_input=Decimal("1"),
                cache_read=Decimal("0.1"),
                cache_write=Decimal("1.25"),
                output=Decimal("2"),
            )
            for arm in ARMS
        }
    )

    @model_validator(mode="after")
    def check_rates(self) -> Self:
        if set(self.rates) != set(ARMS):
            raise ValueError("both arms need frozen rate cards")
        if self.mode == "cmto-development":
            if self.count != 20 or self.max_attempts != 1:
                raise ValueError("CMTO development requires 20 items and one attempt per arm")
            if self.generator_version != "cmto-generator-v1" or not self.provider_config:
                raise ValueError("CMTO configuration required")
        if self.mode == "live-smoke":
            if self.count > 5 or self.max_attempts != 1:
                raise ValueError(
                    "live smoke runs permit at most five inputs and one attempt per arm"
                )
            if not self.provider_config or any(
                card.provenance != "published_snapshot" for card in self.rates.values()
            ):
                raise ValueError("live smoke runs require explicit providers and published rates")
        return self


EventType = Literal[
    "run.created",
    "run.resumed",
    "run.completed",
    "run.stopped",
    "run.cancelled",
    "run.failed",
    "candidate.generated",
    "candidate.validated",
    "candidate.invalid",
    "attempt.started",
    "attempt.succeeded",
    "attempt.failed",
    "attempt.recovery_unknown",
    "retry.scheduled",
    "evaluation.completed",
    "decision.recorded",
    "selection.recorded",
    "export.completed",
    "generation.started",
    "generation.succeeded",
    "generation.failed",
    "candidate.constructed",
    "candidate.prepared",
    "pool.frozen",
    "budget.checked",
]


class Event(Frozen):
    schema_version: Literal[1] = 1
    event_id: str
    run_id: str
    sequence: int = Field(ge=1)
    event_type: EventType
    occurred_at: str
    persisted_at: str
    session_id: str
    elapsed_ns: int = Field(ge=0)
    arm: Arm | None = None
    candidate_id: str | None = None
    operation_id: str | None = None
    attempt_id: str | None = None
    payload: dict[str, JsonValue]
    previous_hash: str
    event_hash: str

    def verify(self) -> None:
        if digest(self.model_dump(mode="json", exclude={"event_hash"})) != self.event_hash:
            raise ValueError("event hash mismatch")
