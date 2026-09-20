"""Read-only, versioned counterfactuals over saved evaluations, never new inference."""

from collections import Counter
from math import isfinite
from typing import Any, cast

from content_eval.audit import accuracy, candidates
from content_eval.models import ARMS, Arm, Evaluation, Event, Manifest, digest
from content_eval.projection import project


def filter_decision(
    evaluation: Evaluation, required: tuple[str, ...], threshold: float, arm: Arm
) -> tuple[str, str]:
    """Uncertainty can justify withholding; it never establishes a factual defect."""
    if not isfinite(threshold) or not 0.5 <= threshold <= 1:
        raise ValueError("threshold must be finite and between 0.5 and 1")
    if set(evaluation.checks) != set(required):
        return "unresolved", "rubric_mismatch"
    if evaluation.critical_failures:
        return "withhold", "critical_failure"
    # Jev's uncertain flag is derived from the OLD threshold, not an independent answer.
    # LLM uncertainty is an explicit categorical answer and must not become a pass.
    if arm == "llm" and evaluation.uncertain:
        return "withhold", "categorical_uncertainty"
    if any(value < threshold or value == 0.5 for value in evaluation.checks.values()):
        return "withhold", "insufficient_pass_evidence"
    return "pass", "all_checks_meet_threshold"


def analyze_policy(events: list[Event], threshold: float | None = None) -> dict[str, Any]:
    baseline = project(events)  # Verifies the complete source hash chain first.
    if baseline["mode"] != "cmto-development" or not baseline["collection_complete"]:
        raise ValueError("policy analysis requires a complete CMTO collection")
    manifest = Manifest.model_validate(events[0].payload["manifest"])
    cutoff = manifest.policy.threshold if threshold is None else threshold
    if not isfinite(cutoff) or not 0.5 <= cutoff <= 1:
        raise ValueError("threshold must be finite and between 0.5 and 1")
    pool = candidates(events)
    cfg = cast(dict[str, Any], manifest.provider_config)
    populations = {
        name: {slot["id"] for slot in cfg["slots"] if slot["kind"] == name}
        for name in ("ordinary", "defect", "paraphrase")
    }
    policy = {
        "version": "offline-filter-first-v1",
        "threshold": cutoff,
        "required_checks": list(manifest.policy.required_checks),
        "tie_action": "withhold",
        "llm_uncertainty_action": "withhold",
        "missing_or_invalid_result_action": "unresolved",
    }
    arms = {}
    for arm in ARMS:
        successes = {
            e.event_id: e for e in events if e.event_type == "attempt.succeeded" and e.arm == arm
        }
        completions = {
            e.candidate_id: e
            for e in events
            if e.event_type == "evaluation.completed" and e.arm == arm
        }
        decisions = {}
        details = []
        for cid in pool:
            completed = completions.get(cid)
            result = successes.get(str(completed.payload["result_event_id"])) if completed else None
            evaluation = None
            if result is None:
                decision, reason = "unresolved", "no_completed_evaluation"
            else:
                if result.candidate_id != cid:
                    raise ValueError("evaluation result belongs to another candidate")
                evaluation = Evaluation.model_validate(result.payload["evaluation"])
                decision, reason = filter_decision(
                    evaluation, manifest.policy.required_checks, cutoff, arm
                )
            decisions[cid] = decision
            details.append(
                {
                    "candidate_id": cid,
                    "result_event_id": result.event_id if result else None,
                    "decision": decision,
                    "reason": reason,
                    "original_uncertainty_flag": evaluation.uncertain if evaluation else None,
                    "checks": evaluation.checks if evaluation else None,
                }
            )
        counts = Counter(decisions.values())
        stats = baseline["arms"][arm]
        arms[arm] = {
            "model": stats["model"],
            "baseline_accuracy": stats["accuracy"],
            "baseline_unresolved": stats["unresolved"],
            "passes": counts["pass"],
            "withheld": counts["withhold"],
            "unresolved": counts["unresolved"],
            "original_uncertainty_flags": sum(
                item["original_uncertainty_flag"] is True for item in details
            ),
            "reason_counts": dict(Counter(item["reason"] for item in details)),
            "accuracy_details": accuracy(events, arm, decision_overrides=decisions),
            "accuracy_by_population": {
                population: accuracy(
                    events,
                    arm,
                    population=population,
                    decision_overrides={
                        cid: value
                        for cid, value in decisions.items()
                        if cid in populations[population]
                    },
                )
                for population in ("ordinary", "defect", "paraphrase")
            },
            "source_evaluation_estimated_cost_usd": stats["estimated_cost_usd"],
            "source_cost_complete": stats["cost_complete"],
            "source_attempt_latency_p50_ms": stats["attempt_latency_p50_ms"],
            "decisions": details,
        }
    report = {
        "kind": "offline_policy_analysis",
        "parent_run_id": baseline["run_id"],
        "parent_manifest_hash": baseline["manifest_hash"],
        "parent_event_hash": events[-1].event_hash,
        "policy": policy,
        "policy_hash": digest(policy),
        "network_calls": 0,
        "new_inference_cost_usd": "0",
        "arms": arms,
        "warning": "Post-hoc development analysis, not held-out validation. "
        "Existing human labels include any recorded owner scope adjustments. "
        "Withhold means not admitted, not proven wrong. Original uncertainty is preserved. "
        "Pass counts are before deduplication/selection. No live policy or journal was changed.",
    }
    return {**report, "analysis_hash": digest(report)}
