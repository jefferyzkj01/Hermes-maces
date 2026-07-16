from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class MacesPolicy:
    max_research_queries: int = 6
    max_sources: int = 12
    max_artifact_chars: int = 32_000
    max_influence_items: int = 8
    minimum_pattern_weight: float = 0.15
    require_learning_approval: bool = False
    require_promotion_approval: bool = True

    def validate_research_budget(self, query_count: int, source_count: int) -> None:
        if query_count > self.max_research_queries:
            raise PermissionError("research query budget exceeded")
        if source_count > self.max_sources:
            raise PermissionError("research source budget exceeded")

    def validate_artifact(self, content: str) -> None:
        if not content.strip():
            raise ValueError("research content is empty")
        if len(content) > self.max_artifact_chars:
            raise ValueError("artifact size budget exceeded")
