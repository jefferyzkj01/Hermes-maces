from __future__ import annotations

from hashlib import sha256

from .capabilities import CapabilityBus
from .influence import InfluenceEngine
from .learning import LearningExecutor
from .models import CognitiveEvent, LearningIntent, PromotionProposal, StagedArtifact
from .policy import MacesPolicy
from .store import CognitiveStore


def _key(value: str) -> str:
    return sha256(value.strip().lower().encode()).hexdigest()[:24]


class MacesEngine:
    def __init__(
        self,
        store: CognitiveStore,
        policy: MacesPolicy | None = None,
        capabilities: CapabilityBus | None = None,
    ) -> None:
        self.store = store
        self.policy = policy or MacesPolicy()
        self.capabilities = capabilities or CapabilityBus()
        self.influence_engine = InfluenceEngine(store, self.policy)
        self.learning_executor = LearningExecutor(self.capabilities, self.policy)

    def observe(self, event: CognitiveEvent) -> dict[str, int]:
        event.validate()
        if not self.store.save_event(event):
            return {"patterns": 0, "gaps": 0, "proposals": 0}
        patterns = 0
        for label in self._pattern_labels(event):
            self.store.upsert_pattern(
                _key(label), label, max(0.05, event.confidence * 0.12), event.event_id
            )
            patterns += 1
        gaps = proposals = 0
        for topic, reason, priority, sources in self._gaps(event):
            gap_key = _key(topic)
            self.store.upsert_gap(gap_key, topic, reason, priority)
            gaps += 1
            intent = LearningIntent(
                topic=topic,
                reason=reason,
                priority=priority,
                required_evidence=sources,
                strategy="adaptive",
                gap_key=gap_key,
            )
            proposals += int(self.store.create_learning_proposal(intent))
        return {"patterns": patterns, "gaps": gaps, "proposals": proposals}

    def influence(self, subject: str):
        return self.influence_engine.signal(subject)

    def learn(self, intent: LearningIntent) -> StagedArtifact | None:
        artifact = self.learning_executor.execute(intent)
        if artifact is not None:
            self.store.stage(artifact)
        return artifact

    def stage_research(
        self,
        proposal_id: str,
        *,
        title: str,
        content: str,
        sources: list[dict[str, str]],
        query_count: int,
        confidence: float,
    ) -> StagedArtifact:
        self.policy.validate_research_budget(query_count, len(sources))
        self.policy.validate_artifact(content)
        proposal = self.store.get_learning(proposal_id)
        if self.policy.require_learning_approval and proposal["status"] != "approved":
            raise PermissionError("proposal must be approved before research")
        artifact = StagedArtifact(
            proposal_id=proposal_id,
            title=title,
            content=content,
            sources=sources,
            confidence=min(1.0, max(0.0, confidence)),
        )
        self.store.stage(artifact)
        return artifact

    def propose_promotion(
        self, artifact_id: str, target_provider: str, target_path: str
    ) -> PromotionProposal:
        proposal = PromotionProposal(
            artifact_id=artifact_id,
            target_provider=target_provider,
            target_path=target_path,
        )
        self.store.create_promotion(proposal)
        return proposal

    def _pattern_labels(self, event: CognitiveEvent) -> list[str]:
        labels = [str(v).strip() for v in event.payload.get("patterns", []) if str(v).strip()]
        if event.subject:
            labels.append(f"subject:{event.subject.strip().lower()}")
        return sorted(set(labels))

    def _gaps(self, event: CognitiveEvent) -> list[tuple[str, str, float, list[str]]]:
        result = []
        for item in event.payload.get("knowledge_gaps", []):
            if isinstance(item, str):
                topic, reason, priority, sources = item, "Observed unresolved knowledge need", 0.5, ["primary"]
            else:
                topic = str(item.get("topic", "")).strip()
                reason = str(item.get("reason", "Observed unresolved knowledge need")).strip()
                priority = float(item.get("priority", 0.5))
                sources = [str(v) for v in item.get("required_sources", ["primary"])]
            if topic:
                result.append((topic, reason, min(1.0, max(0.0, priority)), sources))
        return result
