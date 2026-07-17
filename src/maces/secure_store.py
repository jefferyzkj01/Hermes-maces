from __future__ import annotations

import json
import math
import sqlite3
import threading
import time
from contextlib import contextmanager
from dataclasses import replace
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path, PurePosixPath
from typing import Any, Callable, Iterator, TypeVar
from uuid import uuid4

from .models import CognitiveEvent, LearningProposal, PromotionProposal, StagedArtifact, utc_now
from .policy import MacesPolicy
from .validation import is_valid_pattern_label, reject_sensitive_candidate, scrub_text, scrub_value

T = TypeVar("T")
ACTIVE_PROPOSAL_STATUSES = ("proposed", "approved", "running", "staged")

SCHEMA = """
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;
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
CREATE TABLE IF NOT EXISTS candidates(
 candidate_key TEXT PRIMARY KEY, label TEXT NOT NULL, occurrences INTEGER NOT NULL,
 distinct_sessions INTEGER NOT NULL, status TEXT NOT NULL,
 first_seen TEXT NOT NULL, last_seen TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS candidate_sessions(
 candidate_key TEXT NOT NULL, session_key TEXT NOT NULL, first_seen TEXT NOT NULL,
 PRIMARY KEY(candidate_key,session_key),
 FOREIGN KEY(candidate_key) REFERENCES candidates(candidate_key) ON DELETE CASCADE);
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
CREATE TABLE IF NOT EXISTS metadata(key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS idx_patterns_weight ON patterns(weight DESC,last_seen DESC);
CREATE INDEX IF NOT EXISTS idx_edges_a_weight ON edges(key_a,weight DESC);
CREATE INDEX IF NOT EXISTS idx_edges_b_weight ON edges(key_b,weight DESC);
CREATE INDEX IF NOT EXISTS idx_candidates_status_sessions
 ON candidates(status,distinct_sessions DESC,last_seen DESC);
CREATE INDEX IF NOT EXISTS idx_gaps_status_priority ON gaps(status,priority DESC,updated_at DESC);
"""


def _json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def _key(value: str) -> str:
    return sha256(value.strip().lower().encode()).hexdigest()[:24]


def _is_internal_key(value: str) -> bool:
    return len(value) == 24 and all(ch in "0123456789abcdef" for ch in value)


def _dt(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def _safe_identifier(value: object, prefix: str) -> tuple[str, int]:
    cleaned, scrubbed = scrub_text(value)
    valid = bool(cleaned) and len(cleaned) <= 128 and all(
        ch.isalnum() or ch in "-_.:" for ch in cleaned
    )
    if scrubbed or not valid:
        return f"{prefix}-{uuid4()}", scrubbed + 1
    return cleaned, scrubbed


def _safe_timestamp(value: object) -> tuple[str, int]:
    cleaned, scrubbed = scrub_text(value)
    try:
        return _dt(cleaned).isoformat(), scrubbed
    except (TypeError, ValueError):
        return utc_now(), scrubbed + 1


class CognitiveStore:
    """The only persistence boundary for MACES.

    Connections yield once. Lock retries wrap an entire transaction and create a
    fresh SQLite connection on every attempt.
    """

    def __init__(
        self,
        path: str | Path,
        policy: MacesPolicy | None = None,
        *,
        busy_timeout_ms: int = 5_000,
        max_retries: int = 3,
    ) -> None:
        self.path = str(Path(path))
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self.policy = policy or MacesPolicy()
        self.busy_timeout_ms = max(100, min(int(busy_timeout_ms), 30_000))
        self.max_retries = max(1, min(int(max_retries), 8))
        self._lock = threading.RLock()
        self._write(self._initialize)

    def configure(self, policy: MacesPolicy) -> None:
        with self._lock:
            self.policy = policy

    def _connection(self) -> sqlite3.Connection:
        db = sqlite3.connect(
            self.path,
            timeout=self.busy_timeout_ms / 1000,
            check_same_thread=False,
        )
        db.row_factory = sqlite3.Row
        db.execute(f"PRAGMA busy_timeout={self.busy_timeout_ms}")
        db.execute("PRAGMA foreign_keys=ON")
        return db

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        """Compatibility context manager: exactly one connection and one yield."""

        with self._lock:
            db = self._connection()
            try:
                yield db
                db.commit()
            except Exception:
                db.rollback()
                raise
            finally:
                db.close()

    def _transaction(self, fn: Callable[[sqlite3.Connection], T], *, write: bool) -> T:
        last_error: sqlite3.OperationalError | None = None
        for attempt in range(self.max_retries):
            try:
                with self._lock:
                    db = self._connection()
                    try:
                        db.execute("BEGIN IMMEDIATE" if write else "BEGIN")
                        result = fn(db)
                        db.commit()
                        return result
                    except Exception:
                        db.rollback()
                        raise
                    finally:
                        db.close()
            except sqlite3.OperationalError as exc:
                last_error = exc
                locked = "locked" in str(exc).lower() or "busy" in str(exc).lower()
                if not locked or attempt + 1 >= self.max_retries:
                    raise
                time.sleep(0.05 * (2**attempt))
        assert last_error is not None
        raise last_error

    def _write(self, fn: Callable[[sqlite3.Connection], T]) -> T:
        return self._transaction(fn, write=True)

    def _read(self, fn: Callable[[sqlite3.Connection], T]) -> T:
        return self._transaction(fn, write=False)

    def _initialize(self, db: sqlite3.Connection) -> None:
        db.executescript(SCHEMA)
        self._migrate_learning_proposals(db)

    def _migrate_learning_proposals(self, db: sqlite3.Connection) -> None:
        placeholders = ",".join("?" for _ in ACTIVE_PROPOSAL_STATUSES)
        duplicates = db.execute(
            f"""SELECT gap_key FROM learning_proposals
                WHERE status IN ({placeholders})
                GROUP BY gap_key HAVING COUNT(*) > 1""",
            ACTIVE_PROPOSAL_STATUSES,
        ).fetchall()
        rank = """CASE status WHEN 'staged' THEN 4 WHEN 'running' THEN 3
                  WHEN 'approved' THEN 2 WHEN 'proposed' THEN 1 ELSE 0 END"""
        for duplicate in duplicates:
            rows = db.execute(
                f"""SELECT proposal_id FROM learning_proposals
                    WHERE gap_key=? AND status IN ({placeholders})
                    ORDER BY {rank} DESC,priority DESC,created_at ASC,proposal_id ASC""",
                (duplicate["gap_key"], *ACTIVE_PROPOSAL_STATUSES),
            ).fetchall()
            survivor = str(rows[0]["proposal_id"])
            redundant = [str(row["proposal_id"]) for row in rows[1:]]
            if not redundant:
                continue
            marks = ",".join("?" for _ in redundant)
            db.execute(
                f"UPDATE staged_artifacts SET proposal_id=? WHERE proposal_id IN ({marks})",
                (survivor, *redundant),
            )
            db.execute(
                f"DELETE FROM learning_proposals WHERE proposal_id IN ({marks})",
                redundant,
            )
        db.execute(
            """CREATE UNIQUE INDEX IF NOT EXISTS uq_active_learning_gap
               ON learning_proposals(gap_key)
               WHERE status IN ('proposed','approved','running','staged')"""
        )

    @staticmethod
    def _journal_tx(
        db: sqlite3.Connection,
        event_type: str,
        entity_id: str | None,
        payload: dict[str, Any],
    ) -> None:
        db.execute(
            "INSERT INTO journal(event_type,entity_id,payload_json,created_at) VALUES(?,?,?,?)",
            (event_type, entity_id, _json(payload), utc_now()),
        )
        if event_type == "candidates.scrubbed":
            amount = max(0, int(payload.get("scrubbed_candidates", 0)))
            db.execute(
                """INSERT INTO metadata(key,value) VALUES('scrubbed_candidates_total',?)
                   ON CONFLICT(key) DO UPDATE SET
                     value=CAST(CAST(metadata.value AS INTEGER)+excluded.value AS TEXT)""",
                (str(amount),),
            )

    def journal(self, event_type: str, entity_id: str | None, payload: dict[str, Any]) -> None:
        safe_type, type_count = scrub_text(event_type)
        safe_entity, entity_count = scrub_text(entity_id or "")
        safe_payload, payload_count = scrub_value(payload)
        count = type_count + entity_count + payload_count

        def op(db: sqlite3.Connection) -> None:
            self._journal_tx(
                db,
                (safe_type or "audit")[:64],
                safe_entity[:128] or None,
                safe_payload if isinstance(safe_payload, dict) else {},
            )
            if count and safe_type != "candidates.scrubbed":
                self._journal_tx(
                    db,
                    "candidates.scrubbed",
                    None,
                    {"scrubbed_candidates": count},
                )

        self._write(op)

    def metadata(self, key: str) -> str | None:
        safe_key, scrubbed = scrub_text(key)
        if scrubbed or not safe_key:
            return None

        def op(db: sqlite3.Connection) -> str | None:
            row = db.execute("SELECT value FROM metadata WHERE key=?", (safe_key[:128],)).fetchone()
            return str(row[0]) if row else None

        return self._read(op)

    def set_metadata(self, key: str, value: str) -> None:
        safe_key, key_count = scrub_text(key)
        safe_value, value_count = scrub_text(value)
        if not safe_key:
            raise ValueError("metadata key is required")

        def op(db: sqlite3.Connection) -> None:
            db.execute(
                """INSERT INTO metadata(key,value) VALUES(?,?)
                   ON CONFLICT(key) DO UPDATE SET value=excluded.value""",
                (safe_key[:128], safe_value[:2048]),
            )
            count = key_count + value_count
            if count:
                self._journal_tx(
                    db,
                    "candidates.scrubbed",
                    None,
                    {"scrubbed_candidates": count},
                )

        self._write(op)

    def save_event(self, event: CognitiveEvent) -> bool:
        safe_kind, kind_count = scrub_text(event.kind)
        safe_source, source_count = scrub_text(event.source)
        safe_subject, subject_count = scrub_text(event.subject or "")
        safe_payload, payload_count = scrub_value(event.payload)
        safe_event_id, event_id_count = _safe_identifier(event.event_id, "event")
        safe_occurred_at, occurred_count = _safe_timestamp(event.occurred_at)
        safe = replace(
            event,
            event_id=safe_event_id,
            occurred_at=safe_occurred_at,
            kind=safe_kind[:64],
            source=safe_source[:128],
            subject=safe_subject[:256] or None,
            payload=safe_payload if isinstance(safe_payload, dict) else {},
        )
        scrubbed = (
            kind_count
            + source_count
            + subject_count
            + payload_count
            + event_id_count
            + occurred_count
        )

        def op(db: sqlite3.Connection) -> bool:
            cur = db.execute(
                """INSERT OR IGNORE INTO events
                   (event_id,kind,source,subject,confidence,payload_json,occurred_at)
                   VALUES(?,?,?,?,?,?,?)""",
                (
                    safe.event_id,
                    safe.kind,
                    safe.source,
                    safe.subject,
                    float(safe.confidence),
                    _json(safe.payload),
                    safe.occurred_at,
                ),
            )
            created = cur.rowcount == 1
            if created:
                self._journal_tx(db, "event.observed", safe.event_id, {"kind": safe.kind})
                if scrubbed:
                    self._journal_tx(
                        db,
                        "candidates.scrubbed",
                        None,
                        {"scrubbed_candidates": scrubbed},
                    )
            return created

        return self._write(op)

    def pattern(self, key: str) -> dict[str, Any] | None:
        if not _is_internal_key(key):
            return None

        def op(db: sqlite3.Connection) -> dict[str, Any] | None:
            row = db.execute("SELECT * FROM patterns WHERE pattern_key=?", (key,)).fetchone()
            return dict(row) if row else None

        return self._read(op)

    def _enforce_pattern_cap_tx(self, db: sqlite3.Connection) -> None:
        count = int(db.execute("SELECT COUNT(*) FROM patterns").fetchone()[0])
        excess = count - self.policy.max_patterns
        if excess <= 0:
            return
        rows = db.execute(
            """SELECT pattern_key FROM patterns
               ORDER BY weight ASC,evidence_count ASC,last_seen ASC LIMIT ?""",
            (excess,),
        ).fetchall()
        keys = [str(row[0]) for row in rows]
        if not keys:
            return
        marks = ",".join("?" for _ in keys)
        db.execute(
            f"DELETE FROM edges WHERE key_a IN ({marks}) OR key_b IN ({marks})",
            (*keys, *keys),
        )
        db.execute(f"DELETE FROM patterns WHERE pattern_key IN ({marks})", keys)

    def put_pattern(self, key: str, label: str, weight: float, event_id: str, seen: str) -> None:
        label = str(label).strip().lower()
        cleaned, scrubbed = scrub_text(label)
        if scrubbed or cleaned != label or reject_sensitive_candidate(label):
            raise ValueError("sensitive material cannot become a pattern label")
        if not is_valid_pattern_label(label):
            raise ValueError("pattern label must be <=32 lowercase letters/CJK/digits/hyphen")
        if not _is_internal_key(key):
            raise ValueError("pattern key must be a 24-character lowercase hex digest")

        safe_event_id, event_count = _safe_identifier(event_id, "event")
        safe_seen, seen_count = _safe_timestamp(seen)

        def op(db: sqlite3.Connection) -> None:
            db.execute(
                """INSERT INTO patterns
                   (pattern_key,label,weight,evidence_count,last_event_id,last_seen)
                   VALUES(?,?,?,?,?,?)
                   ON CONFLICT(pattern_key) DO UPDATE SET
                     label=excluded.label,
                     weight=excluded.weight,
                     evidence_count=patterns.evidence_count+1,
                     last_event_id=excluded.last_event_id,
                     last_seen=excluded.last_seen""",
                (
                    key,
                    label,
                    max(0.0, min(1.0, float(weight))),
                    1,
                    safe_event_id,
                    safe_seen,
                ),
            )
            if event_count + seen_count:
                self._journal_tx(
                    db,
                    "candidates.scrubbed",
                    None,
                    {"scrubbed_candidates": event_count + seen_count},
                )
            self._enforce_pattern_cap_tx(db)

        self._write(op)

    def delete_patterns(self, keys: list[str] | tuple[str, ...]) -> int:
        safe_keys = list(dict.fromkeys(key for key in keys if _is_internal_key(key)))[:256]
        if not safe_keys:
            return 0

        def op(db: sqlite3.Connection) -> int:
            marks = ",".join("?" for _ in safe_keys)
            db.execute(
                f"DELETE FROM edges WHERE key_a IN ({marks}) OR key_b IN ({marks})",
                (*safe_keys, *safe_keys),
            )
            cur = db.execute(f"DELETE FROM patterns WHERE pattern_key IN ({marks})", safe_keys)
            return int(cur.rowcount)

        return self._write(op)

    def edge(self, a: str, b: str) -> dict[str, Any] | None:
        if not _is_internal_key(a) or not _is_internal_key(b):
            return None
        a, b = sorted((a, b))

        def op(db: sqlite3.Connection) -> dict[str, Any] | None:
            row = db.execute("SELECT * FROM edges WHERE key_a=? AND key_b=?", (a, b)).fetchone()
            return dict(row) if row else None

        return self._read(op)

    def _enforce_edge_cap_tx(self, db: sqlite3.Connection) -> None:
        count = int(db.execute("SELECT COUNT(*) FROM edges").fetchone()[0])
        excess = count - self.policy.max_edges
        if excess > 0:
            db.execute(
                """DELETE FROM edges WHERE (key_a,key_b) IN (
                     SELECT key_a,key_b FROM edges
                     ORDER BY weight ASC,evidence_count ASC,last_seen ASC LIMIT ?
                   )""",
                (excess,),
            )

    def put_edge(self, a: str, b: str, weight: float, seen: str) -> None:
        if a == b:
            return
        if not _is_internal_key(a) or not _is_internal_key(b):
            raise ValueError("edge keys must be internal pattern digests")
        a, b = sorted((a, b))
        safe_seen, seen_count = _safe_timestamp(seen)

        def op(db: sqlite3.Connection) -> None:
            db.execute(
                """INSERT INTO edges(key_a,key_b,weight,evidence_count,last_seen)
                   VALUES(?,?,?,?,?)
                   ON CONFLICT(key_a,key_b) DO UPDATE SET
                     weight=excluded.weight,
                     evidence_count=edges.evidence_count+1,
                     last_seen=excluded.last_seen""",
                (a, b, max(0.0, min(1.0, float(weight))), 1, safe_seen),
            )
            if seen_count:
                self._journal_tx(
                    db,
                    "candidates.scrubbed",
                    None,
                    {"scrubbed_candidates": seen_count},
                )
            self._enforce_edge_cap_tx(db)

        self._write(op)

    def normalize_edges(self, cap: float, changed_nodes: list[str] | tuple[str, ...]) -> None:
        nodes = list(dict.fromkeys(node for node in changed_nodes if _is_internal_key(node)))
        if not nodes:
            return

        def op(db: sqlite3.Connection) -> None:
            for node in nodes:
                rows = db.execute(
                    "SELECT key_a,key_b,weight FROM edges WHERE key_a=? OR key_b=?",
                    (node, node),
                ).fetchall()
                total = sum(float(row["weight"]) for row in rows)
                if total <= cap or not rows:
                    continue
                scale = cap / total
                for row in rows:
                    db.execute(
                        "UPDATE edges SET weight=? WHERE key_a=? AND key_b=?",
                        (
                            float(row["weight"]) * scale,
                            row["key_a"],
                            row["key_b"],
                        ),
                    )

        self._write(op)

    def record_candidates(
        self,
        labels: list[str],
        session_key: str,
        event_id: str,
        seen: str,
    ) -> list[str]:
        if not _is_internal_key(session_key):
            raise ValueError("candidate session key must be an internal digest")
        safe_labels: list[str] = []
        scrubbed = 0
        for value in labels:
            label = str(value).strip().lower()
            cleaned, count = scrub_text(label)
            scrubbed += count
            if (
                count
                or cleaned != label
                or reject_sensitive_candidate(label)
                or not is_valid_pattern_label(label)
                or not any("\u3400" <= ch <= "\u9fff" for ch in label)
            ):
                continue
            if label not in safe_labels:
                safe_labels.append(label)
            if len(safe_labels) >= 16:
                break
        safe_event_id, event_count = _safe_identifier(event_id, "event")
        safe_seen, seen_count = _safe_timestamp(seen)
        scrubbed += event_count + seen_count

        def op(db: sqlite3.Connection) -> list[str]:
            promoted: list[str] = []
            for label in safe_labels:
                candidate_key = _key(label)
                db.execute(
                    """INSERT OR IGNORE INTO candidates
                       (candidate_key,label,occurrences,distinct_sessions,status,first_seen,last_seen)
                       VALUES(?,?,0,0,'candidate',?,?)""",
                    (candidate_key, label, safe_seen, safe_seen),
                )
                db.execute(
                    """INSERT OR IGNORE INTO candidate_sessions
                       (candidate_key,session_key,first_seen) VALUES(?,?,?)""",
                    (candidate_key, session_key, safe_seen),
                )
                session_count = int(
                    db.execute(
                        "SELECT COUNT(*) FROM candidate_sessions WHERE candidate_key=?",
                        (candidate_key,),
                    ).fetchone()[0]
                )
                db.execute(
                    """UPDATE candidates SET occurrences=occurrences+1,
                       distinct_sessions=?,last_seen=? WHERE candidate_key=?""",
                    (session_count, safe_seen, candidate_key),
                )
                status = str(
                    db.execute(
                        "SELECT status FROM candidates WHERE candidate_key=?",
                        (candidate_key,),
                    ).fetchone()[0]
                )
                if status == "candidate" and session_count >= self.policy.candidate_min_sessions:
                    db.execute(
                        "UPDATE candidates SET status='promoted' WHERE candidate_key=?",
                        (candidate_key,),
                    )
                    db.execute(
                        """INSERT OR IGNORE INTO patterns
                           (pattern_key,label,weight,evidence_count,last_event_id,last_seen)
                           VALUES(?,?,0,1,?,?)""",
                        (candidate_key, label, safe_event_id, safe_seen),
                    )
                    promoted.append(label)
            count = int(db.execute("SELECT COUNT(*) FROM candidates").fetchone()[0])
            excess = count - self.policy.max_candidates
            if excess > 0:
                db.execute(
                    """DELETE FROM candidates WHERE candidate_key IN (
                         SELECT candidate_key FROM candidates WHERE status='candidate'
                         ORDER BY distinct_sessions ASC,occurrences ASC,last_seen ASC LIMIT ?
                       )""",
                    (excess,),
                )
            self._enforce_pattern_cap_tx(db)
            if scrubbed:
                self._journal_tx(
                    db,
                    "candidates.scrubbed",
                    None,
                    {"scrubbed_candidates": scrubbed},
                )
            return promoted

        return self._write(op)

    def get_relevant_patterns(self, keys: list[str], limit: int) -> list[dict[str, Any]]:
        safe_keys = list(dict.fromkeys(key for key in keys if _is_internal_key(key)))[:64]
        bounded = max(0, min(int(limit), 64))
        if bounded == 0:
            return []

        def op(db: sqlite3.Connection) -> list[dict[str, Any]]:
            if not safe_keys:
                return []
            marks = ",".join("?" for _ in safe_keys)
            rows = db.execute(
                f"""SELECT * FROM patterns WHERE pattern_key IN ({marks})
                    ORDER BY weight DESC,last_seen DESC LIMIT ?""",
                (*safe_keys, bounded),
            ).fetchall()
            return [dict(row) for row in rows]

        return self._read(op)

    def get_connected_edges(self, keys: list[str], limit: int) -> list[dict[str, Any]]:
        safe_keys = list(dict.fromkeys(key for key in keys if _is_internal_key(key)))[:64]
        if not safe_keys:
            return []
        bounded = max(0, min(int(limit), 128))
        marks = ",".join("?" for _ in safe_keys)

        def op(db: sqlite3.Connection) -> list[dict[str, Any]]:
            rows = db.execute(
                f"""SELECT * FROM edges
                    WHERE key_a IN ({marks}) OR key_b IN ({marks})
                    ORDER BY weight DESC,last_seen DESC LIMIT ?""",
                (*safe_keys, *safe_keys, bounded),
            ).fetchall()
            return [dict(row) for row in rows]

        return self._read(op)

    def get_open_gaps(self, limit: int) -> list[dict[str, Any]]:
        bounded = max(0, min(int(limit), 32))

        def op(db: sqlite3.Connection) -> list[dict[str, Any]]:
            rows = db.execute(
                """SELECT * FROM gaps WHERE status='open'
                   ORDER BY priority DESC,updated_at DESC LIMIT ?""",
                (bounded,),
            ).fetchall()
            return [dict(row) for row in rows]

        return self._read(op)

    def upsert_gap(self, key: str, topic: str, kind: str, reason: str, priority: float) -> None:
        if not _is_internal_key(key):
            raise ValueError("gap key must be an internal digest")
        safe_topic, topic_count = scrub_text(topic)
        safe_kind, kind_count = scrub_text(kind)
        safe_reason, reason_count = scrub_text(reason)
        if not safe_topic:
            return

        def op(db: sqlite3.Connection) -> None:
            now = utc_now()
            db.execute(
                """INSERT INTO gaps
                   (gap_key,topic,kind,reason,priority,evidence_count,status,last_triggered,updated_at)
                   VALUES(?,?,?,?,?,1,'open',NULL,?)
                   ON CONFLICT(gap_key) DO UPDATE SET
                     priority=MAX(gaps.priority,excluded.priority),
                     evidence_count=gaps.evidence_count+1,
                     reason=excluded.reason,
                     kind=excluded.kind,
                     updated_at=excluded.updated_at""",
                (
                    key,
                    safe_topic[:256],
                    safe_kind[:64],
                    safe_reason[:512],
                    max(0.0, min(1.0, float(priority))),
                    now,
                ),
            )
            open_count = int(
                db.execute("SELECT COUNT(*) FROM gaps WHERE status='open'").fetchone()[0]
            )
            excess = open_count - self.policy.max_gaps
            if excess > 0:
                db.execute(
                    """DELETE FROM gaps WHERE gap_key IN (
                         SELECT gap_key FROM gaps WHERE status='open'
                         ORDER BY priority ASC,evidence_count ASC,updated_at ASC LIMIT ?
                       )""",
                    (excess,),
                )
            count = topic_count + kind_count + reason_count
            if count:
                self._journal_tx(
                    db,
                    "candidates.scrubbed",
                    None,
                    {"scrubbed_candidates": count},
                )

        self._write(op)

    def decay(self, policy: MacesPolicy | None = None, now: str | None = None) -> dict[str, int]:
        active = policy or self.policy
        self.configure(active)
        current = _dt(now or utc_now()).astimezone(UTC)

        def op(db: sqlite3.Connection) -> dict[str, int]:
            row = db.execute("SELECT value FROM metadata WHERE key='last_decay_at'").fetchone()
            if row:
                elapsed = (current - _dt(str(row[0]))).total_seconds()
                if elapsed < active.decay_interval_hours * 3600:
                    return {"changed": 0, "pruned": 0}

            changed = 0
            pruned = 0
            batch = active.prune_batch_size
            last_key = ""
            while True:
                rows = db.execute(
                    """SELECT pattern_key,weight,last_seen FROM patterns
                       WHERE pattern_key>? ORDER BY pattern_key LIMIT ?""",
                    (last_key, batch),
                ).fetchall()
                if not rows:
                    break
                for item in rows:
                    last_key = str(item["pattern_key"])
                    days = max(
                        0.0,
                        (current - _dt(str(item["last_seen"]))).total_seconds() / 86_400,
                    )
                    weight = float(item["weight"]) * math.exp(-days / active.decay_tau_days)
                    if weight < active.weight_floor:
                        db.execute(
                            "DELETE FROM edges WHERE key_a=? OR key_b=?",
                            (last_key, last_key),
                        )
                        db.execute("DELETE FROM patterns WHERE pattern_key=?", (last_key,))
                        pruned += 1
                    else:
                        db.execute(
                            "UPDATE patterns SET weight=?,last_seen=? WHERE pattern_key=?",
                            (weight, current.isoformat(), last_key),
                        )
                        changed += 1

            last_a = ""
            last_b = ""
            while True:
                rows = db.execute(
                    """SELECT key_a,key_b,weight,last_seen FROM edges
                       WHERE key_a>? OR (key_a=? AND key_b>?)
                       ORDER BY key_a,key_b LIMIT ?""",
                    (last_a, last_a, last_b, batch),
                ).fetchall()
                if not rows:
                    break
                for item in rows:
                    last_a, last_b = str(item["key_a"]), str(item["key_b"])
                    days = max(
                        0.0,
                        (current - _dt(str(item["last_seen"]))).total_seconds() / 86_400,
                    )
                    weight = float(item["weight"]) * math.exp(-days / active.decay_tau_days)
                    if weight < active.weight_floor:
                        db.execute(
                            "DELETE FROM edges WHERE key_a=? AND key_b=?",
                            (last_a, last_b),
                        )
                        pruned += 1
                    else:
                        db.execute(
                            "UPDATE edges SET weight=?,last_seen=? WHERE key_a=? AND key_b=?",
                            (weight, current.isoformat(), last_a, last_b),
                        )
                        changed += 1

            db.execute(
                """INSERT INTO metadata(key,value) VALUES('last_decay_at',?)
                   ON CONFLICT(key) DO UPDATE SET value=excluded.value""",
                (current.isoformat(),),
            )
            self._journal_tx(
                db,
                "consolidation.decay",
                None,
                {"changed": changed, "pruned": pruned},
            )
            return {"changed": changed, "pruned": pruned}

        return self._write(op)

    def create_learning_proposal(self, proposal: LearningProposal) -> bool:
        if not _is_internal_key(proposal.gap_key):
            raise ValueError("proposal gap key must be an internal digest")
        topic, topic_count = scrub_text(proposal.topic)
        reason, reason_count = scrub_text(proposal.reason)
        sources, source_count = scrub_value(proposal.required_sources)
        if not topic:
            return False
        safe_proposal_id, proposal_id_count = _safe_identifier(
            proposal.proposal_id, "proposal"
        )
        safe_created_at, created_count = _safe_timestamp(proposal.created_at)
        status, status_count = scrub_text(str(proposal.status))
        if status not in {
            "proposed",
            "approved",
            "running",
            "staged",
            "rejected",
            "promoted",
        }:
            status = "proposed"
            status_count += 1
        safe = replace(
            proposal,
            proposal_id=safe_proposal_id,
            created_at=safe_created_at,
            topic=topic[:256],
            reason=reason[:512],
            required_sources=[str(item)[:64] for item in sources if str(item)],
            status=status,
        )

        def op(db: sqlite3.Connection) -> bool:
            marks = ",".join("?" for _ in ACTIVE_PROPOSAL_STATUSES)
            existing = db.execute(
                f"""SELECT 1 FROM learning_proposals
                    WHERE gap_key=? AND status IN ({marks}) LIMIT 1""",
                (safe.gap_key, *ACTIVE_PROPOSAL_STATUSES),
            ).fetchone()
            if existing:
                return False
            try:
                db.execute(
                    """INSERT INTO learning_proposals
                       (proposal_id,digest,topic,reason,priority,required_sources_json,
                        gap_key,status,created_at)
                       VALUES(?,?,?,?,?,?,?,?,?)""",
                    (
                        safe.proposal_id,
                        safe.digest,
                        safe.topic,
                        safe.reason,
                        max(0.0, min(1.0, float(safe.priority))),
                        _json(safe.required_sources),
                        safe.gap_key,
                        str(safe.status),
                        safe.created_at,
                    ),
                )
            except sqlite3.IntegrityError:
                return False
            self._journal_tx(
                db,
                "learning.proposed",
                safe.proposal_id,
                {"gap_key": safe.gap_key},
            )
            count = (
                topic_count
                + reason_count
                + source_count
                + proposal_id_count
                + created_count
                + status_count
            )
            if count:
                self._journal_tx(
                    db,
                    "candidates.scrubbed",
                    None,
                    {"scrubbed_candidates": count},
                )
            return True

        return self._write(op)

    def stage(self, artifact: StagedArtifact) -> None:
        title, title_count = scrub_text(artifact.title)
        content, content_count = scrub_text(artifact.content)
        sources, source_count = scrub_value(artifact.sources)
        safe_artifact_id, artifact_id_count = _safe_identifier(
            artifact.artifact_id, "artifact"
        )
        safe_proposal_id, proposal_id_count = _safe_identifier(
            artifact.proposal_id, "proposal"
        )
        safe_created_at, created_count = _safe_timestamp(artifact.created_at)
        safe = replace(
            artifact,
            artifact_id=safe_artifact_id,
            proposal_id=safe_proposal_id,
            created_at=safe_created_at,
            title=title[:256],
            content=content[: self.policy.max_artifact_chars],
            sources=sources if isinstance(sources, list) else [],
        )

        def op(db: sqlite3.Connection) -> None:
            db.execute(
                """INSERT INTO staged_artifacts
                   (artifact_id,proposal_id,title,content,sources_json,confidence,created_at)
                   VALUES(?,?,?,?,?,?,?)""",
                (
                    safe.artifact_id,
                    safe.proposal_id,
                    safe.title,
                    safe.content,
                    _json(safe.sources),
                    max(0.0, min(1.0, float(safe.confidence))),
                    safe.created_at,
                ),
            )
            self._journal_tx(
                db,
                "artifact.staged",
                safe.artifact_id,
                {"proposal_id": safe.proposal_id},
            )
            count = (
                title_count
                + content_count
                + source_count
                + artifact_id_count
                + proposal_id_count
                + created_count
            )
            if count:
                self._journal_tx(
                    db,
                    "candidates.scrubbed",
                    None,
                    {"scrubbed_candidates": count},
                )

        self._write(op)

    def create_promotion(self, proposal: PromotionProposal) -> None:
        target, scrubbed = scrub_text(proposal.target_path)
        normalized = target.replace("\\", "/")
        path = PurePosixPath(normalized)
        if (
            scrubbed
            or not normalized
            or path.is_absolute()
            or any(part in {"", ".", ".."} for part in path.parts)
        ):
            raise ValueError("promotion target must be a non-sensitive relative path")
        operation, op_count = scrub_text(proposal.operation)
        safe_proposal_id, proposal_id_count = _safe_identifier(
            proposal.proposal_id, "promotion"
        )
        safe_artifact_id, artifact_id_count = _safe_identifier(
            proposal.artifact_id, "artifact"
        )
        safe_created_at, created_count = _safe_timestamp(proposal.created_at)
        safe = replace(
            proposal,
            proposal_id=safe_proposal_id,
            artifact_id=safe_artifact_id,
            created_at=safe_created_at,
            target_path=str(path)[:512],
            operation=operation[:32] or "create",
        )

        def op(db: sqlite3.Connection) -> None:
            db.execute(
                """INSERT INTO promotion_proposals
                   (proposal_id,digest,artifact_id,target_path,operation,status,created_at)
                   VALUES(?,?,?,?,?,'proposed',?)""",
                (
                    safe.proposal_id,
                    safe.digest,
                    safe.artifact_id,
                    safe.target_path,
                    safe.operation,
                    safe.created_at,
                ),
            )
            self._journal_tx(
                db,
                "promotion.proposed",
                safe.proposal_id,
                {"artifact_id": safe.artifact_id, "target_path": safe.target_path},
            )
            count = op_count + proposal_id_count + artifact_id_count + created_count
            if count:
                self._journal_tx(
                    db,
                    "candidates.scrubbed",
                    None,
                    {"scrubbed_candidates": count},
                )

        self._write(op)

    def audit_summary(self) -> dict[str, Any]:
        def op(db: sqlite3.Connection) -> dict[str, Any]:
            row = db.execute(
                "SELECT value FROM metadata WHERE key='last_decay_at'"
            ).fetchone()
            scrubbed = db.execute(
                "SELECT value FROM metadata WHERE key='scrubbed_candidates_total'"
            ).fetchone()
            return {
                "last_decay_at": str(row[0]) if row else None,
                "scrubbed_candidates": int(scrubbed[0]) if scrubbed else 0,
            }

        return self._read(op)

    def list_table(self, table: str) -> list[dict[str, Any]]:
        allowed = {
            "events",
            "patterns",
            "edges",
            "candidates",
            "candidate_sessions",
            "gaps",
            "learning_proposals",
            "staged_artifacts",
            "promotion_proposals",
            "journal",
            "metadata",
        }
        if table not in allowed:
            raise ValueError(f"unsupported table: {table}")

        def op(db: sqlite3.Connection) -> list[dict[str, Any]]:
            return [dict(row) for row in db.execute(f"SELECT * FROM {table}").fetchall()]

        return self._read(op)

    def counts(self) -> dict[str, int]:
        def op(db: sqlite3.Connection) -> dict[str, int]:
            return {
                table: int(db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
                for table in ("patterns", "edges", "gaps", "candidates")
            }

        return self._read(op)

    def top_patterns(
        self, limit: int = 20, minimum_weight: float = 0.0
    ) -> list[dict[str, Any]]:
        bounded = max(0, min(int(limit), 50))
        threshold = max(0.0, min(float(minimum_weight), 1.0))

        def op(db: sqlite3.Connection) -> list[dict[str, Any]]:
            return [
                dict(row)
                for row in db.execute(
                    """SELECT label,weight,evidence_count,last_seen FROM patterns
                       WHERE weight>=? ORDER BY weight DESC,last_seen DESC LIMIT ?""",
                    (threshold, bounded),
                ).fetchall()
            ]

        return self._read(op)
