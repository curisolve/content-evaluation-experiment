"""Append-only event store. State is derived, so no state/event dual-write gap."""

import fcntl
import sqlite3
import time
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from pydantic import JsonValue

from content_eval.models import Arm, Event, EventType, digest


class Store:
    def __init__(self, path: Path, *, read_only: bool = False) -> None:
        self.read_only = read_only
        if not read_only:
            path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        self.session_id = str(uuid4())
        self.started = time.monotonic_ns()
        if read_only:
            self.db = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)
            return
        self.db = sqlite3.connect(path, timeout=10)
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA synchronous=FULL")
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS events (
                run_id TEXT NOT NULL, sequence INTEGER NOT NULL,
                event_id TEXT NOT NULL UNIQUE, body TEXT NOT NULL,
                PRIMARY KEY (run_id, sequence)
            );
            CREATE TRIGGER IF NOT EXISTS no_event_update BEFORE UPDATE ON events
            BEGIN SELECT RAISE(ABORT, 'events are immutable'); END;
            CREATE TRIGGER IF NOT EXISTS no_event_delete BEFORE DELETE ON events
            BEGIN SELECT RAISE(ABORT, 'events are immutable'); END;
        """)

    def close(self) -> None:
        self.db.close()

    def __enter__(self) -> Store:
        return self

    def __exit__(self, *args: object) -> None:
        self.close()

    @contextmanager
    def writer(self) -> Iterator[None]:
        if self.read_only:
            raise ValueError("read-only store cannot acquire a writer")
        # Keep one coordinator per database, including across processes.
        with self.path.with_suffix(self.path.suffix + ".lock").open("a") as lock:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                raise ValueError("another coordinator is using this database") from exc
            try:
                yield
            finally:
                fcntl.flock(lock, fcntl.LOCK_UN)

    def events(self, run_id: str) -> list[Event]:
        return [
            Event.model_validate_json(row[0])
            for row in self.db.execute(
                "SELECT body FROM events WHERE run_id=? ORDER BY sequence",
                (run_id,),
            )
        ]

    def append(
        self,
        run_id: str,
        event_type: EventType,
        payload: dict[str, JsonValue],
        *,
        arm: Arm | None = None,
        candidate_id: str | None = None,
        operation_id: str | None = None,
        attempt_id: str | None = None,
    ) -> Event:
        self.db.execute("BEGIN IMMEDIATE")
        try:
            row = self.db.execute(
                "SELECT body FROM events WHERE run_id=? ORDER BY sequence DESC LIMIT 1",
                (run_id,),
            ).fetchone()
            previous = Event.model_validate_json(row[0]) if row else None
            now = datetime.now(UTC).isoformat()
            event = Event(
                event_id=str(uuid4()),
                run_id=run_id,
                sequence=previous.sequence + 1 if previous else 1,
                event_type=event_type,
                occurred_at=now,
                persisted_at=now,
                session_id=self.session_id,
                elapsed_ns=time.monotonic_ns() - self.started,
                arm=arm,
                candidate_id=candidate_id,
                operation_id=operation_id,
                attempt_id=attempt_id,
                payload=payload,
                previous_hash=previous.event_hash if previous else "",
                event_hash="",
            )
            event = event.model_copy(
                update={
                    "event_hash": digest(event.model_dump(mode="json", exclude={"event_hash"})),
                }
            )
            self.db.execute(
                "INSERT INTO events VALUES (?, ?, ?, ?)",
                (
                    run_id,
                    event.sequence,
                    event.event_id,
                    event.model_dump_json(),
                ),
            )
            self.db.commit()
            return event
        except BaseException:
            self.db.rollback()
            raise
