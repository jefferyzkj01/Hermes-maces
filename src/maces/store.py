from __future__ import annotations

import json
import math
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Iterator

from .models import CognitiveEvent, LearningProposal, PromotionProposal, StagedArtifact, utc_now
from .policy import MacesPolicy

ACTIVE_PROPOSAL_STATUSES = ("proposed", "approved", "running", "staged")

SCHEMA = """
PRAGMA journal_mode=WAL;
CREATE TABLE IF NOT EXISTS events(
 event_id TEXT PRIMARY KEY, kind TEXT NOT NULL, source TEXT NOT NULL,
 subject TEXT, confidence REAL NOT NULL, payload_json TEXT NOT NULL, occurred_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS patterns(
 pattern_key TEXT PRIMARY KEY, label TEXT NOT NULL, weight REAL NOT NULL,
 evidence_count INTEGER NOT NULL, last_event_id TEXT NOT NULL, last_seen TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS edges(
 key_a TEXT NOT NULL, key_b TEXT NOT NULL, weight REAL NOT NULL,
 evidence_count INTEGER NOT NULL, last_seen TEXT NOT NULL,
 PRIMARY KEY(key_a,key_b));
CREATE TABLE IF NOT EXISTS gaps(
 gap_key TEXT PRIMARY KEY, topic TEXT NOT NULL, kind TEXT NOT NULL,
 reason TEXT NOT NULL, priority REAL NOT NULL, evidence_count INTEGER NOT NULL,
 status TEXT NOT NULL, last_triggered TEXT, updated_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS learning_proposals(
 proposal_id TEXT PRIMARY KEY, digest TEXT UNIQUE NOT NULL, topic TEXT NOT NULL,
 reason TEXT NOT NULL, priority REAL NOT NULL, required_sources_json TEXT NOT NULL,
 gap_key TEXT NOT NULL, status TEXT NOT NULL, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS staged_artifacts(
 artifact_id TEXT PRIMARY KEY, proposal_id TEXT NOT NULL, title TEXT NOT NULL,
 content TEXT NOT NULL, sources_json TEXT NOT NULL, confidence REAL NOT NULL, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS promotion_proposals(
 proposal_id TEXT PRIMARY KEY, digest TEXT UNIQUE NOT NULL, artifact_id TEXT NOT NULL,
 target_path TEXT NOT NULL, operation TEXT NOT NULL, status TEXT NOT NULL, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS journal(
 seq INTEGER PRIMARY KEY AUTOINCREMENT, event_type TEXT NOT NULL,
 entity_id TEXT, payload_json TEXT NOT NULL, created_at TEXT NOT NULL);
"""


class CognitiveStore:
    def __init__(self, path: str | Path) -> None:
        self.path = str(path)
        with self.connect() as db:
            db.executescript(SCHEMA)
            self._migrate_learning_proposals(db)

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        db = sqlite3.connect(self.path)
        db.row_factory = sqlite3.Row
        try:
            yield db
            db.commit()
        finally:
            db.close()

    def _migrate_learning_proposals(self, db: sqlite3.Connection) -> None:
        """Collapse legacy active duplicates before enforcing gap identity.

        Releases before v1.0.2 relied on a digest whose inputs changed over time.
        Existing databases can therefore contain multiple active proposals for one
        gap. Keep the most advanced proposal, repoint staged artifacts, remove the
        redundant active rows, and then add a partial unique index.
        """
        placeholders = ",".join("?" for _ in ACTIVE_PROPOSAL_STATUSES)
        duplicate_gaps = db.execute(
            f"""SELECT gap_key FROM learning_proposals
                WHERE status IN ({placeholders})
                GROUP BY gap_key HAVING COUNT(*) > 1""",
            ACTIVE_PROPOSAL_STATUSES,
        ).fetchall()

        status_rank = """CASE status
            WHEN 'staged' THEN 4
            WHEN 'running' THEN 3
            WHEN 'approved' THEN 2
            WHEN 'proposed' THEN 1
            ELSE 0 END"""
        for duplicate in duplicate_gaps:
            rows = db.execute(
                f"""SELECT proposal_id FROM learning_proposals
                    WHERE gap_key=? AND status IN ({placeholders})
                    ORDER BY {status_rank} DESC, priority DESC, created_at ASC, proposal_id ASC""",
                (duplicate["gap_key"], *ACTIVE_PROPOSAL_STATUSES),
            ).fetchall()
            survivor = rows[0]["proposal_id"]
            redundant = [row["proposal_id"] for row in rows[1:]]
            if not redundant:
                continue
            redundant_placeholders = ",".join("?" for _ in redundant)
            db.execute(
                f"UPDATE staged_artifacts SET proposal_id=? WHERE proposal_id IN ({redundant_placeholders})",
                (survivor, *redundant),
            )
            db.execute(
                f"DELETE FROM learning_proposals WHERE proposal_id IN ({redundant_placeholders})",
                redundant,
            )

        db.execute(
            """CREATE UNIQUE INDEX IF NOT EXISTS uq_active_learning_gap
               ON learning_proposals(gap_key)
               WHERE status IN ('proposed','approved','running','staged')"""
        )

    def journal(self, event_type: str, entity_id: str | None, payload: dict[str, Any]) -> None:
        with self.connect() as db:
            db.execute(
                "INSERT INTO journal(event_type,entity_id,payload_json,created_at) VALUES(?,?,?,?)",
                (event_type, entity_id, json.dumps(payload, sort_keys=True), utc_now()),
            )

    def save_event(self, event: CognitiveEvent) -> bool:
        with self.connect() as db:
            cur = db.execute(
                "INSERT OR IGNORE INTO events VALUES(?,?,?,?,?,?,?)",
                (
                    event.event_id,
                    event.kind,
                    event.source,
                    event.subject,
                    event.confidence,
                    json.dumps(event.payload, sort_keys=True),
                    event.occurred_at,
                ),
            )
            created = cur.rowcount == 1
        if created:
            self.journal("event.observed", event.event_id, {"kind": event.kind})
        return created

    def pattern(self, key: str) -> dict[str, Any] | None:
        with self.connect() as db:
            row = db.execute("SELECT * FROM patterns WHERE pattern_key=?", (key,)).fetchone()
        return dict(row) if row else None

    def put_pattern(self, key: str, label: str, weight: float, event_id: str, seen: str) -> None:
        with self.connect() as db:
            db.execute(
                """INSERT INTO patterns VALUES(?,?,?,?,?,?) ON CONFLICT(pattern_key) DO UPDATE SET
                label=excluded.label,weight=excluded.weight,evidence_count=patterns.evidence_count+1,
                last_event_id=excluded.last_event_id,last_seen=excluded.last_seen""",
                (key, label, max(0.0, min(1.0, weight)), 1, event_id, seen),
            )

    def edge(self, a: str, b: str) -> dict[str, Any] | None:
        a, b = sorted((a, b))
        with self.connect() as db:
            row = db.execute("SELECT * FROM edges WHERE key_a=? AND key_b=?", (a, b)).fetchone()
        return dict(row) if row else None

    def put_edge(self, a: str, b: str, weight: float, seen: str) -> None:
        if a == b:
            return
        a, b = sorted((a, b))
        with self.connect() as db:
            db.execute(
                """INSERT INTO edges VALUES(?,?,?,?,?) ON CONFLICT(key_a,key_b) DO UPDATE SET
                weight=excluded.weight,evidence_count=edges.evidence_count+1,last_seen=excluded.last_seen""",
                (a, b, max(0.0, min(1.0, weight)), 1, seen),
            )

    def normalize_edges(self, cap: float) -> None:
        with self.connect() as db:
            nodes = [row[0] for row in db.execute("SELECT pattern_key FROM patterns")]
            for node in nodes:
                rows = db.execute(
                    "SELECT key_a,key_b,weight FROM edges WHERE key_a=? OR key_b=?", (node, node)
                ).fetchall()
                total = sum(float(row[2]) for row in rows)
                if total <= cap or not rows:
                    continue
                scale = cap / total
                for a, b, weight in rows:
                    db.execute(
                        "UPDATE edges SET weight=? WHERE key_a=? AND key_b=?",
                        (float(weight) * scale, a, b),
                    )

    def upsert_gap(self, key: str, topic: str, kind: str, reason: str, priority: float) -> None:
        now = utc_now()
        with self.connect() as db:
            db.execute(
                """INSERT INTO gaps VALUES(?,?,?,?,?,?,?,?,?) ON CONFLICT(gap_key) DO UPDATE SET
                priority=MAX(gaps.priority,excluded.priority),evidence_count=gaps.evidence_count+1,
                reason=excluded.reason,kind=excluded.kind,updated_at=excluded.updated_at""",
                (key, topic, kind, reason, priority, 1, "open", None, now),
            )

    def decay(self, policy: MacesPolicy, now: str | None = None) -> dict[str, int]:
        current = datetime.fromisoformat(now or utc_now())
        changed = pruned = 0
        with self.connect() as db:
            for table, keycols in (("patterns", ("pattern_key",)), ("edges", ("key_a", "key_b"))):
                for row in db.execute(f"SELECT * FROM {table}").fetchall():
                    days = max(
                        0.0,
                        (current - datetime.fromisoformat(row["last_seen"])).total_seconds() / 86400,
                    )
                    weight = float(row["weight"]) * math.exp(-days / policy.decay_tau_days)
                    where = " AND ".join(f"{key}=?" for key in keycols)
                    values = tuple(row[key] for key in keycols)
                    if weight < policy.weight_floor:
                        db.execute(f"DELETE FROM {table} WHERE {where}", values)
                        pruned += 1
                    else:
                        db.execute(
                            f"UPDATE {table} SET weight=?,last_seen=? WHERE {where}",
                            (weight, current.isoformat(), *values),
                        )
                        changed += 1
        self.journal("consolidation.decay", None, {"changed": changed, "pruned": pruned})
        return {"changed": changed, "pruned": pruned}

    def create_learning_proposal(self, proposal: LearningProposal) -> bool:
        placeholders = ",".join("?" for _ in ACTIVE_PROPOSAL_STATUSES)
        try:
            with self.connect() as db:
                existing = db.execute(
                    f"""SELECT 1 FROM learning_proposals
                        WHERE gap_key=? AND status IN ({placeholders}) LIMIT 1""",
                    (proposal.gap_key, *ACTIVE_PROPOSAL_STATUSES),
                ).fetchone()
                if existing:
                    return False
                db.execute(
                    "INSERT INTO learning_proposals VALUES(?,?,?,?,?,?,?,?,?)",
                    (
                        proposal.proposal_id,
                        proposal.digest,
                        proposal.topic,
                        proposal.reason,
                        proposal.priority,
                        json.dumps(proposal.required_sources),
                        proposal.gap_key,
                        proposal.status.value,
                        proposal.created_at,
                    ),
                )
            return True
        except sqlite3.IntegrityError:
            return False

    def stage(self, artifact: StagedArtifact) -> None:
        with self.connect() as db:
            db.execute(
                "INSERT INTO staged_artifacts VALUES(?,?,?,?,?,?,?)",
                (
                    artifact.artifact_id,
                    artifact.proposal_id,
                    artifact.title,
                    artifact.content,
                    json.dumps(artifact.sources),
                    artifact.confidence,
                    artifact.created_at,
                ),
            )
        self.journal("artifact.staged", artifact.artifact_id, {"proposal_id": artifact.proposal_id})

    def create_promotion(self, proposal: PromotionProposal) -> None:
        with self.connect() as db:
            db.execute(
                "INSERT INTO promotion_proposals VALUES(?,?,?,?,?,?,?)",
                (
                    proposal.proposal_id,
                    proposal.digest,
                    proposal.artifact_id,
                    proposal.target_path,
                    proposal.operation,
                    "proposed",
                    proposal.created_at,
                ),
            )

    def list_table(self, table: str) -> list[dict[str, Any]]:
        allowed = {
            "events",
            "patterns",
            "edges",
            "gaps",
            "learning_proposals",
            "staged_artifacts",
            "promotion_proposals",
            "journal",
        }
        if table not in allowed:
            raise ValueError(f"unsupported table: {table}")
        with self.connect() as db:
            rows = db.execute(f"SELECT * FROM {table}").fetchall()
        return [dict(row) for row in rows]
