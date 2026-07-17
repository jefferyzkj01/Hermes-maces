from __future__ import annotations

from hashlib import sha256
from itertools import combinations

from .influence import InfluenceEngine
from .models import CognitiveEvent, EventKind, LearningProposal, PromotionProposal, StagedArtifact
from .policy import MacesPolicy
from .store import CognitiveStore
from .validation import is_valid_pattern_label


def _key(value: str) -> str:
    return sha256(value.strip().lower().encode()).hexdigest()[:24]


class MacesEngine:
    def __init__(self, store: CognitiveStore, policy: MacesPolicy | None = None) -> None:
        self.store = store
        self.policy = policy or MacesPolicy()
        self.influence_engine = InfluenceEngine(store, self.policy)

    def observe(self, event: CognitiveEvent) -> dict[str, int]:
        event.validate()
        if not self.store.save_event(event):
            return {"patterns": 0, "edges": 0, "gaps": 0, "proposals": 0}
        if event.payload.get("operator_driven") is False or event.payload.get("from_staging") is True:
            return {"patterns": 0, "edges": 0, "gaps": 0, "proposals": 0}

        labels = self._labels(event)
        keys = {label: _key(label) for label in labels}
        positive = event.kind in {EventKind.ANSWER_CONFIRMED, EventKind.DECISION_CONFIRMED}
        negative = event.kind == EventKind.ANSWER_CORRECTED
        retrieval = event.kind == EventKind.RETRIEVAL_USED

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
                # task.completed records occurrence and co-occurrence only. Mention
                # frequency is not evidence of preference.
                weight = old
            self.store.put_pattern(key, label, weight, event.event_id, event.occurred_at)

        edges = 0
        for a, b in combinations(keys.values(), 2):
            row = self.store.edge(a, b)
            old = float(row["weight"]) if row else 0.0
            weight = self.policy.penalize(old) if negative else self.policy.reinforce(old)
            self.store.put_edge(a, b, weight, event.occurred_at)
            edges += 1
        self.store.normalize_edges(self.policy.outbound_edge_cap)

        gaps = proposals = 0
        for topic, kind, reason, priority in self._gaps(event):
            gap_key = _key(topic)
            self.store.upsert_gap(gap_key, topic, kind, reason, priority)
            gaps += 1
            p = LearningProposal(topic, reason, priority, ["primary"], gap_key)
            proposals += int(self.store.create_learning_proposal(p))

        return {"patterns": len(labels), "edges": edges, "gaps": gaps, "proposals": proposals}

    def consolidate(self, now: str | None = None) -> dict[str, int]:
        return self.store.decay(self.policy, now)

    def influence(self, concepts: list[str] | str):
        if isinstance(concepts, str):
            concepts = [concepts]
        return self.influence_engine.signal(concepts)

    def stage_research(self, artifact: StagedArtifact) -> None:
        self.store.stage(artifact)

    def propose_promotion(self, artifact_id: str, target_path: str) -> PromotionProposal:
        proposal = PromotionProposal(artifact_id=artifact_id, target_path=target_path)
        self.store.create_promotion(proposal)
        return proposal

    def _labels(self, event: CognitiveEvent) -> list[str]:
        values = event.payload.get("concepts", event.payload.get("patterns", []))
        labels = [str(v).strip().lower() for v in values if str(v).strip()]
        return list(dict.fromkeys(v for v in labels if is_valid_pattern_label(v)))[:16]

    def _gaps(self, event: CognitiveEvent) -> list[tuple[str, str, str, float]]:
        result: list[tuple[str, str, str, float]] = []
        if event.kind == EventKind.GAP_OBSERVED:
            topic = str(event.payload.get("topic", event.subject or "")).strip()
            if topic:
                result.append((topic, "observed", "Hermes retrieval found no relevant explicit knowledge", 0.8))
        for item in event.payload.get("knowledge_gaps", []):
            topic = item if isinstance(item, str) else item.get("topic", "")
            topic = str(topic).strip()
            if topic:
                result.append((topic, "observed", "Observed unresolved knowledge need", 0.6))
        return result
