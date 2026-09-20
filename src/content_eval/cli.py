"""JSON-first commands; fake demo never accesses the network."""

import json
import os
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Annotated

import httpx
import typer

from content_eval.audit import export_packet, import_labels
from content_eval.cmto import continuation_manifest, make_manifest, reevaluation_manifest
from content_eval.cmto import execute as execute_cmto
from content_eval.live import LiveConfig, LiveEvaluator, credential_status, smoke_manifest
from content_eval.models import Arm, Event, Manifest, canonical, digest
from content_eval.policy_analysis import analyze_policy
from content_eval.projection import project
from content_eval.providers import Evaluator
from content_eval.sources import load_pack
from content_eval.storage import Store
from content_eval.workflow import run

app = typer.Typer(no_args_is_help=True, pretty_exceptions_enable=False)
Database = Annotated[Path, typer.Option("--db", help="SQLite journal path")]
RunID = Annotated[str, typer.Argument(help="Run identifier from demo output")]


def emit(value: object) -> None:
    typer.echo(json.dumps(value, indent=2, sort_keys=True))


@app.command("check-providers")
def check_providers() -> None:
    """Report credential presence only; no network calls or secret values."""
    emit({"credentials_present": credential_status(), "network_calls": 0})


@app.command("cmto-pack")
def cmto_pack(
    subject: Path = Path("subjects/cmto_consent_boundaries_v1.json"),
    artifacts: Path = Path("source-artifacts/cmto-2026-09-20"),
    output: Path | None = None,
) -> None:
    """Verify and extract local authority; optional output is a local review artifact."""
    try:
        pack = load_pack(subject, artifacts)
        if output is not None:
            with output.open("x") as stream:
                stream.write(canonical(pack) + "\n")
        emit(
            {
                "pack_hash": pack["pack_hash"],
                "review_status": pack["review_status"],
                "requirements": {
                    key: len(value["requirements"]) for key, value in pack["articles"].items()
                },
                "output": str(output) if output else None,
                "network_calls": 0,
            }
        )
    except (ValueError, OSError, KeyError) as exc:
        raise typer.BadParameter(str(exc)) from exc


@app.command("cmto-run")
def cmto_run(
    max_estimated_usd: Annotated[str, typer.Option("--max-estimated-usd")],
    llm: str = "openai",
    model: str | None = None,
    generator: str = "anthropic",
    generator_model: str = "claude-opus-5",
    subject: Path = Path("subjects/cmto_consent_boundaries_v1.json"),
    artifacts: Path = Path("source-artifacts/cmto-2026-09-20"),
    reviewed_pack_hash: str | None = None,
    max_calls: int = 56,
    threshold: float = 0.9,
    generation_timeout_seconds: float = 120,
    db: Database = Path("runs/cmto.sqlite"),
    execute: bool = False,
) -> None:
    """Preview development collection. Execution needs explicit spend and reviewed pack hash."""
    try:
        pack = load_pack(subject, artifacts)
        selected = model or (
            "claude-opus-5" if llm == "anthropic" else os.environ.get("OPENAI_MODEL", "")
        )
        config = LiveConfig.model_validate(
            {
                "provider": llm,
                "model": selected,
                "max_output_tokens": 4096,
            }
        )
        manifest = make_manifest(
            pack,
            config,
            Decimal(max_estimated_usd),
            max_calls=max_calls,
            threshold=threshold,
            generation_timeout_seconds=generation_timeout_seconds,
            generator=LiveConfig.model_validate(
                {
                    "provider": generator,
                    "model": generator_model,
                    "max_output_tokens": 4096,
                }
            ),
        )
        if not execute:
            emit(
                {
                    "mode": manifest.mode,
                    "pack_hash": pack["pack_hash"],
                    "manifest_hash": digest(manifest.model_dump(mode="json")),
                    "generator": generator_model,
                    "llm_reviewer": selected,
                    "jev": "jev-1.13.0",
                    "items": 20,
                    "maximum_calls": max_calls,
                    "generation_timeout_seconds": generation_timeout_seconds,
                    "estimated_spend_guard_usd": max_estimated_usd,
                    "network_calls": 0,
                    "threshold_status": "provisional_not_calibrated",
                    "execution_requires": "--execute and --reviewed-pack-hash matching this pack",
                    "warning": "Development only; spend admission estimates are not billed caps.",
                }
            )
            return
        if reviewed_pack_hash != pack["pack_hash"]:
            raise ValueError(
                "review the cmto-pack output and supply its exact --reviewed-pack-hash"
            )
        with httpx.Client(trust_env=False, follow_redirects=False) as client, Store(db) as store:
            run_id = execute_cmto(store, manifest, client)
            emit(project(store.events(run_id)))
    except (ValueError, OSError, KeyError, InvalidOperation) as exc:
        raise typer.BadParameter(str(exc)) from exc


@app.command("cmto-validate")
def cmto_validate(
    run_id: RunID,
    max_estimated_usd: Annotated[str, typer.Option("--max-estimated-usd")],
    db: Database = Path("runs/cmto.sqlite"),
    output: Path | None = None,
    reviewed_manifest_hash: str | None = None,
    execute: bool = False,
) -> None:
    """Freeze/preview a fresh validation batch; explicit hash and spend gate for execution."""
    from content_eval.validation import reject_existing_validation, validation_manifest

    try:
        with Store(db, read_only=True) as store:
            manifest = validation_manifest(store, run_id, Decimal(max_estimated_usd))
            reject_existing_validation(store, run_id)
        data = manifest.model_dump(mode="json")
        fingerprint = digest(data)
        if execute:
            if output is not None:
                raise ValueError("--output is for preview/freeze only")
            if reviewed_manifest_hash != fingerprint:
                raise ValueError("review the frozen plan and provide its --reviewed-manifest-hash")
            with (
                Store(db) as store,
                httpx.Client(trust_env=False, follow_redirects=False) as client,
            ):
                child = execute_cmto(store, manifest, client)
                emit(project(store.events(child)))
            return
        if output is not None:
            with output.open("x") as stream:
                stream.write(canonical({"manifest_hash": fingerprint, "manifest": data}) + "\n")
        emit(
            {
                "mode": "prospective_validation_preview",
                "manifest_hash": fingerprint,
                "policy": manifest.policy.model_dump(mode="json"),
                "generator": manifest.provider_config["generator"],
                "reviewer": manifest.provider_config["llm"],
                "maximum_calls": manifest.provider_config["max_calls"],
                "estimated_spend_guard_usd": max_estimated_usd,
                "items": 20,
                "reused_candidates": 0,
                "network_calls": 0,
                "frozen_plan": str(output) if output else None,
                "execution_requires": "--execute and --reviewed-manifest-hash matching this plan",
                "warning": "Not a billed cap. Fresh human review and cross-pool overlap review "
                "are required; zero unresolved is not guaranteed for provider failures.",
            }
        )
    except (ValueError, OSError, KeyError, InvalidOperation) as exc:
        raise typer.BadParameter(str(exc)) from exc


@app.command("cmto-continue")
def cmto_continue(
    run_id: RunID,
    max_estimated_usd: Annotated[str, typer.Option("--max-estimated-usd")],
    max_calls: Annotated[int, typer.Option("--max-calls")],
    generation_timeout_seconds: float = 120,
    acknowledge_uncertain_attempts: bool = False,
    unknown_cost_reserve_usd: str = "0",
    db: Database = Path("runs/cmto.sqlite"),
    execute: bool = False,
) -> None:
    """Preview a linked generation continuation; explicit execution may incur new charges."""
    try:
        with Store(db, read_only=True) as store:
            manifest = continuation_manifest(
                store,
                run_id,
                max_estimated_usd=Decimal(max_estimated_usd),
                max_calls=max_calls,
                generation_timeout_seconds=generation_timeout_seconds,
                acknowledge_uncertain_attempts=acknowledge_uncertain_attempts,
                unknown_cost_reserve_usd=Decimal(unknown_cost_reserve_usd),
            )
        carry = manifest.provider_config["continuation"]
        assert isinstance(carry, dict)
        prepared = carry["prepared"]
        assert isinstance(prepared, list)
        # Paraphrases are paid too; defect variants are not.
        assignments = manifest.provider_config["slots"]
        assert isinstance(assignments, list)
        reused_ids = {item["id"] for item in prepared if isinstance(item, dict)}
        reused_paid = sum(
            isinstance(slot, dict) and slot["id"] in reused_ids and slot["kind"] != "defect"
            for slot in assignments
        )
        if not execute:
            emit(
                {
                    "parent_run_id": run_id,
                    "network_calls": 0,
                    "reused_candidates": len(prepared),
                    "prior_calls": carry["prior_calls"],
                    "prior_known_cost_usd": carry["prior_known_cost_usd"],
                    "prior_unknown_attempts": carry["prior_unknown_attempts"],
                    "unknown_cost_reserve_usd": carry["unknown_cost_reserve_usd"],
                    "maximum_additional_calls_needed": 56 - reused_paid,
                    "total_call_cap": max_calls,
                    "total_estimated_spend_guard_usd": max_estimated_usd,
                    "generation_timeout_seconds": generation_timeout_seconds,
                    "manifest_hash": digest(manifest.model_dump(mode="json")),
                    "execution_requires": "--execute; uncertain calls also require "
                    "--acknowledge-uncertain-attempts and a positive --unknown-cost-reserve-usd",
                    "warning": "Retries may duplicate billed calls; reserves are not charges.",
                }
            )
            return
        with Store(db) as store, httpx.Client(trust_env=False, follow_redirects=False) as client:
            child_id = execute_cmto(store, manifest, client)
            emit(project(store.events(child_id)))
    except (ValueError, OSError, KeyError, InvalidOperation) as exc:
        raise typer.BadParameter(str(exc)) from exc


@app.command("cmto-reevaluate")
def cmto_reevaluate(
    run_id: RunID,
    max_estimated_usd: Annotated[str, typer.Option("--max-estimated-usd")],
    model: str | None = None,
    db: Database = Path("runs/cmto.sqlite"),
    execute: bool = False,
) -> None:
    """Review the saved Opus pool using OpenAI and JEV; never regenerate inputs."""
    try:
        config = LiveConfig(
            provider="openai",
            model=model or os.environ.get("OPENAI_MODEL", ""),
            max_output_tokens=4096,
        )
        with Store(db, read_only=True) as store:
            manifest = reevaluation_manifest(store, run_id, config, Decimal(max_estimated_usd))
        if not execute:
            emit(
                {
                    "network_calls": 0,
                    "maximum_calls": 40,
                    "reused_candidates": 20,
                    "generator": manifest.provider_config["generator"],
                    "llm_reviewer": config.model,
                    "jev": "jev-1.13.0",
                    "generation_calls": 0,
                    "parent_run_id": run_id,
                    "manifest_hash": digest(manifest.model_dump(mode="json")),
                    "estimated_spend_guard_usd": max_estimated_usd,
                }
            )
            return
        with Store(db) as store, httpx.Client(trust_env=False, follow_redirects=False) as client:
            child = execute_cmto(store, manifest, client)
            emit(project(store.events(child)))
    except (ValueError, OSError, KeyError, InvalidOperation) as exc:
        raise typer.BadParameter(str(exc)) from exc


@app.command("export-audit")
def export_audit(
    run_id: RunID,
    output: Path,
    db: Database = Path("runs/cmto.sqlite"),
) -> None:
    """Export a blinded full-pool packet; never include arm outcomes or construction labels."""
    try:
        with Store(db) as store:
            packet = export_packet(store, run_id, output)
        emit({"packet_id": packet, "output": str(output), "network_calls": 0})
    except (ValueError, OSError) as exc:
        raise typer.BadParameter(str(exc)) from exc


@app.command("import-audit")
def import_audit(
    run_id: RunID,
    labels: Path,
    db: Database = Path("runs/cmto.sqlite"),
) -> None:
    """Append independent reference labels, preserving immutable candidates and prior labels."""
    try:
        with Store(db) as store:
            count = import_labels(store, run_id, labels)
            emit({"labels_imported": count, "report": project(store.events(run_id))})
    except (ValueError, OSError) as exc:
        raise typer.BadParameter(str(exc)) from exc


@app.command("analyze-policy")
def policy_analysis(
    run_id: RunID,
    db: Database = Path("runs/cmto.sqlite"),
    threshold: float | None = None,
    output: Path | None = None,
) -> None:
    """Offline filter-first counterfactual; preserves the journal and live policy."""
    try:
        with Store(db, read_only=True) as store:
            result = analyze_policy(store.events(run_id), threshold)
        if output is not None:
            with output.open("x") as stream:
                stream.write(canonical(result) + "\n")
        emit(result)
    except (ValueError, OSError, KeyError) as exc:
        raise typer.BadParameter(str(exc)) from exc


@app.command("compare")
def compare(run_id: RunID, db: Database = Path("runs/cmto.sqlite")) -> None:
    """Compact evaluator comparison; accuracy stays N/A until independent labels exist."""
    with Store(db, read_only=True) as store:
        report = project(store.events(run_id))
    typer.echo("Arm | Eval cost USD | Median ms | Accuracy | Labelled / pool | Unresolved")
    typer.echo("--- | ---: | ---: | ---: | ---: | ---:")
    for arm, stats in report["arms"].items():
        measured = stats.get("accuracy_details") or {}
        score = measured.get("accuracy")
        display = "N/A" if score is None else f"{score:.1%}"
        typer.echo(
            f"{stats.get('model') or arm} | {stats['estimated_cost_usd']} | "
            f"{stats['attempt_latency_p50_ms']} | "
            f"{display} | {measured.get('labelled_evaluated', 0)}/{measured.get('pool_size', 0)} | "
            f"{stats['unresolved']}"
        )
    typer.echo(
        "Accuracy requires independent human labels; abstentions earn no correctness credit."
    )
    typer.echo("Partial labels describe only the audited subset, not full-pool accuracy.")


def execute_live(manifest: Manifest, db: Path, run_id: str | None = None) -> None:
    expected = smoke_manifest(
        LiveConfig.model_validate(manifest.provider_config["llm"]), manifest.count
    )
    if expected != manifest:
        raise ValueError("live manifest does not match the current versioned smoke configuration")
    # Disable proxy inheritance and redirects to keep keys at the intended direct endpoints.
    with httpx.Client(trust_env=False, follow_redirects=False) as client:
        adapters: dict[Arm, Evaluator] = {
            "llm": LiveEvaluator(
                LiveConfig.model_validate(manifest.provider_config["llm"]), client
            ),
            "jev": LiveEvaluator(
                LiveConfig.model_validate(manifest.provider_config["jev"]), client
            ),
        }
        with Store(db) as store:
            completed = run(store, manifest, run_id, evaluators=adapters)
            emit(project(store.events(completed)))


@app.command("live-smoke")
def live_smoke(
    llm: str = "anthropic",
    model: str | None = None,
    count: int = 1,
    db: Database = Path("runs/live.sqlite"),
    execute: bool = False,
) -> None:
    """Preview a bounded live smoke run; --execute makes paid calls on toy inputs."""
    try:
        selected = model or (
            "claude-opus-5" if llm == "anthropic" else os.environ.get("OPENAI_MODEL", "")
        )
        config = LiveConfig.model_validate({"provider": llm, "model": selected})
        manifest = smoke_manifest(config, count)
        if not execute:
            emit(
                {
                    "manifest": manifest.model_dump(mode="json"),
                    "network_calls": 0,
                    "maximum_calls_if_executed": count * 2,
                }
            )
            return
        execute_live(manifest, db)
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from exc


@app.command("live-resume")
def live_resume(
    run_id: RunID,
    db: Database = Path("runs/live.sqlite"),
    execute: bool = False,
) -> None:
    """Inspect a live run; --execute resumes remaining work using current local keys."""
    with Store(db) as store:
        events = store.events(run_id)
        summary = project(events)
        manifest = Manifest.model_validate(events[0].payload["manifest"])
    if manifest.mode != "live-smoke":
        raise typer.BadParameter("use resume for a fake run")
    if not execute or summary["status"] == "completed":
        emit(summary)
        return
    try:
        execute_live(manifest, db, run_id)
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from exc


@app.command("runs")
def list_runs(db: Database = Path("runs/demo.sqlite")) -> None:
    """List run IDs and status, including interrupted runs that can be resumed."""
    if not db.is_file():
        raise typer.BadParameter("database does not exist")
    with Store(db) as store:
        ids = [row[0] for row in store.db.execute("SELECT DISTINCT run_id FROM events")]
        emit(
            [
                {"run_id": run_id, "status": project(store.events(run_id))["status"]}
                for run_id in ids
            ]
        )


@app.command()
def demo(
    db: Database = Path("runs/demo.sqlite"),
    count: int = 12,
    seed: int = 7,
    target: int = 5,
    failure_mode: str = "none",
    dry_run: bool = False,
) -> None:
    """Run both fake arms on synthetic fixtures, or inspect the manifest with --dry-run."""
    try:
        manifest = Manifest.model_validate(
            {
                "count": count,
                "seed": seed,
                "target": target,
                "failure_mode": failure_mode,
            }
        )
        if dry_run:
            emit(manifest.model_dump(mode="json"))
            return
        with Store(db) as store:
            run_id = run(store, manifest)
            emit(project(store.events(run_id)))
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from exc


@app.command()
def resume(run_id: RunID, db: Database = Path("runs/demo.sqlite")) -> None:
    """Resume persisted inputs/policy; completed runs are a no-op."""
    try:
        with Store(db) as store:
            run(store, run_id=run_id)
            emit(project(store.events(run_id)))
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from exc


@app.command()
def report(run_id: RunID, db: Database = Path("runs/demo.sqlite")) -> None:
    """Derive a report from the persisted journal."""
    try:
        with Store(db) as store:
            emit(project(store.events(run_id)))
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from exc


@app.command("export-events")
def export_events(run_id: RunID, output: Path, db: Database = Path("runs/demo.sqlite")) -> None:
    """Export a self-contained journal snapshot; refuse to overwrite an existing file."""
    with Store(db) as store, store.writer():
        events = store.events(run_id)
        project(events)
        data = "".join(e.model_dump_json() + "\n" for e in events)
        with output.open("x") as stream:
            stream.write(data)
        store.append(
            run_id,
            "export.completed",
            {
                "kind": "journal",
                "through_sequence": events[-1].sequence,
                "content_hash": digest(data),
            },
        )
        emit({"output": str(output), "events": len(events), "content_hash": digest(data)})


@app.command()
def replay(journal: Path) -> None:
    """Verify hashes/order and reconstruct the report without a database or providers."""
    try:
        events = [Event.model_validate_json(line) for line in journal.read_text().splitlines()]
        emit(project(events))
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from exc


@app.command("export-approval")
def export_approval(
    run_id: RunID,
    output: Path,
    arm: str = "llm",
    db: Database = Path("runs/demo.sqlite"),
) -> None:
    """Export selected unchanged demo items, explicitly NOT approved for use."""
    if arm not in {"llm", "jev"}:
        raise typer.BadParameter("arm must be llm or jev")
    with Store(db) as store, store.writer():
        events = store.events(run_id)
        summary = project(events)
        if summary["mode"] == "cmto-development":
            raise typer.BadParameter(
                "CMTO development items cannot be exported as an approval queue"
            )
        selected = summary["arms"][arm]["selected"]
        candidates = [
            e.payload["candidate"]
            for e in events
            if e.event_type == "candidate.generated" and e.candidate_id in selected
        ]
        payload = {
            "status": "demo_only_not_approved",
            "run_id": run_id,
            "arm": arm,
            "candidates": candidates,
        }
        data = canonical(payload)
        with output.open("x") as stream:
            stream.write(data + "\n")
        store.append(
            run_id,
            "export.completed",
            {
                "kind": "approval",
                "content_hash": digest(data),
                "count": len(candidates),
            },
        )
        emit({"output": str(output), "count": len(candidates)})


if __name__ == "__main__":
    app()
