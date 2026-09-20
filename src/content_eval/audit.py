"""Blinded reference labels and transparent accuracy/abstention accounting."""

import random
from pathlib import Path
from typing import Any, Literal, cast
from uuid import uuid4

from pydantic import Field, JsonValue

from content_eval.models import Arm, Candidate, Event, Frozen, Manifest, digest
from content_eval.storage import Store


class ReferenceLabel(Frozen):
    review_id: str
    input_hash: str
    disposition: Literal["acceptable", "revisable", "rejectable", "unresolved"] | None = None
    notes: str = ""
    review_seconds: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    candidate: dict[str, JsonValue]


class AuditPacket(Frozen):
    packet_id: str
    reviewer_id: str = ""
    qualification: str = ""
    reference_type: Literal["human", "proxy"] = "human"
    independent: bool = False
    source: str
    criteria: list[dict[str, JsonValue]]
    items: list[ReferenceLabel]


def candidates(events: list[Event]) -> dict[str, Candidate]:
    pools = [e for e in events if e.event_type == "pool.frozen"]
    if len(pools) != 1:
        raise ValueError("exactly one frozen pool required")
    payload = pools[0].payload
    inputs = payload["inputs"]
    if not isinstance(inputs, list) or [digest(i) for i in inputs] != payload["input_hashes"]:
        raise ValueError("pool hash mismatch")
    items = [Candidate.model_validate(item) for item in inputs]
    if len({item.id for item in items}) != len(items):
        raise ValueError("duplicate candidate IDs")
    return {item.id: item for item in items}


def export_packet(store: Store, run_id: str, output: Path) -> str:
    from content_eval.projection import project

    with store.writer():
        events = store.events(run_id)
        report = project(events)
        if report["mode"] != "cmto-development" or not report["collection_complete"]:
            raise ValueError("audit export requires a complete CMTO collection")
        if output.exists():
            raise ValueError("audit output already exists")
        manifest = Manifest.model_validate(events[0].payload["manifest"])
        cfg = cast(dict[str, Any], manifest.provider_config)
        remaining = list(candidates(events).values())
        random.SystemRandom().shuffle(remaining)
        ordered = []
        last_family = None
        while remaining:
            index = next(
                (i for i, item in enumerate(remaining) if item.family_id != last_family),
                0,
            )
            item = remaining.pop(index)
            ordered.append(item)
            last_family = item.family_id
        mapping = {}
        entries = []
        for item in ordered:
            review_id = str(uuid4())
            fingerprint = digest(item.model_dump(mode="json"))
            visible = item.model_dump(mode="json", exclude={"id", "family_id", "cohort"})
            mapping[review_id] = {
                "candidate_id": item.id,
                "input_hash": fingerprint,
                "visible_hash": digest(visible),
            }
            entries.append(
                ReferenceLabel(
                    review_id=review_id,
                    input_hash=fingerprint,
                    candidate=visible,
                )
            )
        packet = AuditPacket(
            packet_id=str(uuid4()),
            source=manifest.source_text,
            criteria=cfg["pack"]["rubric"]["checks"],
            items=entries,
        )
        # Durable private mapping before external write; never share the journal with reviewers.
        store.append(
            run_id,
            "audit.packet.created",
            {
                "packet_id": packet.packet_id,
                "mapping": cast(JsonValue, mapping),
                "source_hash": digest(packet.source),
                "criteria_hash": digest(packet.criteria),
            },
        )
        with output.open("x") as stream:
            stream.write(packet.model_dump_json(indent=2) + "\n")
        store.append(
            run_id,
            "export.completed",
            {
                "kind": "blinded_audit",
                "packet_id": packet.packet_id,
                "content_hash": digest(packet.model_dump(mode="json")),
            },
        )
        return packet.packet_id


def import_labels(store: Store, run_id: str, path: Path) -> int:
    from content_eval.projection import project

    packet = AuditPacket.model_validate_json(path.read_text())
    if not packet.independent or not packet.reviewer_id.strip() or not packet.qualification.strip():
        raise ValueError("independence attestation, reviewer identity and qualification required")
    with store.writer():
        events = store.events(run_id)
        project(events)
        registered = next(
            (
                e.payload
                for e in events
                if e.event_type == "audit.packet.created"
                and e.payload["packet_id"] == packet.packet_id
            ),
            None,
        )
        if registered is None:
            raise ValueError("packet is not registered for this run")
        if (
            digest(packet.source) != registered["source_hash"]
            or digest(packet.criteria) != registered["criteria_hash"]
        ):
            raise ValueError("source or criteria changed")
        mapping = cast(dict[str, Any], registered["mapping"])
        existing = {
            str(label["candidate_id"])
            for e in events
            if e.event_type == "audit.labels.imported"
            and e.payload["reference_type"] == packet.reference_type
            for label in cast(list[dict[str, Any]], e.payload["labels"])
        }
        seen = set()
        labels = []
        for item in packet.items:
            if item.review_id in seen or item.review_id not in mapping:
                raise ValueError("duplicate or unknown review ID")
            seen.add(item.review_id)
            ref = mapping[item.review_id]
            if (
                item.input_hash != ref["input_hash"]
                or digest(item.candidate) != ref["visible_hash"]
            ):
                raise ValueError("reviewed candidate changed")
            if item.disposition is None:
                continue
            if ref["candidate_id"] in existing:
                raise ValueError(
                    "reference already exists; labels are append-only, not overwritten"
                )
            if not item.notes.strip() or item.review_seconds is None:
                raise ValueError("label needs notes and active review time")
            labels.append(
                {
                    "candidate_id": ref["candidate_id"],
                    "input_hash": item.input_hash,
                    "disposition": item.disposition,
                    "notes": item.notes,
                    "review_seconds": item.review_seconds,
                }
            )
        if not labels:
            raise ValueError("no new reference labels")
        store.append(
            run_id,
            "audit.labels.imported",
            {
                "packet_id": packet.packet_id,
                "reviewer_id": packet.reviewer_id,
                "qualification": packet.qualification,
                "reference_type": packet.reference_type,
                "independent": packet.independent,
                "labels": cast(JsonValue, labels),
            },
        )
        return len(labels)


def accuracy(
    events: list[Event],
    arm: Arm,
    *,
    reference_type: str = "human",
    population: str | None = None,
) -> dict[str, Any]:
    pool = candidates(events)
    refs: dict[str, str] = {}
    for event in events:
        if (
            event.event_type != "audit.labels.imported"
            or event.payload["reference_type"] != reference_type
        ):
            continue
        if event.payload.get("independent") is not True:
            raise ValueError("reference independence missing")
        for label in cast(list[dict[str, Any]], event.payload["labels"]):
            cid = label["candidate_id"]
            if cid not in pool or label["input_hash"] != digest(pool[cid].model_dump(mode="json")):
                raise ValueError("reference does not match frozen input")
            if cid in refs:
                raise ValueError("duplicate reference label")
            refs[cid] = label["disposition"]
    if population is not None:
        manifest = Manifest.model_validate(events[0].payload["manifest"])
        cfg = cast(dict[str, Any], manifest.provider_config)
        eligible = {s["id"] for s in cfg["slots"] if s["kind"] == population}
        refs = {cid: value for cid, value in refs.items() if cid in eligible}
        pool = {cid: value for cid, value in pool.items() if cid in eligible}
    decisions = {
        e.candidate_id: str(e.payload["decision"])
        for e in events
        if e.event_type == "decision.recorded" and e.arm == arm
    }
    labelled = {cid: verdict for cid, verdict in refs.items() if verdict != "unresolved"}
    evaluated = {cid: verdict for cid, verdict in labelled.items() if cid in decisions}
    correct = sum(
        decisions[cid] == ("pass" if verdict == "acceptable" else "withhold")
        for cid, verdict in evaluated.items()
    )
    abstentions = sum(decisions[cid] == "unresolved" for cid in evaluated)
    decided = len(evaluated) - abstentions
    passes = [cid for cid in evaluated if decisions[cid] == "pass"]
    true_passes = sum(evaluated[cid] == "acceptable" for cid in passes)
    good = sum(value == "acceptable" for value in evaluated.values())
    return {
        "reference_type": reference_type,
        "population": population or "all_mixed_development",
        "accuracy": correct / len(evaluated) if evaluated else None,
        "correct": correct,
        "labelled_evaluated": len(evaluated),
        "resolved_reference_labels": len(labelled),
        "reference_unresolved": sum(v == "unresolved" for v in refs.values()),
        "pool_size": len(pool),
        "label_coverage": len(labelled) / len(pool) if pool else None,
        "abstentions": abstentions,
        "decision_coverage": decided / len(evaluated) if evaluated else None,
        "decided_accuracy": correct / decided if decided else None,
        "pass_precision": true_passes / len(passes) if passes else None,
        "acceptable_recall": true_passes / good if good else None,
        "false_accepts": len(passes) - true_passes,
        "false_rejects": sum(
            decisions[cid] == "withhold" and verdict == "acceptable"
            for cid, verdict in evaluated.items()
        ),
        "definition": "Correct pass/withhold decisions divided by labelled evaluated items; "
        "abstentions earn no correctness credit. Partial audits describe labelled items only.",
    }
