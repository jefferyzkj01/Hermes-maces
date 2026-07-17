from __future__ import annotations

from dataclasses import replace
from hashlib import sha256
from itertools import combinations

from .influence import InfluenceEngine
from .models import CognitiveEvent, EventKind, LearningProposal, PromotionProposal, StagedArtifact
from .policy import MacesPolicy
from .secure_store import CognitiveStore
from .validation import is_valid_pattern_label, reject_sensitive_candidate, scrub_text


def _key(value: str) -> str:
    return sha256(value.strip().lower().encode()).hexdigest()[:24]


class MacesEngine:
    def __init__(self, store: CognitiveStore, policy: MacesPolicy | None = None) -> None:
        self.store = store
        self.policy = policy or MacesPolicy()
        self.store.configure(self.policy)
        self.influence_engine = InfluenceEngine(store, self.policy)

    def observe(self, event: CognitiveEvent) -> dict[str, int]:
        event.validate()
        original_payload = dict(event.payload)
        persisted_payload = {
            key: value for key, value in original_payload.items() if not str(key).startswith("_")
        }
        if not self.store.save_event(replace(event, payload=persisted_payload)):
            return {"patterns": 0, "edges": 0, "gaps": 0, "proposals": 0}
        if original_payload.get("operator_driven") is False or original_payload.get("from_staging") is True:
            return {"patterns": 0, "edges": 0, "gaps": 0, "proposals": 0}

        labels = self._labels(original_payload)
        keys = {label: _key(label) for label in labels}
        kind = str(event.kind)
        positive = kind in {str(EventKind.ANSWER_CONFIRMED), str(EventKind.DECISION_CONFIRMED)}
        negative = kind == str(EventKind.ANSWER_CORRECTED)
        retrieval = kind == str(EventKind.RETRIEVAL_USED)

        for label, key in keys.items():
            row = self.store.pattern(key)
            old = float(row["weight"]) if row else 0.0
            if positive:
                weight = self.policy.reinforce(old)
            elif negative:
                weight = self.policy.penalize(old)
            elif retrieval:
                weight = self.policy.reinforce_retrieval(old)
            else:
                weight = old
            self.store.put_pattern(key, label, weight, event.event_id, event.occurred_at)

        edge_count = 0
        for a, b in combinations(keys.values(), 2):
            row = self.store.edge(a, b)
            old = float(row["weight"]) if row else 0.0
            if negative:
                weight = self.policy.penalize(old)
            elif positive or retrieval:
                weight = self.policy.reinforce(old)
            else:
                weight = old
            self.store.put_edge(a, b, weight, event.occurred_at)
            edge_count += 1
        self.store.normalize_edges(self.policy.outbound_edge_cap, list(keys.values()))

        candidate_labels = self._candidate_labels(original_payload)
        promoted: list[str] = []
        if candidate_labels:
            session_key = str(original_payload.get("_candidate_session_key", ""))
            if not session_key and original_payload.get("session_id"):
                session_key = _key(str(original_payload["session_id"]))
            if len(session_key) == 24:
                promoted = self.store.record_candidates(
                    candidate_labels,
                    session_key,
                    event.event_id,
                    event.occurred_at,
                )

        gaps = proposals = 0
        for topic, gap_kind, reason, priority in self._gaps(event, original_payload):
            safe_topic, topic_count = scrub_text(topic)
            safe_reason, reason_count = scrub_text(reason)
            if topic_count + reason_count:
                self.store.journal(
                    "candidates.scrubbed",
                    None,
                    {"scrubbed_candidates": topic_count + reason_count},
                )
            if not safe_topic:
                continue
            gap_key = _key(safe_topic)
            self.store.upsert_gap(
                gap_key, safe_topic, gap_kind, safe_reason, priority
            )
            gaps += 1
            proposal = LearningProposal(
                safe_topic, safe_reason, priority, ["primary"], gap_key
            )
            proposals += int(self.store.create_learning_proposal(proposal))

        return {
            "patterns": len(labels) + len(promoted),
            "edges": edge_count,
            "gaps": gaps,
            "proposals": proposals,
        }

    def consolidate(self, now: str | None = None) -> dict[str, int]:
        return self.store.decay(self.policy, now)

    def influence(self, concepts: list[str] | str) -> InfluenceSignal:
        values = [concepts] if isinstance(concepts, str) else concepts
        return self.influence_engine.signal(values)

    def stage_research(self, artifact: StagedArtifact) -> None:
        self.store.stage(artifact)

    def propose_promotion(self, artifact_id: str, target_path: str) -> PromotionProposal:
        proposal = PromotionProposal(artifact_id=artifact_id, target_path=target_path)
        self.store.create_promotion(proposal)
        return proposal

    @staticmethod
    def _labels(payload: dict) -> list[str]:
        values = payload.get("concepts", payload.get("patterns", []))
        if not isinstance(values, (list, tuple)):
            return []
        labels: list[str] = []
        for value in values:
            raw = str(value).strip().lower()
            if not raw:
                continue
            cleaned, scrubbed = scrub_text(raw)
            if scrubbed or cleaned != raw or reject_sensitive_candidate(raw):
                continue
            if is_valid_pattern_label(raw):
                labels.append(raw)
        return list(dict.fromkeys(labels))[:16]

    @staticmethod
    def _candidate_labels(payload: dict) -> list[str]:
        values = payload.get("candidates", payload.get("candidate_concepts", []))
        if not isinstance(values, (list, tuple)):
            return []
        labels: list[str] = []
        for value in values:
            raw = str(value).strip().lower()
            cleaned, scrubbed = scrub_text(raw)
            if scrubbed or cleaned != raw or reject_sensitive_candidate(raw):
                continue
            if is_valid_pattern_label(raw):
                labels.append(raw)
        return list(dict.fromkeys(labels))[:16]

    @staticmethod
    def _gaps(event: CognitiveEvent, payload: dict) -> list[tuple[str, str, str, float]]:
        result: list[tuple[str, str, str, float]] = []
        if str(event.kind) == str(EventKind.GAP_OBSERVED):
            topic = str(payload.get("topic", event.subject or "")).strip()
            if topic:
                result.append(
                    (
                        topic,
                        "observed",
                        "Hermes retrieval found no relevant explicit knowledge",
                        0.8,
                    )
                )
        for item in payload.get("knowledge_gaps", []):
            topic = item if isinstance(item, str) else item.get("topic", "")
            topic = str(topic).strip()
            if topic:
                result.append((topic, "observed", "Observed unresolved knowledge need", 0.6))
        return result


# Type-only import kept at the end to avoid obscuring the public return annotation.
from .models import InfluenceSignal  # noqa: E402
