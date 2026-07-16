from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

from .models import LearningIntent, PromotionProposal, ResearchPlan, StagedArtifact


@runtime_checkable
class ResearchProvider(Protocol):
    name: str
    source_types: set[str]

    def research(self, plan: ResearchPlan) -> StagedArtifact: ...


@runtime_checkable
class ApprovalProvider(Protocol):
    name: str

    def approve_learning(self, intent: LearningIntent) -> bool: ...
    def authorize_promotion(self, proposal: PromotionProposal) -> str | None: ...


@runtime_checkable
class CanonicalProvider(Protocol):
    name: str

    def write(self, proposal: PromotionProposal, artifact: StagedArtifact, grant: str) -> Any: ...


@dataclass(slots=True)
class CapabilityBus:
    research: list[ResearchProvider] = field(default_factory=list)
    approvals: list[ApprovalProvider] = field(default_factory=list)
    canonical: dict[str, CanonicalProvider] = field(default_factory=dict)

    def register(self, provider: object) -> None:
        if isinstance(provider, ResearchProvider):
            self.research.append(provider)
        if isinstance(provider, ApprovalProvider):
            self.approvals.append(provider)
        if isinstance(provider, CanonicalProvider):
            self.canonical[provider.name] = provider

    def capabilities(self) -> dict[str, object]:
        return {
            "observation": True,
            "pattern_mining": True,
            "gap_detection": True,
            "influence": True,
            "research": [p.name for p in self.research],
            "approval": [p.name for p in self.approvals],
            "canonical_write": sorted(self.canonical),
        }

    def select_research(self, source_types: list[str]) -> ResearchProvider | None:
        wanted = set(source_types)
        candidates = sorted(
            self.research,
            key=lambda p: len(wanted.intersection(p.source_types)),
            reverse=True,
        )
        return candidates[0] if candidates and wanted.intersection(candidates[0].source_types) else None
