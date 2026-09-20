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
    if digest(manifest.model_dump(mode="json")) != events[0].payload["manifest_hash"]:
        raise ValueError("manifest hash mismatch")
    report: dict[str, Any] = {
        "report_version": 1,
        "run_id": events[0].run_id,
        "mode": "fake-demo",
        "warning": "Synthetic judgments, tokens and prices; no quality or savings evidence.",
        "manifest_hash": events[0].payload["manifest_hash"],
        "status": "running",
        "generated": 0,
        "valid": 0,
        "invalid": 0,
        "audited_quality": None,
        "actual_billed_usd": "0",
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
    sessions: dict[str, tuple[int, int]] = {}
    for event in events:
        p = event.payload
        if event.event_type != "export.completed":
            start, _ = sessions.get(event.session_id, (event.elapsed_ns, event.elapsed_ns))
            sessions[event.session_id] = (start, event.elapsed_ns)
        if event.event_type == "candidate.generated":
            report["generated"] += 1
        elif event.event_type == "candidate.validated":
            report["valid"] += 1
        elif event.event_type == "candidate.invalid":
            report["invalid"] += 1
        elif event.event_type in {"run.completed", "run.cancelled", "run.failed"}:
            report["status"] = event.event_type.split(".")[1]
        elif event.event_type == "run.resumed":
            report["status"] = "running"
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
                stats["cache_write_tokens"] += usage.cache_write
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
    return report
