import json
import sqlite3
from decimal import Decimal
from pathlib import Path

import pytest
from pydantic import ValidationError
from typer.testing import CliRunner

from content_eval.cli import app
from content_eval.models import (
    Candidate,
    Evaluation,
    Event,
    Manifest,
    Policy,
    RateCard,
    Usage,
    digest,
)
from content_eval.projection import project
from content_eval.providers import FakeEvaluator, ProviderResult, generate
from content_eval.storage import Store
from content_eval.workflow import run


@pytest.fixture
def store(tmp_path: Path):  # type: ignore[no-untyped-def]
    with Store(tmp_path / "experiment.sqlite") as value:
        yield value


def test_decimal_accounting_and_reasoning_not_double_billed() -> None:
    rate = RateCard(
        id="test",
        uncached_input=Decimal("2"),
        cache_read=Decimal("0.2"),
        cache_write=Decimal("2.5"),
        output=Decimal("10"),
    )
    usage = Usage.from_inclusive_input(
        total=1000,
        cache_read=500,
        cache_write=100,
        output=100,
        reasoning=80,
    )
    assert usage.uncached_input == 400
    assert usage.input_total == 1000
    assert rate.cost(usage) == Decimal("0.00215")
    assert rate.cost(None) is None
    assert rate.cost(Usage(uncached_input=0, output=0)) == 0


@pytest.mark.parametrize(
    "fields",
    [
        {"uncached_input": -1, "output": 1},
        {"uncached_input": 1, "output": 1, "reasoning": 2},
    ],
)
def test_invalid_usage_rejected(fields: dict[str, int]) -> None:
    with pytest.raises(ValidationError):
        Usage.model_validate(fields)


def test_overlapping_input_counters_rejected() -> None:
    with pytest.raises(ValidationError):
        Usage.from_inclusive_input(total=100, cache_read=90, cache_write=50, output=1)


@pytest.mark.parametrize(
    ("evaluation", "expected"),
    [
        (Evaluation(checks={"answer_correct": 1, "rationale_consistent": 1}), "pass"),
        (Evaluation(checks={"answer_correct": 0, "rationale_consistent": 1}), "withhold"),
        (Evaluation(checks={"answer_correct": 1}), "unresolved"),
        (
            Evaluation(checks={"answer_correct": 1, "rationale_consistent": 1}, uncertain=True),
            "unresolved",
        ),
        (
            Evaluation(
                checks={"answer_correct": 1, "rationale_consistent": 1},
                critical_failures=("unsafe",),
            ),
            "withhold",
        ),
    ],
)
def test_policy_polarity_and_gates(evaluation: Evaluation, expected: str) -> None:
    assert Policy().decide(evaluation)[0] == expected


def test_both_arms_share_inputs_and_distinguish_exclusions(store: Store) -> None:
    run_id = run(store, Manifest(count=6, target=10))
    events = store.events(run_id)
    summary = project(events)
    assert (summary["generated"], summary["valid"], summary["invalid"]) == (6, 5, 1)
    for arm in ("llm", "jev"):
        stats = summary["arms"][arm]
        assert stats["attempts"] == 5
        assert stats["withheld"] == 1
        assert stats["quality_passes"] == 4
        assert len(stats["selected"]) == 3
        assert stats["duplicates"] == 1
        assert stats["target_gap"] == 7
        assert stats["cost_complete"]
    hashes = {
        arm: [
            e.payload["input_hash"]
            for e in events
            if e.event_type == "attempt.started" and e.arm == arm
        ]
        for arm in ("llm", "jev")
    }
    assert hashes["llm"] == hashes["jev"]
    assert summary["audited_quality"] is None
    assert summary["actual_billed_usd"] == "0"


def test_seeded_inputs_are_reproducible() -> None:
    assert generate(Manifest(seed=3)) == generate(Manifest(seed=3))
    assert generate(Manifest(seed=3)) != generate(Manifest(seed=4))


def test_provider_mutation_cannot_change_other_arm_or_selection(store: Store) -> None:
    class MutatingEvaluator(FakeEvaluator):
        def evaluate(self, candidate: Candidate, attempt: int) -> ProviderResult:
            result = super().evaluate(candidate, attempt)
            candidate.options["A"] = "corrupted by adapter"
            return result

    run_id = run(
        store,
        Manifest(count=1),
        evaluators={
            "llm": MutatingEvaluator("llm"),
            "jev": FakeEvaluator("jev"),
        },
    )
    events = store.events(run_id)
    report = project(events)
    assert report["arms"]["jev"]["quality_passes"] == 1
    selections = [e.payload["fingerprint"] for e in events if e.event_type == "selection.recorded"]
    assert selections[0] == selections[1]
    original = next(e.payload["candidate"] for e in events if e.event_type == "candidate.generated")
    assert original == generate(Manifest(count=1))[0]


def test_completed_resume_is_noop_and_manifest_cannot_change(store: Store) -> None:
    run_id = run(store, Manifest())
    before = store.events(run_id)
    assert run(store, run_id=run_id) == run_id
    assert store.events(run_id) == before
    with pytest.raises(ValueError, match="manifest differs"):
        run(store, Manifest(seed=99), run_id)


def test_retry_usage_and_unknown_cost_are_visible(store: Store) -> None:
    run_id = run(store, Manifest(count=1, failure_mode="transient"))
    stats = project(store.events(run_id))["arms"]["llm"]
    assert stats["attempts"] == 2
    assert stats["retries"] == 1
    assert stats["failures"] == 1
    assert stats["unknown_cost_attempts"] == 1
    assert stats["cost_per_selected_usd"] is None
    assert len(stats["selected"]) == 1


def test_provider_outage_never_passes(store: Store) -> None:
    run_id = run(store, Manifest(count=1, failure_mode="unavailable"))
    for stats in project(store.events(run_id))["arms"].values():
        assert stats["unresolved"] == 1
        assert stats["quality_passes"] == 0
        assert stats["selected"] == []
        assert stats["cost_per_selected_usd"] is None


class InterruptingEvaluator(FakeEvaluator):
    def evaluate(self, candidate: Candidate, attempt: int) -> ProviderResult:
        raise KeyboardInterrupt


def test_interrupt_and_recovery_never_invent_completion(store: Store) -> None:
    with pytest.raises(KeyboardInterrupt):
        run(
            store,
            Manifest(count=1),
            "interrupted",
            {
                "llm": InterruptingEvaluator("llm"),
                "jev": FakeEvaluator("jev"),
            },
        )
    before = project(store.events("interrupted"))
    assert before["status"] == "cancelled"
    assert len(before["outstanding_attempts"]) == 1
    run(store, run_id="interrupted")
    events = store.events("interrupted")
    after = project(events)
    assert after["status"] == "completed"
    assert after["outstanding_attempts"] == []
    assert after["arms"]["llm"]["attempts"] == 1
    assert after["arms"]["llm"]["unresolved"] == 1
    assert after["arms"]["llm"]["unknown_cost_attempts"] == 1
    assert after["arms"]["jev"]["selected"] == ["candidate-0000"]


def test_resume_after_success_does_not_call_provider_twice(
    store: Store,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original = store.append

    def fail_once(*args, **kwargs):  # type: ignore[no-untyped-def]
        if args[1] == "evaluation.completed":
            raise RuntimeError("simulated crash after durable success")
        return original(*args, **kwargs)

    monkeypatch.setattr(store, "append", fail_once)
    with pytest.raises(RuntimeError):
        run(store, Manifest(count=1), "crash")
    monkeypatch.setattr(store, "append", original)
    run(store, run_id="crash")
    events = store.events("crash")
    assert sum(e.event_type == "attempt.started" for e in events) == 2
    assert len(project(events)["arms"]["llm"]["selected"]) == 1


def test_store_immutable_and_invalid_append_rolls_back(store: Store) -> None:
    run_id = run(store, Manifest(count=1))
    count = len(store.events(run_id))
    with pytest.raises(sqlite3.IntegrityError, match="immutable"):
        store.db.execute("DELETE FROM events")
    store.db.rollback()
    with pytest.raises(ValidationError):
        store.append(run_id, "not.a.valid.event", {})  # type: ignore[arg-type]
    assert len(store.events(run_id)) == count
    store.append(run_id, "export.completed", {"kind": "test"})
    assert len(store.events(run_id)) == count + 1


def test_single_coordinator_lock(store: Store) -> None:
    with store.writer(), Store(store.path) as second:
        with pytest.raises(ValueError, match="another coordinator"), second.writer():
            pass


def test_replay_checks_hashes_and_sequence(store: Store) -> None:
    run_id = run(store, Manifest(count=1))
    events = store.events(run_id)
    replayed = [Event.model_validate_json(e.model_dump_json()) for e in events]
    assert project(events) == project(replayed)
    with pytest.raises(ValueError, match="sequence"):
        project([events[0], *events[2:]])
    bad = events[1].model_copy(update={"payload": {"tampered": True}})
    with pytest.raises(ValueError, match="hash"):
        project([events[0], bad, *events[2:]])
    unknown = events[0].model_dump(mode="json") | {"schema_version": 2}
    with pytest.raises(ValidationError):
        Event.model_validate(unknown)


def test_manifest_and_input_hashes_are_persisted(store: Store) -> None:
    manifest = Manifest(count=2)
    run_id = run(store, manifest)
    first = store.events(run_id)[0]
    assert first.payload["manifest_hash"] == digest(manifest.model_dump(mode="json"))
    assert first.payload["input_hashes"] == [digest(x) for x in generate(manifest)]


def test_cli_round_trip_and_unchanged_approval_export(tmp_path: Path) -> None:
    runner = CliRunner()
    db = str(tmp_path / "journal.sqlite")
    result = runner.invoke(app, ["demo", "--db", db, "--count", "6"])
    assert result.exit_code == 0, result.output
    report = json.loads(result.output)
    run_id = report["run_id"]
    journal = str(tmp_path / "events.jsonl")
    export = runner.invoke(app, ["export-events", run_id, journal, "--db", db])
    assert export.exit_code == 0, export.output
    replay = runner.invoke(app, ["replay", journal])
    assert replay.exit_code == 0, replay.output
    assert json.loads(replay.output) == report
    approval = str(tmp_path / "approval.json")
    result = runner.invoke(app, ["export-approval", run_id, approval, "--db", db])
    assert result.exit_code == 0, result.output
    packet = json.loads(Path(approval).read_text())
    assert packet["status"] == "demo_only_not_approved"
    original = {x["id"]: x for x in generate(Manifest(count=6))}
    assert all(original[x["id"]] == x for x in packet["candidates"])
    result = runner.invoke(app, ["export-approval", run_id, approval, "--db", db])
    assert result.exit_code != 0  # Do not silently overwrite artifacts.


def test_cli_dry_run_creates_no_database(tmp_path: Path) -> None:
    db = tmp_path / "absent.sqlite"
    result = CliRunner().invoke(app, ["demo", "--dry-run", "--db", str(db)])
    assert result.exit_code == 0, result.output
    assert not db.exists()
    assert json.loads(result.output)["mode"] == "fake-demo"


def test_resume_uses_frozen_inputs(store: Store, monkeypatch: pytest.MonkeyPatch) -> None:
    with pytest.raises(KeyboardInterrupt):
        run(
            store,
            Manifest(count=1),
            "frozen",
            {
                "llm": InterruptingEvaluator("llm"),
                "jev": FakeEvaluator("jev"),
            },
        )

    def unexpected_generation(*args: object) -> None:
        raise AssertionError("resume must not regenerate inputs")

    monkeypatch.setattr("content_eval.workflow.generate", unexpected_generation)
    run(store, run_id="frozen")
    assert project(store.events("frozen"))["status"] == "completed"


def test_run_listing_includes_recoverable_runs(store: Store) -> None:
    with pytest.raises(KeyboardInterrupt):
        run(
            store,
            Manifest(count=1),
            "recoverable",
            {
                "llm": InterruptingEvaluator("llm"),
                "jev": FakeEvaluator("jev"),
            },
        )
    result = CliRunner().invoke(app, ["runs", "--db", str(store.path)])
    assert result.exit_code == 0, result.output
    assert json.loads(result.output) == [{"run_id": "recoverable", "status": "cancelled"}]
