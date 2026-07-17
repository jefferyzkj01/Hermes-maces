from __future__ import annotations

from hashlib import sha256

from .models import InfluenceSignal
from .policy import MacesPolicy
from .secure_store import CognitiveStore
from .validation import is_valid_pattern_label


def _key(value: str) -> str:
    return sha256(value.strip().lower().encode()).hexdigest()[:24]


class InfluenceEngine:
    def __init__(self, store: CognitiveStore, policy: MacesPolicy | None = None) -> None:
        self.store = store
        self.policy = policy or MacesPolicy()

    def signal(self, concepts: list[str]) -> InfluenceSignal:
        wanted = {_key(c): c.strip().lower() for c in concepts if str(c).strip()}
        if not wanted or self.policy.influence_max_items <= 0:
            return InfluenceSignal()

        query_limit = max(self.policy.influence_max_items * 4, 8)
        patterns = self.store.get_relevant_patterns(list(wanted), query_limit)
        safe_patterns = [
            row
            for row in patterns
            if is_valid_pattern_label(str(row["label"]))
            and float(row["weight"]) >= self.policy.minimum_influence_weight
        ]
        attention_candidates = [
            (str(row["label"]), float(row["weight"])) for row in safe_patterns
        ]

        edges = self.store.get_connected_edges(list(wanted), query_limit)
        endpoint_keys = {
            str(row["key_a"]) for row in edges
        } | {str(row["key_b"]) for row in edges}
        endpoint_patterns = self.store.get_relevant_patterns(
            list(endpoint_keys), query_limit * 2
        )
        safe_endpoints = [
            row
            for row in endpoint_patterns
            if is_valid_pattern_label(str(row["label"]))
            and float(row["weight"]) >= self.policy.minimum_influence_weight
        ]
        labels = {str(row["pattern_key"]): str(row["label"]) for row in safe_endpoints}
        weighted = set(labels)
        association_candidates = [
            (
                labels[str(row["key_a"])],
                labels[str(row["key_b"])],
                float(row["weight"]),
            )
            for row in edges
            if str(row["key_a"]) in weighted
            and str(row["key_b"]) in weighted
            and float(row["weight"]) >= self.policy.minimum_influence_weight
        ]

        remaining = self.policy.influence_max_items
        attention = attention_candidates[:remaining]
        remaining -= len(attention)
        associations = association_candidates[:remaining]
        remaining -= len(associations)

        # An unresolved gap alone is not a high-weight signal. Only append verify
        # reminders after a weighted node or association already justified influence.
        verify: list[str] = []
        if remaining > 0 and (attention or associations):
            verify = [
                str(row["topic"])
                for row in self.store.get_open_gaps(remaining)
            ][:remaining]

        values = [weight for _, weight in attention] + [
            weight for _, _, weight in associations
        ]
        signal = InfluenceSignal(
            attention=attention,
            associations=associations,
            verify=verify,
            confidence=sum(values) / len(values) if values else 0.0,
        )
        while signal.render() and len(signal.render()) > self.policy.influence_max_chars:
            if signal.verify:
                signal.verify.pop()
            elif signal.associations:
                signal.associations.pop()
            elif signal.attention:
                signal.attention.pop()
            else:
                break
        if len(signal.render()) > self.policy.influence_max_chars:
            return InfluenceSignal()
        return signal
