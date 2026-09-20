import json
from decimal import Decimal
from pathlib import Path
from typing import Any

import httpx
import pytest
from typer.testing import CliRunner

from content_eval.cli import app
from content_eval.cmto import execute, make_manifest, slots
from content_eval.live import LiveConfig
from content_eval.models import Event, digest
from content_eval.projection import project
from content_eval.sources import extract, load_pack
from content_eval.storage import Store

ROOT = Path(__file__).resolve().parents[1]


def fixture_pack() -> dict[str, Any]:
    subject = json.loads((ROOT / "subjects/cmto_consent_boundaries_v1.json").read_text())
    rubric = json.loads((ROOT / "rubrics/cmto_consent_boundaries_v1.json").read_text())
    pack = {
        "subject": subject,
        "rubric": rubric,
        "capture": {"effective_date": "2026-09-08"},
        "articles": {"fixture": {"context": "Synthetic test authority, not real guidance."}},
        "allowed_locators": ["cmto_consent:requirements.1", "cmto_boundaries:requirements.9"],
    }
    return {**pack, "pack_hash": digest(pack)}


def manifest(llm_provider: str = "anthropic", **kwargs: Any) -> Any:
    return make_manifest(
        fixture_pack(),
        LiveConfig.model_validate(
            {
                "provider": llm_provider,
                "model": "claude-opus-5" if llm_provider == "anthropic" else "gpt-5.6-sol",
            }
        ),
        Decimal("100"),
        generator=LiveConfig.model_validate(
            {
                "provider": "openai" if llm_provider == "anthropic" else "anthropic",
                "model": "gpt-5.6-sol" if llm_provider == "anthropic" else "claude-opus-5",
            }
        ),
        **kwargs,
    )


def response(model: str, value: Any, *, usage: bool = True) -> dict[str, Any]:
    if model.startswith("gpt-"):
        result = {
            "model": model,
            "status": "completed",
            "service_tier": "default",
            "output": [
                {
                    "type": "message",
                    "content": [
                        {
                            "type": "output_text",
                            "text": json.dumps(value),
                        }
                    ],
                }
            ],
        }
        if usage:
            result["usage"] = {
                "input_tokens": 100,
                "output_tokens": 50,
                "input_tokens_details": {"cached_tokens": 0, "cache_write_tokens": 0},
                "output_tokens_details": {"reasoning_tokens": 0},
            }
        return result
    result = {
        "model": model,
        "stop_reason": "end_turn",
        "content": [{"type": "text", "text": json.dumps(value)}],
    }
    if usage:
        result["usage"] = {
            "input_tokens": 100,
            "output_tokens": 50,
            "cache_read_input_tokens": 0,
            "cache_creation_input_tokens": 0,
        }
    return result


def transport(
    calls: list[dict[str, Any]],
    *,
    bad_generation: bool = False,
    missing_usage: bool = False,
) -> httpx.MockTransport:
    def handle(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        calls.append(body)
        if "state" in body:
            return httpx.Response(
                200,
                json={
                    "model": body["model"],
                    "answers": {key: {"type": "noul", "noul": 0.99} for key in body["questions"]},
                    "usage": {"input_tokens": 100, "output_tokens": 40},
                },
            )
        content = json.loads(body["input"] if "input" in body else body["messages"][0]["content"])
        if "assignment" in content:
            slot = content["assignment"]
            value = {
                "stem": f"Synthetic question {slot['id']}?",
                "options": {"A": "one", "B": "two", "C": "three", "D": "four"},
                "answer_key": "A",
                "rationale": "Synthetic fixture rationale.",
                "source_references": [
                    f"cmto_{slot['topic']}:requirements."
                    + ("1" if slot["topic"] == "consent" else "9")
                ],
            }
            if bad_generation:
                value["source_references"] = ["unknown:requirements.999"]
            return httpx.Response(
                200,
                json=response(
                    body["model"],
                    value,
                    usage=not missing_usage,
                ),
            )
        assert not {"id", "family_id", "cohort"} & set(content["state"]["candidate"])
        return httpx.Response(
            200,
            json=response(
                body["model"],
                {key: "pass" for key in content["checks"]},
            ),
        )

    return httpx.MockTransport(handle)


@pytest.fixture(autouse=True)
def keys(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "offline-test-key")
    monkeypatch.setenv("TYPESAFE_API_KEY", "offline-test-key")
    monkeypatch.setenv("OPENAI_API_KEY", "offline-test-key")
    monkeypatch.setenv("OPENAI_MODEL", "gpt-5.6-sol")


def test_allocation() -> None:
    allocation = slots()
    assert len(allocation) == 20
    for field, expected in (
        ("topic", {"consent": 10, "boundaries": 10}),
        ("audience", {"rmt_student": 10, "practising_rmt": 10}),
        ("difficulty", {"foundational": 10, "applied": 10}),
        ("kind", {"ordinary": 12, "defect": 4, "paraphrase": 4}),
    ):
        assert {value: sum(s[field] == value for s in allocation) for value in expected} == expected


def test_extraction_preserves_nested_and_governing_context() -> None:
    html = (
        '<div class="left-col"><h3>Patient Outcome</h3><p>Overview.</p>'
        "<h3>Requirements</h3><p>Always:</p><ol>"
        '<li>First<ol type="a"><li>Nested one.</li><li>Nested two.</li></ol></li>'
        + "".join(f"<li>Item {n}</li>" for n in range(2, 9))
        + '</ol><p>Only while clothed:</p><ol start="9"><li>Ninth.</li></ol></div>'
    )
    result = extract(html.encode(), "cmto_consent")
    assert len(result["requirements"]) == 9
    assert "Nested two." in result["requirements"]["cmto_consent:requirements.1"]
    assert result["requirements"]["cmto_consent:requirements.9"] == "Only while clothed: Ninth."
    assert "Overview." in result["context"]
    with pytest.raises(ValueError, match="numbering"):
        extract(html.replace('start="9"', 'start="8"').encode(), "cmto_consent")


def test_source_integrity_rejected(tmp_path: Path) -> None:
    subject = json.loads((ROOT / "subjects/cmto_consent_boundaries_v1.json").read_text())
    subject["source_pack"] = "capture.json"
    subject["rubric"] = str(ROOT / "rubrics/cmto_consent_boundaries_v1.json")
    (tmp_path / "subject.json").write_text(json.dumps(subject))
    capture = json.loads(
        (ROOT / "subjects/sources/cmto_consent_boundaries.capture.json").read_text()
    )
    (tmp_path / "capture.json").write_text(json.dumps(capture))
    (tmp_path / capture["sources"][0]["raw_path"]).write_text("tampered")
    with pytest.raises(ValueError, match="hash mismatch"):
        load_pack(tmp_path / "subject.json", tmp_path)


@pytest.mark.parametrize("llm_provider", ["anthropic", "openai"])
def test_complete_mock_run_and_replay(tmp_path: Path, llm_provider: str) -> None:
    calls: list[dict[str, Any]] = []
    with httpx.Client(transport=transport(calls)) as client, Store(tmp_path / "run.db") as store:
        mid = execute(store, manifest(llm_provider), client)
        events = store.events(mid)
        report = project(events)
        assert len(calls) == 56
        assert report["frozen_pool_size"] == report["valid"] == 20
        assert report["prepared_candidates"] == 20
        assert report["generation"]["attempts"] == 16
        assert report["generation"]["input_tokens"] == 1600
        assert report["experiment_cost_complete"]
        assert report["stop_reason"] == "fixed_pool_exhausted"
        assert report["outstanding_attempts"] == []
        assert all(v["attempts"] == 20 for v in report["arms"].values())
        for stats in report["arms"].values():
            assert stats["populations"]["ordinary"]["attempts"] == 12
            assert stats["populations"]["defect"]["attempts"] == 4
            assert stats["populations"]["paraphrase"]["attempts"] == 4
        assert project([Event.model_validate_json(e.model_dump_json()) for e in events]) == report
        frozen = next(e.payload for e in events if e.event_type == "pool.frozen")
        assert len(set(frozen["input_hashes"])) == 20
        assert len([e for e in events if e.event_type == "candidate.constructed"]) == 4
        evaluation_calls = [body for body in calls if "state" in body]
        assert len(evaluation_calls) == 20
        for body in evaluation_calls:
            assert set(body["state"]["candidate"]).isdisjoint({"cohort", "family_id", "id"})
            assert len(body["questions"]) == 10
        result = CliRunner().invoke(
            app,
            [
                "export-approval",
                mid,
                str(tmp_path / "queue.json"),
                "--db",
                str(tmp_path / "run.db"),
            ],
        )
        assert result.exit_code != 0
        assert not (tmp_path / "queue.json").exists()


@pytest.mark.parametrize(
    ("options", "reason", "calls_expected"),
    [
        ({"max_calls": 1}, "call_cap", 1),
        ({"max_calls": 16}, "call_cap", 16),
    ],
)
def test_call_cap(
    tmp_path: Path, options: dict[str, Any], reason: str, calls_expected: int
) -> None:
    calls: list[dict[str, Any]] = []
    with httpx.Client(transport=transport(calls)) as client, Store(tmp_path / "run.db") as store:
        mid = execute(store, manifest(**options), client)
        report = project(store.events(mid))
        assert len(calls) == calls_expected
        assert report["stop_reason"] == reason
        assert not report["outstanding_attempts"]


def test_spend_guard_prevents_first_call(tmp_path: Path) -> None:
    calls: list[dict[str, Any]] = []
    m = make_manifest(
        fixture_pack(),
        LiveConfig(provider="anthropic", model="claude-opus-5"),
        Decimal("0.000001"),
        generator=LiveConfig(provider="openai", model="gpt-5.6-sol"),
    )
    with httpx.Client(transport=transport(calls)) as client, Store(tmp_path / "run.db") as store:
        mid = execute(store, m, client)
        assert not calls
        assert project(store.events(mid))["stop_reason"] == "estimated_spend_guard"


@pytest.mark.parametrize("failure", ["invalid", "unknown_usage"])
def test_generation_fail_closed(tmp_path: Path, failure: str) -> None:
    calls: list[dict[str, Any]] = []
    mock = transport(
        calls, bad_generation=failure == "invalid", missing_usage=failure == "unknown_usage"
    )
    with httpx.Client(transport=mock) as client, Store(tmp_path / "run.db") as store:
        mid = execute(store, manifest(), client)
        report = project(store.events(mid))
        assert len(calls) == 1
        assert report["frozen_pool_size"] == 0
        assert report["generation"]["attempts"] == 1
        assert report["generation"]["unknown_cost_attempts"] == (failure == "unknown_usage")
        assert all(v["attempts"] == 0 for v in report["arms"].values())


def test_preview_no_network_or_database(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr("content_eval.cli.load_pack", lambda *args: fixture_pack())
    monkeypatch.delenv("ANTHROPIC_API_KEY")
    monkeypatch.delenv("TYPESAFE_API_KEY")
    db = tmp_path / "no.db"
    result = CliRunner().invoke(app, ["cmto-run", "--max-estimated-usd", "5", "--db", str(db)])
    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["network_calls"] == 0
    assert not db.exists()
    result = CliRunner().invoke(
        app,
        [
            "cmto-run",
            "--max-estimated-usd",
            "5",
            "--db",
            str(db),
            "--execute",
            "--reviewed-pack-hash",
            "wrong",
        ],
    )
    assert result.exit_code != 0
    assert not db.exists()


def test_missing_second_credential_prevents_generation(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.delenv("TYPESAFE_API_KEY")
    calls: list[dict[str, Any]] = []
    with httpx.Client(transport=transport(calls)) as client, Store(tmp_path / "run.db") as store:
        with pytest.raises(ValueError, match="TYPESAFE_API_KEY"):
            execute(store, manifest(), client)
        assert not calls
        assert store.db.execute("SELECT COUNT(*) FROM events").fetchone()[0] == 0


@pytest.mark.parametrize("interrupt_at", [1, 17])
def test_interrupted_calls_are_visible_and_not_resumed(
    tmp_path: Path,
    interrupt_at: int,
) -> None:
    from content_eval.workflow import run

    calls: list[dict[str, Any]] = []
    normal = transport(calls)
    seen = 0

    def handle(request: httpx.Request) -> httpx.Response:
        nonlocal seen
        seen += 1
        if seen == interrupt_at:
            raise KeyboardInterrupt
        return normal.handle_request(request)

    with httpx.Client(transport=httpx.MockTransport(handle)) as client:
        with Store(tmp_path / "run.db") as store:
            with pytest.raises(KeyboardInterrupt):
                execute(store, manifest(), client)
            mid = store.db.execute("SELECT run_id FROM events LIMIT 1").fetchone()[0]
            events = store.events(mid)
            report = project(events)
            assert report["status"] == "cancelled"
            assert len(report["outstanding_attempts"]) == 1
            assert not report["experiment_cost_complete"]
            with pytest.raises(ValueError, match="resume"):
                run(store, run_id=mid)
            assert len(store.events(mid)) == len(events)
            assert seen == interrupt_at


def test_timeout_is_logged_without_retry(tmp_path: Path) -> None:
    calls = 0

    def handle(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        raise httpx.ReadTimeout("private transport detail", request=request)

    with httpx.Client(transport=httpx.MockTransport(handle)) as client:
        with Store(tmp_path / "run.db") as store:
            mid = execute(store, manifest(), client)
            report = project(store.events(mid))
            assert calls == 1
            assert report["generation"]["failures"] == 1
            assert report["stop_reason"] == "generation_failed_no_retry"
            assert not report["experiment_cost_complete"]
            assert "private transport detail" not in "".join(
                e.model_dump_json() for e in store.events(mid)
            )


def test_pack_and_manifest_changes_rejected_before_calls(tmp_path: Path) -> None:
    pack = fixture_pack()
    pack["articles"]["fixture"]["context"] = "changed"
    with pytest.raises(ValueError, match="pack hash"):
        make_manifest(pack, LiveConfig(provider="anthropic", model="claude-opus-5"), Decimal(5))
    m = manifest().model_copy(update={"source_text": "changed"})
    calls: list[dict[str, Any]] = []
    with httpx.Client(transport=transport(calls)) as client, Store(tmp_path / "run.db") as store:
        with pytest.raises(ValueError, match="manifest differs"):
            execute(store, m, client)
        assert not calls


def test_wrong_dynamic_verdict_keys_retain_billed_usage() -> None:
    from content_eval.live import LiveEvaluator
    from content_eval.models import Candidate
    from content_eval.providers import ProviderError

    with httpx.Client(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(200, json=response("claude-opus-5", {"wrong": "pass"}))
        )
    ) as client:
        evaluator = LiveEvaluator(
            LiveConfig(provider="anthropic", model="claude-opus-5"),
            client,
            questions={"custom_check": "Is this supported?"},
            source="fixture",
        )
        candidate = Candidate(
            id="x",
            family_id="x",
            topic="fixture",
            stem="Fixture?",
            options={"A": "a", "B": "b", "C": "c", "D": "d"},
            answer_key="A",
            rationale="Fixture.",
        )
        with pytest.raises(ProviderError) as caught:
            evaluator.evaluate(candidate, 1)
        assert caught.value.category == "invalid_evaluation"
        assert caught.value.usage is not None
        assert caught.value.usage.output == 50
        assert caught.value.pricing_applicable


def stopped_parent(store: Store) -> str:
    seen = 0
    calls: list[dict[str, Any]] = []
    normal = transport(calls)

    def handle(request: httpx.Request) -> httpx.Response:
        nonlocal seen
        seen += 1
        if seen == 3:
            raise httpx.ReadTimeout("fixture", request=request)
        return normal.handle_request(request)

    with httpx.Client(transport=httpx.MockTransport(handle)) as client:
        return execute(store, manifest(), client)


def plan_continuation(store: Store, parent: str, **kwargs: Any) -> Any:
    from content_eval.cmto import continuation_manifest

    options = {
        "max_estimated_usd": Decimal("100"),
        "max_calls": 57,
        "generation_timeout_seconds": 120,
        "acknowledge_uncertain_attempts": True,
        "unknown_cost_reserve_usd": Decimal("0.25"),
    }
    return continuation_manifest(store, parent, **{**options, **kwargs})


def test_continuation_reuses_originals_and_preserves_unknown_cost(tmp_path: Path) -> None:
    calls: list[dict[str, Any]] = []
    timeouts: list[float] = []
    normal = transport(calls)

    def handle(request: httpx.Request) -> httpx.Response:
        timeouts.append(request.extensions["timeout"]["read"])
        return normal.handle_request(request)

    with Store(tmp_path / "run.db") as store:
        parent = stopped_parent(store)
        prior = store.events(parent)
        assert project(prior)["status"] == "stopped"
        child_plan = plan_continuation(store, parent)
        with httpx.Client(transport=httpx.MockTransport(handle)) as client:
            child = execute(store, child_plan, client)
        assert store.events(parent) == prior
        assert len(calls) == 54
        assert timeouts[:14] == [120] * 14
        assert timeouts[14:] == [30] * 40
        events = store.events(child)
        report = project(events)
        assert report["status"] == "completed"
        assert report["reused_candidates"] == 2
        assert report["prepared_candidates"] == 18
        assert report["frozen_pool_size"] == 20
        assert report["continuation"]["prior_calls"] == 3
        assert report["continuation"]["prior_unknown_attempts"] == 1
        assert not report["experiment_cost_complete"]
        assert report["generation"]["cost_complete"]
        known_total = (
            Decimal(project(prior)["experiment_estimated_cost_usd"])
            + Decimal(report["generation"]["estimated_cost_usd"])
            + sum(Decimal(s["estimated_cost_usd"]) for s in report["arms"].values())
        )
        assert Decimal(report["experiment_estimated_cost_usd"]) == known_total
        pool = next(e.payload["inputs"] for e in events if e.event_type == "pool.frozen")
        by_id = {item["id"]: item for item in pool}
        for event in prior:
            if event.event_type == "candidate.prepared":
                assert by_id[event.candidate_id] == event.payload["candidate"]
        assert project([Event.model_validate_json(e.model_dump_json()) for e in events]) == report
        with httpx.Client(transport=transport([])) as client:
            with pytest.raises(ValueError, match="already has a continuation"):
                execute(store, child_plan, client)


@pytest.mark.parametrize(
    "overrides",
    [
        {"acknowledge_uncertain_attempts": False},
        {"unknown_cost_reserve_usd": Decimal(0)},
    ],
)
def test_continuation_requires_explicit_uncertain_cost_ack(
    tmp_path: Path,
    overrides: dict[str, Any],
) -> None:
    calls: list[dict[str, Any]] = []
    with Store(tmp_path / "run.db") as store:
        parent = stopped_parent(store)
        count_before = store.db.execute("SELECT COUNT(*) FROM events").fetchone()[0]
        plan = plan_continuation(store, parent, **overrides)
        with httpx.Client(transport=transport(calls)) as client:
            with pytest.raises(ValueError, match="uncertain prior calls"):
                execute(store, plan, client)
        assert not calls
        assert store.db.execute("SELECT COUNT(*) FROM events").fetchone()[0] == count_before


def test_continuation_reserve_counts_against_budget(tmp_path: Path) -> None:
    calls: list[dict[str, Any]] = []
    with Store(tmp_path / "run.db") as store:
        parent = stopped_parent(store)
        plan = plan_continuation(store, parent, unknown_cost_reserve_usd=Decimal(100))
        with httpx.Client(transport=transport(calls)) as client:
            child = execute(store, plan, client)
        assert not calls
        report = project(store.events(child))
        assert report["status"] == "stopped"
        assert report["stop_reason"] == "estimated_spend_guard"
        assert not report["experiment_cost_complete"]


def test_chained_continuation_carries_originals_and_cumulative_call_cap(tmp_path: Path) -> None:
    with Store(tmp_path / "run.db") as store:
        parent = stopped_parent(store)
        calls: list[dict[str, Any]] = []
        with httpx.Client(transport=transport(calls)) as client:
            child = execute(store, plan_continuation(store, parent, max_calls=4), client)
        assert len(calls) == 1
        assert project(store.events(child))["stop_reason"] == "call_cap"
        next_plan = plan_continuation(store, child)
        carry = next_plan.provider_config["continuation"]
        assert carry["prior_calls"] == 4
        assert carry["prior_unknown_attempts"] == 1
        assert len(carry["prepared"]) == 3
        final_calls: list[dict[str, Any]] = []
        with httpx.Client(transport=transport(final_calls)) as client:
            final = execute(store, next_plan, client)
        assert len(final_calls) == 53
        assert project(store.events(final))["collection_complete"]


def test_read_only_preview_and_legacy_stop_status(tmp_path: Path) -> None:
    path = tmp_path / "run.db"
    with Store(path) as store:
        m = manifest()
        data = m.model_dump(mode="json")
        store.append(
            "old",
            "run.created",
            {
                "manifest": data,
                "manifest_hash": digest(data),
                "inputs": [],
                "input_hashes": [],
            },
        )
        store.append("old", "run.completed", {"reason": "generation_failed_no_retry"})
        assert project(store.events("old"))["status"] == "stopped"
    before = path.read_bytes()
    with Store(path, read_only=True) as store:
        assert len(store.events("old")) == 2
        with pytest.raises(ValueError, match="read-only"):
            with store.writer():
                pass
    assert path.read_bytes() == before

    result = CliRunner().invoke(
        app,
        [
            "cmto-continue",
            "old",
            "--db",
            str(path),
            "--max-estimated-usd",
            "5",
            "--max-calls",
            "56",
        ],
    )
    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["network_calls"] == 0
    assert path.read_bytes() == before


def test_same_model_rejected_and_generator_cost_separate(tmp_path: Path) -> None:
    config = LiveConfig(provider="anthropic", model="claude-opus-5")
    with pytest.raises(ValueError, match="different"):
        make_manifest(fixture_pack(), config, Decimal(5), generator=config)
    old = make_manifest(fixture_pack(), config, Decimal(5))
    calls: list[dict[str, Any]] = []
    with Store(tmp_path / "run.db") as store, httpx.Client(transport=transport(calls)) as client:
        with pytest.raises(ValueError, match="same-model"):
            execute(store, old, client)
        assert not calls
        mid = execute(store, manifest(), client)
        report = project(store.events(mid))
        assert Decimal(report["generation"]["estimated_cost_usd"]) == Decimal("0.0224")
        assert all(call["model"] == "gpt-5.6-sol" for call in calls[:16])


def test_reevaluate_saved_pool_without_generator_key(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from content_eval.cmto import reevaluation_manifest

    path = tmp_path / "run.db"
    with Store(path) as store, httpx.Client(transport=transport([])) as client:
        parent = execute(store, manifest("openai"), client)
        prior = store.events(parent)
        m = reevaluation_manifest(
            store,
            parent,
            LiveConfig(provider="openai", model="gpt-5.6-sol"),
            Decimal(5),
        )
        monkeypatch.delenv("ANTHROPIC_API_KEY")
        calls: list[dict[str, Any]] = []
        with httpx.Client(transport=transport(calls)) as reviewer_client:
            child = execute(store, m, reviewer_client)
        assert len(calls) == 40
        assert store.events(parent) == prior
        child_events = store.events(child)
        parent_pool = next(e.payload["inputs"] for e in prior if e.event_type == "pool.frozen")
        child_pool = next(
            e.payload["inputs"] for e in child_events if e.event_type == "pool.frozen"
        )
        assert parent_pool == child_pool
        report = project(child_events)
        assert report["generation"]["attempts"] == 0
        assert report["arms"]["llm"]["model"] == "gpt-5.6-sol"
        assert report["arms"]["llm"]["accuracy"] is None
        assert report["arms"]["jev"]["accuracy"] is None
        assert report["evaluation_pool"]["generator_model"] == "claude-opus-5"


def labelled_packet(path: Path, *, reference_type: str = "human") -> dict[str, Any]:
    packet = json.loads(path.read_text())
    packet.update(
        {
            "reviewer_id": "test-reviewer",
            "qualification": "synthetic fixture only",
            "reference_type": reference_type,
            "independent": True,
        }
    )
    for item, verdict in zip(
        packet["items"],
        ("acceptable", "rejectable", "revisable", "unresolved"),
        strict=False,
    ):
        item.update({"disposition": verdict, "notes": "Fixture reference.", "review_seconds": 1})
    return packet


def test_blinded_audit_accuracy_abstentions_and_replay(tmp_path: Path) -> None:
    from content_eval.audit import export_packet, import_labels

    normal = transport([])

    def handle(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        if "state" in body:
            return httpx.Response(
                200,
                json={
                    "model": body["model"],
                    "usage": {"input_tokens": 100, "output_tokens": 40},
                    "answers": {key: {"type": "noul", "noul": 0.5} for key in body["questions"]},
                },
            )
        return normal.handle_request(request)

    path = tmp_path / "packet.json"
    with Store(tmp_path / "run.db") as store:
        with httpx.Client(transport=httpx.MockTransport(handle)) as client:
            mid = execute(store, manifest("openai"), client)
        before = project(store.events(mid))
        export_packet(store, mid, path)
        exported = json.loads(path.read_text())
        assert set(exported).isdisjoint({"arm", "decisions", "cohort", "mapping"})
        assert all(
            set(item["candidate"]).isdisjoint({"id", "family_id", "cohort"})
            for item in exported["items"]
        )
        packet = labelled_packet(path)
        path.write_text(json.dumps(packet))
        assert import_labels(store, mid, path) == 4
        events = store.events(mid)
        after = project(events)
        assert after["observed_active_elapsed_ms"] == before["observed_active_elapsed_ms"]
        llm = after["arms"]["llm"]["accuracy_details"]
        jev = after["arms"]["jev"]["accuracy_details"]
        assert llm["accuracy"] == 1 / 3
        assert llm["pass_precision"] == 1 / 3
        assert llm["acceptable_recall"] == 1
        assert llm["labelled_evaluated"] == 3
        assert llm["reference_unresolved"] == 1
        assert llm["false_accepts"] == 2
        assert jev["accuracy"] == 0
        assert jev["abstentions"] == 3
        assert jev["decision_coverage"] == 0
        assert jev["decided_accuracy"] is None
        assert (
            sum(
                stats["labelled_evaluated"]
                for stats in after["arms"]["llm"]["accuracy_by_population"].values()
            )
            == 3
        )
        assert project([Event.model_validate_json(e.model_dump_json()) for e in events]) == after
        with pytest.raises(ValueError, match="already exists"):
            import_labels(store, mid, path)
        assert store.events(mid) == events


@pytest.mark.parametrize("tamper", ["candidate", "source", "independence", "duplicate"])
def test_audit_rejects_changed_input_or_invalid_provenance(
    tmp_path: Path,
    tamper: str,
) -> None:
    from content_eval.audit import export_packet, import_labels

    path = tmp_path / "packet.json"
    with Store(tmp_path / "run.db") as store, httpx.Client(transport=transport([])) as client:
        mid = execute(store, manifest(), client)
        export_packet(store, mid, path)
        packet = labelled_packet(path)
        if tamper == "candidate":
            packet["items"][0]["candidate"]["stem"] = "changed"
        elif tamper == "source":
            packet["source"] = "changed"
        elif tamper == "independence":
            packet["independent"] = False
        else:
            packet["items"].append(packet["items"][0])
        path.write_text(json.dumps(packet))
        before = store.events(mid)
        with pytest.raises(ValueError):
            import_labels(store, mid, path)
        assert store.events(mid) == before


def test_proxy_labels_do_not_become_human_accuracy(tmp_path: Path) -> None:
    from content_eval.audit import export_packet, import_labels

    path = tmp_path / "packet.json"
    with Store(tmp_path / "run.db") as store, httpx.Client(transport=transport([])) as client:
        mid = execute(store, manifest(), client)
        export_packet(store, mid, path)
        path.write_text(json.dumps(labelled_packet(path, reference_type="proxy")))
        import_labels(store, mid, path)
        result = project(store.events(mid))
        assert result["arms"]["llm"]["accuracy"] is None
        assert result["arms"]["llm"]["proxy_accuracy_details"]["accuracy"] == 1 / 3
        assert result["audited_quality"] is None
