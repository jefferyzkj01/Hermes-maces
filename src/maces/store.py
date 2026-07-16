from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from .models import CognitiveEvent, LearningProposal, PromotionProposal, StagedArtifact, utc_now


SCHEMA = """
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;
CREATE TABLE IF NOT EXISTS events(
  event_id TEXT PRIMARY KEY, kind TEXT NOT NULL, source TEXT NOT NULL,
  subject TEXT, confidence REAL NOT NULL, authority TEXT NOT NULL,
  payload_json TEXT NOT NULL, occurred_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS patterns(
  pattern_key TEXT PRIMARY KEY, label TEXT NOT NULL, weight REAL NOT NULL,
  evidence_count INTEGER NOT NULL, last_event_id TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS gaps(
  gap_key TEXT PRIMARY KEY, topic TEXT NOT NULL, reason TEXT NOT NULL,
  priority REAL NOT NULL, evidence_count INTEGER NOT NULL, status TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS learning_proposals(
  proposal_id TEXT PRIMARY KEY, digest TEXT NOT NULL UNIQUE, topic TEXT NOT NULL,
  reason TEXT NOT NULL, priority REAL NOT NULL, required_sources_json TEXT NOT NULL,
  gap_key TEXT NOT NULL, status TEXT NOT NULL, created_at TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS uq_active_learning_gap
ON learning_proposals(gap_key) WHERE status IN ('proposed','approved','running','staged');
CREATE TABLE IF NOT EXISTS staged_artifacts(
  artifact_id TEXT PRIMARY KEY, proposal_id TEXT NOT NULL, title TEXT NOT NULL,
  content TEXT NOT NULL, sources_json TEXT NOT NULL, confidence REAL NOT NULL,
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS promotion_proposals(
  proposal_id TEXT PRIMARY KEY, digest TEXT NOT NULL UNIQUE, artifact_id TEXT NOT NULL,
  target_provider TEXT NOT NULL, target_path TEXT NOT NULL, operation TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'proposed', created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS journal(
  seq INTEGER PRIMARY KEY AUTOINCREMENT, event_type TEXT NOT NULL,
  entity_id TEXT, payload_json TEXT NOT NULL, created_at TEXT NOT NULL
);
"""


class CognitiveStore:
    def __init__(self, path: str | Path) -> None:
        self.path = str(path)
        with self.connect() as db:
            db.executescript(SCHEMA)

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        db = sqlite3.connect(self.path)
        db.row_factory = sqlite3.Row
        try:
            yield db
            db.commit()
        finally:
            db.close()

    def append_journal(self, event_type: str, entity_id: str | None, payload: dict[str, Any]) -> None:
        with self.connect() as db:
            db.execute(
                "INSERT INTO journal(event_type,entity_id,payload_json,created_at) VALUES(?,?,?,?)",
                (event_type, entity_id, json.dumps(payload, sort_keys=True), utc_now()),
            )

    def save_event(self, event: CognitiveEvent) -> bool:
        with self.connect() as db:
            cur = db.execute(
                "INSERT OR IGNORE INTO events VALUES(?,?,?,?,?,?,?,?)",
                (event.event_id, event.kind, event.source, event.subject, event.confidence,
                 event.authority, json.dumps(event.payload, sort_keys=True), event.occurred_at),
            )
            created = cur.rowcount == 1
        if created:
            self.append_journal("event.observed", event.event_id, {"kind": event.kind})
        return created

    def upsert_pattern(self, key: str, label: str, delta: float, event_id: str) -> None:
        with self.connect() as db:
            db.execute(
                """INSERT INTO patterns VALUES(?,?,?,?,?,?)
                ON CONFLICT(pattern_key) DO UPDATE SET
                weight=MIN(1.0,patterns.weight+excluded.weight),
                evidence_count=patterns.evidence_count+1,
                last_event_id=excluded.last_event_id,updated_at=excluded.updated_at""",
                (key, label, delta, 1, event_id, utc_now()),
            )

    def upsert_gap(self, key: str, topic: str, reason: str, priority: float) -> None:
        with self.connect() as db:
            db.execute(
                """INSERT INTO gaps VALUES(?,?,?,?,?,?,?)
                ON CONFLICT(gap_key) DO UPDATE SET
                priority=MAX(gaps.priority,excluded.priority),
                evidence_count=gaps.evidence_count+1,reason=excluded.reason,updated_at=excluded.updated_at""",
                (key, topic, reason, priority, 1, "open", utc_now()),
            )

    def create_learning_proposal(self, proposal: LearningProposal) -> bool:
        try:
            with self.connect() as db:
                db.execute(
                    "INSERT INTO learning_proposals VALUES(?,?,?,?,?,?,?,?,?)",
                    (proposal.proposal_id, proposal.digest, proposal.topic, proposal.reason,
                     proposal.priority, json.dumps(proposal.required_sources), proposal.gap_key,
                     proposal.status.value, proposal.created_at),
                )
            self.append_journal("learning.proposed", proposal.proposal_id, {"topic": proposal.topic})
            return True
        except sqlite3.IntegrityError:
            return False

    def set_learning_status(self, proposal_id: str, status: str) -> None:
        with self.connect() as db:
            cur = db.execute("UPDATE learning_proposals SET status=? WHERE proposal_id=?", (status, proposal_id))
            if cur.rowcount != 1:
                raise KeyError(proposal_id)
        self.append_journal("learning.status", proposal_id, {"status": status})

    def get_learning(self, proposal_id: str) -> dict[str, Any]:
        with self.connect() as db:
            row = db.execute("SELECT * FROM learning_proposals WHERE proposal_id=?", (proposal_id,)).fetchone()
        if row is None:
            raise KeyError(proposal_id)
        return dict(row)

    def stage(self, artifact: StagedArtifact) -> None:
        with self.connect() as db:
            db.execute(
                "INSERT INTO staged_artifacts VALUES(?,?,?,?,?,?,?)",
                (artifact.artifact_id, artifact.proposal_id, artifact.title, artifact.content,
                 json.dumps(artifact.sources, sort_keys=True), artifact.confidence, artifact.created_at),
            )
        self.set_learning_status(artifact.proposal_id, "staged")
        self.append_journal("artifact.staged", artifact.artifact_id, {"proposal_id": artifact.proposal_id})

    def create_promotion(self, proposal: PromotionProposal) -> None:
        with self.connect() as db:
            db.execute(
                "INSERT INTO promotion_proposals VALUES(?,?,?,?,?,?,?,?)",
                (proposal.proposal_id, proposal.digest, proposal.artifact_id, proposal.target_provider,
                 proposal.target_path, proposal.operation, "proposed", proposal.created_at),
            )
        self.append_journal("promotion.proposed", proposal.proposal_id, {"digest": proposal.digest})

    def list_table(self, table: str) -> list[dict[str, Any]]:
        allowed = {"events", "patterns", "gaps", "learning_proposals", "staged_artifacts", "promotion_proposals", "journal"}
        if table not in allowed:
            raise ValueError(f"unsupported table: {table}")
        with self.connect() as db:
            rows = db.execute(f"SELECT * FROM {table}").fetchall()
        return [dict(row) for row in rows]
