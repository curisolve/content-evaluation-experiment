"""JSON-first commands; fake demo never accesses the network."""

import json
from pathlib import Path
from typing import Annotated

import typer

from content_eval.models import Event, Manifest, canonical, digest
from content_eval.projection import project
from content_eval.storage import Store
from content_eval.workflow import run

app = typer.Typer(no_args_is_help=True, pretty_exceptions_enable=False)
Database = Annotated[Path, typer.Option("--db", help="SQLite journal path")]
RunID = Annotated[str, typer.Argument(help="Run identifier from demo output")]


def emit(value: object) -> None:
    typer.echo(json.dumps(value, indent=2, sort_keys=True))


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
