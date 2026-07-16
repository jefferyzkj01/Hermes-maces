from __future__ import annotations

from hashlib import sha256

from .models import InfluenceSignal
from .policy import MacesPolicy
from .store import CognitiveStore


def _key(value: str) -> str:
    return sha256(value.strip().lower().encode()).hexdigest()[:24]


class InfluenceEngine:
    def __init__(self, store: CognitiveStore, policy: MacesPolicy | None = None) -> None:
        self.store = store
        self.policy = policy or MacesPolicy()

    def signal(self, concepts: list[str]) -> InfluenceSignal:
        patterns = self.store.list_table("patterns")
        edges = self.store.list_table("edges")
        gaps = self.store.list_table("gaps")
        wanted = {_key(c): c.strip().lower() for c in concepts if c.strip()}

        relevant = [r for r in patterns if r["pattern_key"] in wanted]
        if not relevant:
            relevant = sorted(patterns, key=lambda r: float(r["weight"]), reverse=True)[:2]
        attention = [
            (str(r["label"]), float(r["weight"]))
            for r in sorted(relevant, key=lambda r: float(r["weight"]), reverse=True)
            if float(r["weight"]) >= self.policy.minimum_influence_weight
        ][: self.policy.influence_max_items]

        labels = {r["pattern_key"]: r["label"] for r in patterns}
        connected = [r for r in edges if r["key_a"] in wanted or r["key_b"] in wanted]
        associations = [
            (str(labels.get(r["key_a"], r["key_a"])), str(labels.get(r["key_b"], r["key_b"])), float(r["weight"]))
            for r in sorted(connected, key=lambda r: float(r["weight"]), reverse=True)
            if float(r["weight"]) >= self.policy.minimum_influence_weight
        ][: max(0, self.policy.influence_max_items - len(attention))]

        verify = [str(r["topic"]) for r in gaps if r["status"] == "open"][:2]
        values = [w for _, w in attention] + [w for _, _, w in associations]
        signal = InfluenceSignal(attention, associations, verify, sum(values) / len(values) if values else 0.0)
        # The renderer only sees weighted labels, edge labels, and gap topics. It never
        # queries staged_artifacts, so autonomous research text cannot enter prompts.
        if len(signal.render()) > self.policy.influence_max_chars:
            signal.associations = []
        return signal
