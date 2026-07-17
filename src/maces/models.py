from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from hashlib import sha256
from json import dumps
from typing import Any
from uuid import uuid4


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


class EventKind(StrEnum):
    RETRIEVAL_USED = "retrieval.used"
    ANSWER_CONFIRMED = "answer.confirmed"
    ANSWER_CORRECTED = "answer.corrected"
    TASK_COMPLETED = "task.completed"
    DECISION_CONFIRMED = "decision.confirmed"
    GAP_OBSERVED = "gap.observed"


class ProposalStatus(StrEnum):
    PROPOSED = "proposed"
    APPROVED = "approved"
    RUNNING = "running"
    STAGED = "staged"
    REJECTED = "rejected"
    PROMOTED = "promoted"


@dataclass(slots=True)
class CognitiveEvent:
    kind: str
    source: str
    payload: dict[str, Any]
    subject: str | None = None
    confidence: float = 1.0
    occurred_at: str = field(default_factory=utc_now)
    event_id: str = field(default_factory=lambda: str(uuid4()))

    def validate(self) -> None:
        if not isinstance(self.payload, dict):
            raise ValueError("payload must be a mapping")
        if not str(self.kind).strip() or not str(self.source).strip():
            raise ValueError("kind and source are required")
        if not 0 <= float(self.confidence) <= 1:
            raise ValueError("confidence must be between 0 and 1")


@dataclass(slots=True)
class InfluenceSignal:
    attention: list[tuple[str, float]] = field(default_factory=list)
    associations: list[tuple[str, str, float]] = field(default_factory=list)
    verify: list[str] = field(default_factory=list)
    confidence: float = 0.0

    def render(self) -> str:
        items: list[str] = []
        items.extend(f"prioritize {label} ({weight:.2f})" for label, weight in self.attention)
        items.extend(f"consider {a} ↔ {b} ({weight:.2f})" for a, b, weight in self.associations)
        items.extend(f"verify {topic}" for topic in self.verify)
        if not items:
            return ""
        return "[intuition — advisory, unverified]\n" + "\n".join(
            f"- {item}" for item in items
        )


@dataclass(slots=True)
class LearningProposal:
    topic: str
    reason: str
    priority: float
    required_sources: list[str]
    gap_key: str
    status: ProposalStatus = ProposalStatus.PROPOSED
    proposal_id: str = field(default_factory=lambda: str(uuid4()))
    created_at: str = field(default_factory=utc_now)

    @property
    def digest(self) -> str:
        stable = {"gap_key": self.gap_key}
        return sha256(dumps(stable, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


@dataclass(slots=True)
class StagedArtifact:
    proposal_id: str
    title: str
    content: str
    sources: list[dict[str, str]]
    confidence: float
    artifact_id: str = field(default_factory=lambda: str(uuid4()))
    created_at: str = field(default_factory=utc_now)


@dataclass(slots=True)
class PromotionProposal:
    artifact_id: str
    target_path: str
    operation: str = "create"
    proposal_id: str = field(default_factory=lambda: str(uuid4()))
    created_at: str = field(default_factory=utc_now)

    @property
    def digest(self) -> str:
        stable = {
            "artifact_id": self.artifact_id,
            "target_path": self.target_path,
            "operation": self.operation,
        }
        return sha256(dumps(stable, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
