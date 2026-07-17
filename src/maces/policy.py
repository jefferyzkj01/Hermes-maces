from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

_DEFAULT_ZH_STOPWORDS = (
    "我們",
    "你們",
    "他們",
    "這個",
    "那個",
    "可以",
    "需要",
    "應該",
    "以及",
    "但是",
    "然後",
    "目前",
    "問題",
    "內容",
    "方式",
)


@dataclass(frozen=True, slots=True)
class MacesPolicy:
    reinforcement_alpha: float = 0.10
    retrieval_alpha: float = 0.03
    correction_beta: float = 0.35
    decay_tau_days: float = 45.0
    weight_floor: float = 0.02
    outbound_edge_cap: float = 3.0
    influence_max_items: int = 4
    influence_max_chars: int = 700
    minimum_influence_weight: float = 0.10
    max_research_queries: int = 6
    max_sources: int = 12
    max_artifact_chars: int = 32_000
    max_patterns: int = 5_000
    max_edges: int = 20_000
    max_gaps: int = 500
    max_candidates: int = 5_000
    decay_interval_hours: int = 24
    prune_batch_size: int = 500
    candidate_min_sessions: int = 3
    learnable_tool_fields: dict[str, tuple[str, ...]] = field(default_factory=dict)
    zh_stopwords: tuple[str, ...] = _DEFAULT_ZH_STOPWORDS

    def reinforce(self, weight: float) -> float:
        return min(1.0, weight + self.reinforcement_alpha * (1.0 - weight))

    def reinforce_retrieval(self, weight: float) -> float:
        return min(1.0, weight + self.retrieval_alpha * (1.0 - weight))

    def penalize(self, weight: float) -> float:
        return max(0.0, weight * (1.0 - self.correction_beta))

    def learnable_fields_for(self, tool_name: str) -> tuple[str, ...]:
        return self.learnable_tool_fields.get(str(tool_name), ())

    @classmethod
    def from_mapping(cls, raw: Any) -> tuple["MacesPolicy", list[str]]:
        """Build a validated policy from ``plugins.entries.hermes-maces``.

        Invalid values never propagate into runtime behavior. The caller uses the
        returned error list to force shadow mode while Hermes continues to start.
        """

        errors: list[str] = []
        data = raw if isinstance(raw, dict) else {}

        def section(name: str) -> dict[str, Any]:
            value = data.get(name, {})
            if value is None:
                return {}
            if not isinstance(value, dict):
                errors.append(f"{name} must be a mapping")
                return {}
            return value

        influence = section("influence")
        limits = section("limits")
        maintenance = section("maintenance")
        zh = section("traditional_chinese")

        def number(mapping: dict[str, Any], key: str, default: float, low: float, high: float):
            value = mapping.get(key, default)
            if isinstance(default, int) and not isinstance(default, bool):
                if isinstance(value, bool) or not isinstance(value, int):
                    errors.append(f"{key} must be an integer")
                    return default
            elif isinstance(value, bool) or not isinstance(value, (int, float)):
                errors.append(f"{key} must be numeric")
                return default
            if not low <= float(value) <= high:
                errors.append(f"{key} must be between {low:g} and {high:g}")
                return default
            return type(default)(value)

        raw_fields = data.get("learnable_tool_fields", {})
        fields: dict[str, tuple[str, ...]] = {}
        if not isinstance(raw_fields, dict):
            errors.append("learnable_tool_fields must be a mapping")
        else:
            for tool, values in raw_fields.items():
                if not isinstance(tool, str) or not tool.strip() or not isinstance(values, list):
                    errors.append("learnable_tool_fields entries must map tool names to lists")
                    continue
                cleaned = tuple(
                    field.strip()
                    for field in values
                    if isinstance(field, str) and field.strip() and len(field.strip()) <= 64
                )
                if len(cleaned) != len(values):
                    errors.append(f"invalid learnable fields for {tool}")
                    continue
                fields[tool.strip()] = cleaned

        raw_stopwords = zh.get("stopwords", list(_DEFAULT_ZH_STOPWORDS))
        if not isinstance(raw_stopwords, list):
            errors.append("traditional_chinese.stopwords must be a list")
            stopwords = _DEFAULT_ZH_STOPWORDS
        else:
            stopwords = tuple(
                value.strip()
                for value in raw_stopwords
                if isinstance(value, str) and 1 <= len(value.strip()) <= 32
            )
            if len(stopwords) != len(raw_stopwords):
                errors.append("traditional_chinese.stopwords contains invalid values")
                stopwords = _DEFAULT_ZH_STOPWORDS

        policy = cls(
            influence_max_items=number(influence, "max_items", 4, 0, 8),
            influence_max_chars=number(influence, "max_chars", 700, 0, 2_000),
            minimum_influence_weight=number(
                influence, "minimum_weight", 0.10, 0.0, 1.0
            ),
            max_patterns=number(limits, "max_patterns", 5_000, 100, 100_000),
            max_edges=number(limits, "max_edges", 20_000, 100, 500_000),
            max_gaps=number(limits, "max_open_gaps", 500, 10, 10_000),
            max_candidates=number(limits, "max_candidates", 5_000, 100, 100_000),
            decay_interval_hours=number(
                maintenance, "decay_interval_hours", 24, 1, 168
            ),
            prune_batch_size=number(
                maintenance, "prune_batch_size", 500, 10, 5_000
            ),
            candidate_min_sessions=number(
                zh, "candidate_min_sessions", 3, 2, 10
            ),
            learnable_tool_fields=fields,
            zh_stopwords=stopwords,
        )
        return policy, errors
