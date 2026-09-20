"""The same reducer powers stored-run reports and offline journal replay."""

from decimal import Decimal
from math import ceil
from typing import Any

from content_eval.models import ARMS, Event, Manifest, Usage, digest


def project(events: list[Event]) -> dict[str, Any]:
    if not events or events[0].event_type != "run.created":
        raise ValueError("journal must begin with run.created")
    previous = ""
    for sequence, event in enumerate(events, 1):
        event.verify()
        if (
            event.sequence != sequence
            or event.previous_hash != previous
            or event.run_id != events[0].run_id
        ):
            raise ValueError("journal sequence, run ID or hash chain mismatch")
        previous = event.event_hash
    manifest = Manifest.model_validate(events[0].payload["manifest"])
    if digest(events[0].payload["manifest"]) != events[0].payload["manifest_hash"]:
        raise ValueError("manifest hash mismatch")
    report: dict[str, Any] = {
        "report_version": 1,
        "run_id": events[0].run_id,
        "mode": manifest.mode,
        "warning": (
            "Synthetic judgments, tokens and prices; no quality or savings evidence."
            if manifest.mode == "fake-demo"
            else "CMTO development only: uncalibrated rubric, exact-only deduplication, "
            "mixed ordinary/challenge pool; no approval or verified-quality claim."
            if manifest.mode == "cmto-development"
            else "Live API smoke test; synthetic arithmetic, not CMTO quality or savings evidence."
        ),
        "manifest_hash": events[0].payload["manifest_hash"],
        "status": "running",
        "generated": 0,
        "valid": 0,
        "invalid": 0,
        "audited_quality": None,
        "actual_billed_usd": "0" if manifest.mode == "fake-demo" else None,
        "arms": {},
    }
    for arm in ARMS:
        report["arms"][arm] = {
            "attempts": 0,
            "failures": 0,
            "retries": 0,
            "quality_passes": 0,
            "withheld": 0,
            "unresolved": 0,
            "selected": [],
            "duplicates": 0,
            "target_exclusions": 0,
            "unknown_cost_attempts": 0,
            "estimated_cost_usd": Decimal(0),
            "input_tokens": 0,
            "output_tokens": 0,
            "cache_read_tokens": 0,
            "cache_write_tokens": 0,
            "reasoning_tokens": 0,
            "coverage": {},
            "attempted_candidates": set(),
            "latencies_ns": [],
            "unknown_reasoning_attempts": 0,
        }
    outstanding: set[str] = set()
    generation: dict[str, Any] = {
        "attempts": 0,
        "failures": 0,
        "unknown_cost_attempts": 0,
        "estimated_cost_usd": Decimal(0),
        "input_tokens": 0,
        "output_tokens": 0,
        "cache_read_tokens": 0,
        "cache_write_tokens": 0,
        "reasoning_tokens": 0,
        "unknown_reasoning_attempts": 0,
    }
    pool_size = 0
    prepared = 0
    sessions: dict[str, tuple[int, int]] = {}
    for event in events:
        p = event.payload
        if event.event_type == "candidate.prepared":
            prepared += 1
        if event.event_type != "export.completed" and not event.event_type.startswith("audit."):
            start, _ = sessions.get(event.session_id, (event.elapsed_ns, event.elapsed_ns))
            sessions[event.session_id] = (start, event.elapsed_ns)
        if event.event_type == "candidate.generated":
            report["generated"] += 1
        elif event.event_type == "candidate.validated":
            report["valid"] += 1
        elif event.event_type == "candidate.invalid":
            report["invalid"] += 1
        elif event.event_type in {"run.completed", "run.cancelled", "run.failed", "run.stopped"}:
            report["status"] = event.event_type.split(".")[1]
            report["stop_reason"] = p.get("reason")
        elif event.event_type == "run.resumed":
            report["status"] = "running"
        if event.event_type == "pool.frozen":
            inputs = p["inputs"]
            if not isinstance(inputs, list) or [digest(i) for i in inputs] != p["input_hashes"]:
                raise ValueError("frozen pool hash mismatch")
            pool_size = len(inputs)
        if event.event_type == "generation.started":
            generation["attempts"] += 1
            if event.attempt_id is None or event.attempt_id in outstanding:
                raise ValueError("generation requires unique attempt ID")
            outstanding.add(event.attempt_id)
        elif event.event_type in {"generation.succeeded", "generation.failed"}:
            if event.attempt_id not in outstanding:
                raise ValueError("generation terminal without unique intent")
            outstanding.remove(event.attempt_id)
            generation["failures"] += event.event_type == "generation.failed"
            if p.get("cost_usd") is None:
                generation["unknown_cost_attempts"] += 1
            else:
                generation["estimated_cost_usd"] += Decimal(str(p["cost_usd"]))
            if p.get("usage") is not None:
                usage = Usage.model_validate(p["usage"])
                generation["input_tokens"] += usage.input_total
                generation["output_tokens"] += usage.output
                generation["cache_read_tokens"] += usage.cache_read
                generation["cache_write_tokens"] += usage.cache_write + usage.cache_write_1h
                if usage.reasoning is None:
                    generation["unknown_reasoning_attempts"] += 1
                else:
                    generation["reasoning_tokens"] += usage.reasoning
        if event.arm is None:
            continue
        stats = report["arms"][event.arm]
        if event.event_type == "attempt.started":
            stats["attempts"] += 1
            stats["attempted_candidates"].add(event.candidate_id)
            if event.attempt_id is not None:
                outstanding.add(event.attempt_id)
        elif event.event_type in {
            "attempt.succeeded",
            "attempt.failed",
            "attempt.recovery_unknown",
        }:
            if event.attempt_id not in outstanding:
                raise ValueError("attempt terminal event without a unique intent")
            outstanding.remove(event.attempt_id)
            if event.event_type != "attempt.succeeded":
                stats["failures"] += 1
            if isinstance(p.get("latency_ns"), int):
                stats["latencies_ns"].append(p["latency_ns"])
            if p.get("cost_usd") is None:
                stats["unknown_cost_attempts"] += 1
            else:
                stats["estimated_cost_usd"] += Decimal(str(p["cost_usd"]))
            if p.get("usage") is not None:
                usage = Usage.model_validate(p["usage"])
                stats["input_tokens"] += usage.input_total
                stats["output_tokens"] += usage.output
                stats["cache_read_tokens"] += usage.cache_read
                stats["cache_write_tokens"] += usage.cache_write + usage.cache_write_1h
                if usage.reasoning is None:
                    stats["unknown_reasoning_attempts"] += 1
                else:
                    stats["reasoning_tokens"] += usage.reasoning
        elif event.event_type == "retry.scheduled":
            stats["retries"] += 1
        elif event.event_type == "decision.recorded":
            field = {"pass": "quality_passes", "withhold": "withheld", "unresolved": "unresolved"}[
                str(p["decision"])
            ]
            stats[field] += 1
        elif event.event_type == "selection.recorded":
            if p["reason"] == "selected":
                stats["selected"].append(event.candidate_id)
                topic = str(p["topic"])
                stats["coverage"][topic] = stats["coverage"].get(topic, 0) + 1
            elif p["reason"] == "exact_duplicate":
                stats["duplicates"] += 1
            else:
                stats["target_exclusions"] += 1
    report["outstanding_attempts"] = sorted(outstanding)
    report["observed_active_elapsed_ms"] = (
        sum(end - start for start, end in sessions.values()) / 1_000_000
    )
    report["elapsed_note"] = (
        "Observed session intervals, excluding downtime; arms are interleaved, "
        "not standalone latency benchmarks."
    )
    for stats in report["arms"].values():
        count = len(stats["selected"])
        cost = stats["estimated_cost_usd"]
        complete = stats["unknown_cost_attempts"] == 0 and not outstanding
        stats["cost_complete"] = complete
        stats["cost_per_selected_usd"] = str(cost / count) if count and complete else None
        tried = len(stats.pop("attempted_candidates"))
        stats["cost_per_1000_attempted_usd"] = (
            str(cost * 1000 / tried) if tried and complete else None
        )
        stats["estimated_cost_usd"] = str(cost)
        latencies = sorted(stats.pop("latencies_ns"))
        for label, fraction in (("p50", 0.5), ("p95", 0.95)):
            stats[f"attempt_latency_{label}_ms"] = (
                latencies[ceil(len(latencies) * fraction) - 1] / 1_000_000 if latencies else None
            )
        stats["target_reached"] = count >= manifest.target
        stats["target_gap"] = max(0, manifest.target - count)
    if manifest.mode == "cmto-development":
        from content_eval.audit import accuracy

        has_pool = any(e.event_type == "pool.frozen" for e in events)
        for arm in ARMS:
            measured = accuracy(events, arm) if has_pool else None
            report["arms"][arm]["accuracy"] = measured["accuracy"] if measured else None
            report["arms"][arm]["accuracy_details"] = measured
            report["arms"][arm]["accuracy_by_population"] = {
                kind: accuracy(events, arm, population=kind) if has_pool else None
                for kind in ("ordinary", "defect", "paraphrase")
            }
            provider = manifest.provider_config.get(arm)
            report["arms"][arm]["model"] = (
                provider.get("model") if isinstance(provider, dict) else None
            )
            report["arms"][arm]["proxy_accuracy_details"] = (
                accuracy(events, arm, reference_type="proxy") if has_pool else None
            )
        report["accuracy_note"] = (
            "Independent human reference labels required; model agreement and seeded labels "
            "are not accuracy. Abstentions earn no credit; see denominators and decision coverage."
        )
        if any(
            e.event_type == "audit.labels.imported" and e.payload["reference_type"] == "human"
            for e in events
        ):
            report["audited_quality"] = {
                "status": "independent_reference_labels_imported_not_final_approval",
                "qualification": "reviewer-attested, not independently verified",
            }
        pool_reference = manifest.provider_config.get("evaluation_pool")
        if isinstance(pool_reference, dict):
            report["evaluation_pool"] = {
                k: v for k, v in pool_reference.items() if k not in {"inputs", "input_hashes"}
            }
        if report["status"] == "completed" and report.get("stop_reason") != "fixed_pool_exhausted":
            report["status"] = "stopped"
        report["collection_complete"] = report.get("stop_reason") == "fixed_pool_exhausted"
        cfg = manifest.provider_config
        assignments = cfg.get("slots", [])
        if not isinstance(assignments, list):
            raise ValueError("missing development assignments")
        kinds = {
            str(slot["id"]): str(slot["kind"]) for slot in assignments if isinstance(slot, dict)
        }
        for arm, stats in report["arms"].items():
            populations = {}
            for kind in ("ordinary", "defect", "paraphrase"):
                own = [
                    e for e in events if e.arm == arm and kinds.get(e.candidate_id or "") == kind
                ]
                decisions = [e for e in own if e.event_type == "decision.recorded"]
                populations[kind] = {
                    "attempts": sum(e.event_type == "attempt.started" for e in own),
                    "quality_passes": sum(e.payload["decision"] == "pass" for e in decisions),
                    "withheld": sum(e.payload["decision"] == "withhold" for e in decisions),
                    "unresolved": sum(e.payload["decision"] == "unresolved" for e in decisions),
                    "provisionally_selected": sum(
                        e.event_type == "selection.recorded" and e.payload["reason"] == "selected"
                        for e in own
                    ),
                }
            stats["populations"] = populations
        generation["cost_complete"] = not generation["unknown_cost_attempts"] and not outstanding
        generation["estimated_cost_usd"] = str(generation["estimated_cost_usd"])
        report["generation"] = generation
        report["frozen_pool_size"] = pool_size
        report["prepared_candidates"] = prepared
        report["experiment_estimated_cost_usd"] = str(
            Decimal(generation["estimated_cost_usd"])
            + sum(
                (Decimal(stats["estimated_cost_usd"]) for stats in report["arms"].values()),
                Decimal(0),
            )
        )
        report["experiment_cost_complete"] = generation["cost_complete"] and all(
            stats["cost_complete"] for stats in report["arms"].values()
        )
        report["cost_note"] = (
            "Experiment total counts shared generation once. Arm costs are evaluation-only. "
            "All-item ratios mix ordinary/challenge populations and are not operational yield. "
            "Admission spend guard is estimated, not a provider billing limit."
        )
        if isinstance(pool_reference, dict):
            report["cost_note"] += (
                " Reevaluation costs cover this run's new calls only, excluding parent charges."
            )
        continuation = manifest.provider_config.get("continuation")
        if isinstance(continuation, dict):
            report["continuation"] = {
                key: value for key, value in continuation.items() if key != "prepared"
            }
            prepared_items = continuation.get("prepared")
            report["reused_candidates"] = (
                len(prepared_items) if isinstance(prepared_items, list) else 0
            )
            report["experiment_estimated_cost_usd"] = str(
                Decimal(report["experiment_estimated_cost_usd"])
                + Decimal(str(continuation["prior_known_cost_usd"]))
            )
            if continuation["prior_unknown_attempts"]:
                report["experiment_cost_complete"] = False
            report["cost_note"] += (
                " Continuation total includes prior known charges. Unknown-call reserves are "
                "budget allowances, not costs; prior unknown charges remain unknown."
            )
    return report
