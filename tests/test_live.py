import json
from decimal import Decimal
from pathlib import Path

import httpx
import pytest
from typer.testing import CliRunner

from content_eval.cli import app
from content_eval.live import (
    INSTRUCTIONS,
    QUESTIONS,
    LiveConfig,
    LiveEvaluator,
    normalize_usage,
    rate_card,
    smoke_manifest,
)
from content_eval.models import Candidate, Manifest
from content_eval.projection import project
from content_eval.providers import ProviderError, generate
from content_eval.storage import Store
from content_eval.workflow import run


@pytest.fixture(autouse=True)
def dummy_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in ("TYPESAFE_API_KEY", "OPENAI_API_KEY", "ANTHROPIC_API_KEY"):
        monkeypatch.setenv(key, "fixture-secret")


def fixture_response(provider: str) -> dict:
    verdicts = json.dumps({key: "pass" for key in QUESTIONS})
    if provider == "jev":
        return {
            "model": "jev-1.13.0",
            "answers": {key: {"type": "noul", "noul": 0.99} for key in QUESTIONS},
            "usage": {"input_tokens": 100, "output_tokens": 10},
        }
    if provider == "openai":
        return {
            "model": "gpt-5.6-sol",
            "status": "completed",
            "service_tier": "default",
            "output": [{"type": "message", "content": [{"type": "output_text", "text": verdicts}]}],
            "usage": {
                "input_tokens": 1000,
                "output_tokens": 100,
                "input_tokens_details": {"cached_tokens": 400, "cache_write_tokens": 100},
                "output_tokens_details": {"reasoning_tokens": 60},
            },
        }
    return {
        "model": "claude-opus-5",
        "stop_reason": "end_turn",
        "content": [{"type": "text", "text": verdicts}],
        "usage": {
            "input_tokens": 500,
            "output_tokens": 100,
            "cache_read_input_tokens": 400,
            "cache_creation_input_tokens": 100,
            "cache_creation": {"ephemeral_5m_input_tokens": 40, "ephemeral_1h_input_tokens": 60},
        },
    }


@pytest.mark.parametrize(
    ("provider", "model"),
    [
        ("jev", "jev-1.13.0"),
        ("openai", "gpt-5.6-sol"),
        ("anthropic", "claude-opus-5"),
    ],
)
def test_adapter_contract(provider: str, model: str) -> None:
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(
            200, json=fixture_response(provider), headers={"x-request-id": "req-1"}
        )

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        config = LiveConfig.model_validate({"provider": provider, "model": model})
        evaluator = LiveEvaluator(config, client)
        result = evaluator.evaluate(Candidate.model_validate(generate(Manifest(count=1))[0]), 1)
    assert len(seen) == 1
    request = json.loads(seen[0].content)
    assert request["model"] == model
    assert "family_id" not in seen[0].content.decode()
    assert "cohort" not in seen[0].content.decode()
    assert "fixture-secret" not in result.model_dump_json()
    assert result.model == model
    assert result.request_id == "req-1"
    assert result.usage is not None and result.usage.provenance == "provider_reported"
    assert result.pricing_applicable
    assert all(score >= 0.9 for score in result.evaluation.checks.values())
    if provider == "jev":
        assert set(request["questions"]) == set(QUESTIONS)
        assert all(q["type"] == "noul" for q in request["questions"].values())
    elif provider == "openai":
        assert request["instructions"] == INSTRUCTIONS
        assert request["text"]["format"]["strict"]
        assert request["store"] is False
    else:
        assert seen[0].headers["anthropic-version"] == "2023-06-01"
        assert request["output_config"]["format"]["type"] == "json_schema"


def test_provider_specific_token_costs() -> None:
    o = normalize_usage("openai", fixture_response("openai")["usage"])
    a = normalize_usage("anthropic", fixture_response("anthropic")["usage"])
    assert o is not None and a is not None
    assert o.input_total == a.input_total == 1000
    assert o.uncached_input == a.uncached_input == 500
    assert o.reasoning == 60
    assert a.cache_write_1h == 60
    assert rate_card(LiveConfig(provider="openai", model="gpt-5.6-sol")).cost(o) == Decimal(
        "0.00466"
    )
    assert rate_card(LiveConfig(provider="anthropic", model="claude-opus-5")).cost(a) == Decimal(
        "0.00605"
    )


def test_missing_or_inconsistent_usage_is_unknown() -> None:
    assert normalize_usage("openai", None) is None
    assert normalize_usage("openai", {"input_tokens": 100, "output_tokens": 1}) is None
    raw = fixture_response("openai")["usage"]
    raw["input_tokens"] = 1
    assert normalize_usage("openai", raw) is None
    raw = fixture_response("anthropic")["usage"]
    del raw["cache_creation"]
    assert normalize_usage("anthropic", raw) is None


@pytest.mark.parametrize("status", [401, 429, 529])
def test_http_failures_have_no_hidden_retries_or_secret_leaks(status: int) -> None:
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(status, json={"error": "echo fixture-secret"})

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        evaluator = LiveEvaluator(LiveConfig(provider="jev", model="jev-1.13.0"), client)
        with pytest.raises(ProviderError) as caught:
            evaluator.evaluate(Candidate.model_validate(generate(Manifest(count=1))[0]), 1)
    assert len(calls) == 1
    assert caught.value.transient == (status in {429, 529})
    assert "fixture-secret" not in str(caught.value)
    assert "fixture-secret" not in json.dumps(caught.value.raw_response)


def test_refusal_retains_billable_usage() -> None:
    raw = fixture_response("openai")
    raw["output"] = [{"type": "message", "content": [{"type": "refusal"}]}]
    with httpx.Client(
        transport=httpx.MockTransport(lambda _: httpx.Response(200, json=raw))
    ) as client:
        evaluator = LiveEvaluator(LiveConfig(provider="openai", model="gpt-5.6-sol"), client)
        with pytest.raises(ProviderError) as caught:
            evaluator.evaluate(Candidate.model_validate(generate(Manifest(count=1))[0]), 1)
    assert caught.value.usage is not None
    assert caught.value.usage.output == 100
    assert caught.value.pricing_applicable


def test_jev_uncertainty_is_not_fabricated_confidence() -> None:
    raw = fixture_response("jev")
    raw["answers"]["answer_correct"]["noul"] = 0.5
    with httpx.Client(
        transport=httpx.MockTransport(lambda _: httpx.Response(200, json=raw))
    ) as client:
        result = LiveEvaluator(LiveConfig(provider="jev", model="jev-1.13.0"), client).evaluate(
            Candidate.model_validate(generate(Manifest(count=1))[0]),
            1,
        )
    assert result.evaluation.uncertain
    assert result.evaluation.checks["answer_correct"] == 0.5


def test_preflight_and_preview_do_not_call_network_or_show_keys(tmp_path: Path) -> None:
    runner = CliRunner()
    result = runner.invoke(app, ["check-providers"])
    assert result.exit_code == 0
    assert "fixture-secret" not in result.output
    assert all(json.loads(result.output)["credentials_present"].values())
    db = tmp_path / "not-created.sqlite"
    result = runner.invoke(app, ["live-smoke", "--db", str(db)])
    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["network_calls"] == 0
    assert not db.exists()
    result = runner.invoke(app, ["live-smoke", "--count", "6"])
    assert result.exit_code != 0


def test_live_run_accounting_replay_and_fake_fallback_guard(tmp_path: Path) -> None:
    config = LiveConfig(provider="openai", model="gpt-5.6-sol")
    manifest = smoke_manifest(config)

    def handler(request: httpx.Request) -> httpx.Response:
        provider = "openai" if request.url.host == "api.openai.com" else "jev"
        return httpx.Response(200, json=fixture_response(provider))

    with Store(tmp_path / "live.sqlite") as store:
        with pytest.raises(ValueError, match="requires explicitly"):
            run(store, manifest)
        with httpx.Client(transport=httpx.MockTransport(handler)) as client:
            run_id = run(
                store,
                manifest,
                evaluators={
                    "llm": LiveEvaluator(config, client),
                    "jev": LiveEvaluator(LiveConfig(provider="jev", model="jev-1.13.0"), client),
                },
            )
        report = project(store.events(run_id))
        assert report["mode"] == "live-smoke"
        assert report["actual_billed_usd"] is None
        assert report["arms"]["llm"]["estimated_cost_usd"] == "0.00466"
        assert report["arms"]["jev"]["estimated_cost_usd"] == "0.0000042"
        assert "fixture-secret" not in "".join(e.model_dump_json() for e in store.events(run_id))


def test_unpriced_returned_model_does_not_get_wrong_cost() -> None:
    raw = fixture_response("openai")
    raw["model"] = "unexpected-model"
    with httpx.Client(
        transport=httpx.MockTransport(lambda _: httpx.Response(200, json=raw))
    ) as client:
        result = LiveEvaluator(LiveConfig(provider="openai", model="gpt-5.6-sol"), client).evaluate(
            Candidate.model_validate(generate(Manifest(count=1))[0]),
            1,
        )
    assert not result.pricing_applicable


def test_missing_key_fails_before_request(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("TYPESAFE_API_KEY")
    with httpx.Client() as client:
        with pytest.raises(ValueError, match="TYPESAFE_API_KEY"):
            LiveEvaluator(LiveConfig(provider="jev", model="jev-1.13.0"), client)


def test_non_json_rate_limit_is_still_a_rate_limit() -> None:
    with httpx.Client(
        transport=httpx.MockTransport(lambda _: httpx.Response(429, text="temporarily unavailable"))
    ) as client:
        evaluator = LiveEvaluator(LiveConfig(provider="jev", model="jev-1.13.0"), client)
        with pytest.raises(ProviderError) as caught:
            evaluator.evaluate(Candidate.model_validate(generate(Manifest(count=1))[0]), 1)
    assert caught.value.category == "http_429"
    assert caught.value.transient


def test_billable_invalid_output_is_journaled(tmp_path: Path) -> None:
    config = LiveConfig(provider="openai", model="gpt-5.6-sol")
    manifest = smoke_manifest(config)

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "api.openai.com":
            response = fixture_response("openai")
            response["status"] = "incomplete"
        else:
            response = fixture_response("jev")
        return httpx.Response(200, json=response)

    with Store(tmp_path / "invalid.sqlite") as store:
        with httpx.Client(transport=httpx.MockTransport(handler)) as client:
            run_id = run(
                store,
                manifest,
                evaluators={
                    "llm": LiveEvaluator(config, client),
                    "jev": LiveEvaluator(LiveConfig(provider="jev", model="jev-1.13.0"), client),
                },
            )
        events = store.events(run_id)
        stats = project(events)["arms"]["llm"]
        assert stats["selected"] == []
        assert stats["unresolved"] == 1
        assert stats["estimated_cost_usd"] == "0.00466"
        assert stats["output_tokens"] == 100
        intents = [e for e in events if e.event_type == "attempt.started"]
        assert all(e.payload["request_payload"] and e.payload["request_hash"] for e in intents)
        assert "fixture-secret" not in "".join(e.model_dump_json() for e in events)


def test_success_response_echoed_key_is_redacted() -> None:
    response = fixture_response("jev")
    response["debug"] = "fixture-secret"
    with httpx.Client(
        transport=httpx.MockTransport(lambda _: httpx.Response(200, json=response))
    ) as client:
        result = LiveEvaluator(LiveConfig(provider="jev", model="jev-1.13.0"), client).evaluate(
            Candidate.model_validate(generate(Manifest(count=1))[0]),
            1,
        )
    assert "fixture-secret" not in result.model_dump_json()
    assert result.raw_response["debug"] == "[REDACTED]"
