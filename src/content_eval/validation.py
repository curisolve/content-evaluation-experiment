"""Predeclared validation batch; no labels or development judgments enter generation."""

from decimal import Decimal
from typing import Any, cast

from pydantic import JsonValue

from content_eval.audit import candidates
from content_eval.live import LiveConfig
from content_eval.models import Manifest, Policy, digest
from content_eval.projection import project
from content_eval.storage import Store

POLICY_VERSION = "cmto-filter-first-validation-v1"


def validation_manifest(store: Store, parent_id: str, budget: Decimal) -> Manifest:
    from content_eval.cmto import make_manifest

    events = store.events(parent_id)
    report = project(events)
    if report["mode"] != "cmto-development" or not report["collection_complete"]:
        raise ValueError("validation requires a complete development pool")
    old = Manifest.model_validate(events[0].payload["manifest"])
    cfg = cast(dict[str, Any], old.provider_config)
    if "validation" in cfg:
        raise ValueError("do not use a validation batch as development data for this protocol")
    if any(
        report["arms"][arm]["accuracy_details"]["labelled_evaluated"] != 20
        for arm in ("jev", "llm")
    ):
        raise ValueError("complete development reference labels required before freezing")
    generator = LiveConfig.model_validate(cfg.get("generator", cfg["llm"]))
    reviewer = LiveConfig.model_validate(cfg["llm"])
    if generator.provider != "anthropic" or reviewer.provider != "openai":
        raise ValueError("validation requires Anthropic generation and OpenAI review")
    base = make_manifest(
        cfg["pack"],
        reviewer,
        budget,
        generator=generator,
        generation_timeout_seconds=120,
    )
    pool = list(candidates(events).values())
    protocol = {
        "version": "cmto-prospective-validation-v1",
        "parent_run_id": parent_id,
        "parent_event_hash": events[-1].event_hash,
        "parent_manifest_hash": events[0].payload["manifest_hash"],
        "excluded_pool_hash": digest([item.model_dump(mode="json") for item in pool]),
        "excluded_stems": sorted({item.stem for item in pool}),
        "decision_rule": "all ten checks > 0.5; ties/explicit uncertainty withhold; "
        "missing or invalid responses unresolved; critical failures withhold",
        "label_rule": "Acceptable unchanged may have optional wording improvements. "
        "Necessary corrections mean revisable/rejectable. Semantic redundancy is separate.",
        "analysis_plan": "Report ordinary and challenge populations separately; "
        "accuracy, pass precision, acceptable recall, false accepts/rejects, unresolved, "
        "evaluation cost and latency. No threshold retuning or replacing failed items.",
        "independence_note": "Fresh generation with exact-stem exclusion only; "
        "semantic/family overlap with development requires independent review before "
        "claiming held-out validation. Within-pool challenge variants remain correlated.",
    }
    return base.model_copy(
        update={
            "policy": Policy(
                version=POLICY_VERSION, threshold=0.5, required_checks=base.policy.required_checks
            ),
            "provider_config": {
                **base.provider_config,
                "validation": cast(JsonValue, protocol),
                "generator_instructions": str(base.provider_config["generator_instructions"])
                + " This is a new validation batch. The excluded development stems are data, "
                "not examples to imitate. Create new scenarios, not rewrites of those stems. "
                "Only paraphrase slots may reuse their NEW batch parent's scenario.",
            },
        }
    )


def reject_existing_validation(store: Store, parent_id: str) -> None:
    import json

    for row in store.db.execute("SELECT body FROM events WHERE sequence=1"):
        cfg = json.loads(row[0])["payload"]["manifest"]["provider_config"]
        if cfg.get("validation", {}).get("parent_run_id") == parent_id:
            raise ValueError(
                "validation already started for this parent; inspect that run, "
                "do not cherry-pick a replacement batch"
            )
