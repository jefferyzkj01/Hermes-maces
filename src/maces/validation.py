from __future__ import annotations

import math
import re
from collections import Counter
from typing import Any

_PATTERN_LABEL = re.compile(r"[a-z0-9\u3400-\u9fff-]{1,32}\Z")
_PROFILE_ID = _PATTERN_LABEL
_SECRET_KEY = re.compile(r"(?i)(?:api[_-]?key|access[_-]?token|refresh[_-]?token|oauth|jwt|secret|authorization|bearer|password|passwd|pwd|credential)")
_SECRET_ASSIGNMENT = re.compile(
    r"(?i)\b(?:api[_-]?key|access[_-]?token|refresh[_-]?token|oauth|jwt|secret|authorization|bearer|password|passwd|pwd)\s*[:=]\s*\S+"
)
_BEARER = re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]{8,}")
_JWT = re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\b")
_EMAIL = re.compile(r"(?i)\b[a-z0-9.!#$%&'*+/=?^_`{|}~-]+@[a-z0-9-]+(?:\.[a-z0-9-]+)+\b")
_URL_SENSITIVE = re.compile(r"(?i)\bhttps?://(?:[^\s/@]+:[^\s/@]+@|[^\s?#]+[?#]\S*)")
_PATH = re.compile(r"(?:(?:^|\s)(?:~?/|\\\\|[a-zA-Z]:[\\/])\S+)")
_PHONE = re.compile(r"(?<!\w)(?:\+?\d[\d\s().-]{6,}\d)(?!\w)")
_LONG_DIGITS = re.compile(r"(?<!\d)\d{8,}(?!\d)")
_LONG_HEX_OR_B64 = re.compile(
    r"(?<![A-Za-z0-9])[A-Fa-f0-9]{20,}(?![A-Za-z0-9])|"
    r"(?<![A-Za-z0-9+/])[A-Za-z0-9+/]{20,}={0,2}(?![A-Za-z0-9+/])"
)


def is_valid_pattern_label(value: str) -> bool:
    return value == value.lower() and bool(_PATTERN_LABEL.fullmatch(value))


def sanitize_profile_id(value: object) -> str:
    profile_id = str(value or "").strip().lower()
    if not _PROFILE_ID.fullmatch(profile_id):
        raise ValueError("trusted profile name must be 1-32 lowercase letters/CJK/digits/hyphen")
    return profile_id


def shannon_entropy(value: str) -> float:
    if not value:
        return 0.0
    counts = Counter(value)
    length = len(value)
    return -sum((count / length) * math.log2(count / length) for count in counts.values())


def scrub_text(value: str) -> tuple[str, int]:
    text = str(value)
    scrubbed = 0
    for pattern in (
        _SECRET_ASSIGNMENT,
        _BEARER,
        _JWT,
        _EMAIL,
        _URL_SENSITIVE,
        _PATH,
        _PHONE,
        _LONG_DIGITS,
        _LONG_HEX_OR_B64,
    ):
        text, count = pattern.subn(" ", text)
        scrubbed += count
    words = text.split()
    safe_words: list[str] = []
    for word in words:
        if reject_sensitive_candidate(word):
            scrubbed += 1
        else:
            safe_words.append(word)
    return " ".join(safe_words), scrubbed


def scrub_value(value: Any, key: str = "") -> tuple[Any, int]:
    """Recursively sanitize every value before it may cross a persistence boundary."""
    if _SECRET_KEY.search(str(key)):
        return "[redacted]", 1
    if isinstance(value, str):
        return scrub_text(value)
    if isinstance(value, dict):
        output: dict[str, Any] = {}
        count = 0
        for child_key, child_value in value.items():
            cleaned, removed = scrub_value(child_value, str(child_key))
            output[str(child_key)] = cleaned
            count += removed
        return output, count
    if isinstance(value, (list, tuple)):
        output = []
        count = 0
        for child in value:
            cleaned, removed = scrub_value(child)
            output.append(cleaned)
            count += removed
        return output, count
    return value, 0


def reject_sensitive_candidate(value: str) -> bool:
    return len(value) >= 16 and shannon_entropy(value) > 4.0
