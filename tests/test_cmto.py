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
