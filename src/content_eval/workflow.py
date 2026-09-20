"""A resumable fake-provider run with durable intent before every attempt."""

import json
import time
from typing import cast
from uuid import uuid4

from pydantic import JsonValue, ValidationError

from content_eval.models import ARMS, Arm, Candidate, Evaluation, Event, Manifest, digest
from content_eval.projection import project
from content_eval.providers import Evaluator, FakeEvaluator, ProviderError, generate
from content_eval.storage import Store


def run(
    store: Store,
    manifest: Manifest | None = None,
    run_id: str | None = None,
    evaluators: dict[Arm, Evaluator] | None = None,
) -> str:
    with store.writer():
        if manifest is not None and manifest.mode == "cmto-development":
            raise ValueError("use the dedicated CMTO development coordinator")
        run_id = run_id or str(uuid4())
        events = store.events(run_id)
        if events:
            report = project(events)
            frozen = Manifest.model_validate(events[0].payload["manifest"])
            if manifest is not None and frozen != manifest:
                raise ValueError("resume manifest differs from the frozen run")
            manifest = frozen
            if manifest.mode == "cmto-development":
                raise ValueError("CMTO resume is inspection-only; paid attempts are never repeated")
            if report["status"] == "completed":
                return run_id
            if manifest.mode == "live-smoke" and evaluators is None:
                raise ValueError(
                    "live resume needs explicitly configured adapters; fake fallback forbidden"
                )
            store.append(run_id, "run.resumed", {})
        else:
            if manifest is None:
                raise ValueError("unknown run ID")
            if manifest.mode == "live-smoke" and evaluators is None:
                raise ValueError("live run requires explicitly configured adapters")
            data = manifest.model_dump(mode="json")
            inputs = generate(manifest)
            store.append(
                run_id,
                "run.created",
                {
                    "manifest": data,
                    "manifest_hash": digest(data),
                    "input_hashes": [digest(item) for item in inputs],
                    "inputs": cast(JsonValue, inputs),
                },
            )
        try:
            _process(store, run_id, manifest, evaluators)
            store.append(run_id, "run.completed", {"reason": "fixed_pool_exhausted"})
        except KeyboardInterrupt:
            store.append(run_id, "run.cancelled", {"reason": "keyboard_interrupt"})
            raise
        except Exception as exc:
            # Do not persist arbitrary exception messages which may contain secrets.
            store.append(run_id, "run.failed", {"reason": type(exc).__name__})
            raise
        return run_id


def _process(
    store: Store,
    run_id: str,
    manifest: Manifest,
    evaluators: dict[Arm, Evaluator] | None,
) -> None:
    events = store.events(run_id)
    finished = {
        e.attempt_id
        for e in events
        if e.event_type
        in {
            "attempt.succeeded",
            "attempt.failed",
            "attempt.recovery_unknown",
        }
    }
    for event in events:
        if event.event_type == "attempt.started" and event.attempt_id not in finished:
            store.append(
                run_id,
                "attempt.recovery_unknown",
                {
                    "reason": "interrupted_after_intent",
                    "usage": None,
                    "cost_usd": None,
                },
                arm=event.arm,
                candidate_id=event.candidate_id,
                operation_id=event.operation_id,
                attempt_id=event.attempt_id,
            )
    generated = {e.candidate_id for e in events if e.event_type == "candidate.generated"}
    pool = next(
        (e.payload for e in reversed(events) if e.event_type == "pool.frozen"),
        events[0].payload,
    )
    inputs = pool["inputs"]
    if not isinstance(inputs, list) or [digest(item) for item in inputs] != pool["input_hashes"]:
        raise ValueError("frozen input pool hash mismatch")
    for raw in inputs:
        if not isinstance(raw, dict):
            raise ValueError("invalid frozen candidate")
        cid = str(raw["id"])
        if cid not in generated:
            store.append(
                run_id,
                "candidate.generated",
                {
                    "candidate": raw,
                    "input_hash": digest(raw),
                },
                candidate_id=cid,
            )
        own = [e for e in store.events(run_id) if e.candidate_id == cid]
        if any(e.event_type == "candidate.invalid" for e in own):
            continue
        try:
            candidate = Candidate.model_validate(raw)
            if manifest.mode == "cmto-development":
                from content_eval.cmto import validate_candidate

                validate_candidate(candidate, manifest)
        except (ValidationError, ValueError) as exc:
            store.append(
                run_id,
                "candidate.invalid",
                {
                    "reason": "schema_validation",
                    "errors": (
                        json.loads(exc.json(include_input=False, include_context=False))
                        if isinstance(exc, ValidationError)
                        else str(exc)
                    ),
                },
                candidate_id=cid,
            )
            continue
        if not any(e.event_type == "candidate.validated" for e in own):
            store.append(
                run_id, "candidate.validated", {"schema": "candidate-v1"}, candidate_id=cid
            )
        for arm in ARMS:
            provider = (
                evaluators[arm]
                if evaluators is not None
                else FakeEvaluator(arm, manifest.failure_mode)
            )
            _evaluate(store, run_id, manifest, candidate, arm, provider)


def _evaluate(
    store: Store,
    run_id: str,
    manifest: Manifest,
    candidate: Candidate,
    arm: Arm,
    provider: Evaluator,
) -> None:
    cid = candidate.id
    own = [e for e in store.events(run_id) if e.candidate_id == cid and e.arm == arm]
    if any(e.event_type == "selection.recorded" for e in own):
        return
    decisions = [e for e in own if e.event_type == "decision.recorded"]
    if decisions:
        if decisions[-1].payload["decision"] == "pass":
            _select(store, run_id, manifest, candidate, arm)
        return
    operation = f"evaluate:{arm}:{cid}"
    successful = [e for e in own if e.event_type == "attempt.succeeded"]
    used_attempts = sum(e.event_type == "attempt.started" for e in own)
    last_terminal = [
        e
        for e in own
        if e.event_type
        in {
            "attempt.failed",
            "attempt.recovery_unknown",
        }
    ]
    can_retry = not last_terminal or last_terminal[-1].payload.get("transient", False)
    success: Event | None = successful[-1] if successful else None
    for number in range(used_attempts + 1, manifest.max_attempts + 1):
        if success is not None or (used_attempts and not can_retry):
            break
        if number > 1:
            # Fake retries have no delay; real backoff belongs to future adapters.
            store.append(
                run_id,
                "retry.scheduled",
                {"number": number, "delay_ms": 0},
                arm=arm,
                candidate_id=cid,
                operation_id=operation,
            )
        attempt = f"{operation}:{number}"
        build_request = getattr(provider, "request_body", None)
        request_payload = build_request(candidate) if callable(build_request) else None
        store.append(
            run_id,
            "attempt.started",
            {
                "number": number,
                "requested_model": provider.model,
                "input_hash": digest(candidate.model_dump(mode="json")),
                "request_payload": request_payload,
                "request_hash": digest(request_payload) if request_payload is not None else None,
                "rate_card_id": manifest.rates[arm].id,
            },
            arm=arm,
            candidate_id=cid,
            operation_id=operation,
            attempt_id=attempt,
        )
        started = time.monotonic_ns()
        try:
            # Frozen Pydantic objects can still contain mutable nested dictionaries.
            # Isolate adapters so they cannot alter persisted inputs or the other arm.
            result = provider.evaluate(candidate.model_copy(deep=True), number)
        except ProviderError as exc:
            error_cost = manifest.rates[arm].cost(exc.usage) if exc.pricing_applicable else None
            store.append(
                run_id,
                "attempt.failed",
                {
                    "category": exc.category,
                    "transient": exc.transient,
                    "usage": exc.usage.model_dump(mode="json") if exc.usage else None,
                    "cost_usd": str(error_cost) if error_cost is not None else None,
                    "returned_model": exc.returned_model,
                    "request_id": exc.request_id,
                    "raw_response": exc.raw_response,
                    "latency_ns": time.monotonic_ns() - started,
                },
                arm=arm,
                candidate_id=cid,
                operation_id=operation,
                attempt_id=attempt,
            )
            if not exc.transient:
                break
        else:
            cost = manifest.rates[arm].cost(result.usage) if result.pricing_applicable else None
            success = store.append(
                run_id,
                "attempt.succeeded",
                {
                    "returned_model": result.model,
                    "evaluation": result.evaluation.model_dump(mode="json"),
                    "usage": result.usage.model_dump(mode="json") if result.usage else None,
                    "request_id": result.request_id,
                    "raw_response": result.raw_response,
                    "cost_usd": str(cost) if cost is not None else None,
                    "rate_card_id": manifest.rates[arm].id,
                    "latency_ns": time.monotonic_ns() - started,
                },
                arm=arm,
                candidate_id=cid,
                operation_id=operation,
                attempt_id=attempt,
            )
    if success:
        evaluation = Evaluation.model_validate(success.payload["evaluation"])
        decision, reason = manifest.policy.decide(evaluation)
        if not any(e.event_type == "evaluation.completed" for e in own):
            store.append(
                run_id,
                "evaluation.completed",
                {
                    "result_event_id": success.event_id,
                },
                arm=arm,
                candidate_id=cid,
                operation_id=operation,
                attempt_id=success.attempt_id,
            )
    else:
        decision, reason = "unresolved", "provider_unavailable_or_interrupted"
    store.append(
        run_id,
        "decision.recorded",
        {
            "decision": decision,
            "reason": reason,
            "policy_version": manifest.policy.version,
        },
        arm=arm,
        candidate_id=cid,
        operation_id=operation,
    )
    if decision == "pass":
        _select(store, run_id, manifest, candidate, arm)


def _select(
    store: Store,
    run_id: str,
    manifest: Manifest,
    candidate: Candidate,
    arm: Arm,
) -> None:
    selections = [
        e
        for e in store.events(run_id)
        if e.arm == arm
        and e.event_type == "selection.recorded"
        and e.payload["reason"] == "selected"
    ]
    representative = next(
        (e.candidate_id for e in selections if e.payload["fingerprint"] == candidate.fingerprint()),
        None,
    )
    reason = (
        "exact_duplicate"
        if representative
        else "target_filled"
        if len(selections) >= manifest.target
        else "selected"
    )
    store.append(
        run_id,
        "selection.recorded",
        {
            "reason": reason,
            "representative": representative,
            "topic": candidate.topic,
            "fingerprint": candidate.fingerprint(),
            "selector_version": manifest.selector_version,
        },
        arm=arm,
        candidate_id=candidate.id,
    )
