from __future__ import annotations

from .store import CognitiveStore as BaseCognitiveStore
from .validation import is_valid_pattern_label


class CognitiveStore(BaseCognitiveStore):
    """Cognitive store with the pattern-key-space invariant enforced at write time."""

    def put_pattern(self, key: str, label: str, weight: float, event_id: str, seen: str) -> None:
        if not is_valid_pattern_label(label):
            raise ValueError("pattern label must be <=32 lowercase letters/CJK/digits/hyphen")
        # Internal keys are deterministic 24-character lowercase hex digests.
        if len(key) != 24 or any(ch not in "0123456789abcdef" for ch in key):
            raise ValueError("pattern key must be a 24-character lowercase hex digest")
        super().put_pattern(key, label, weight, event_id, seen)
