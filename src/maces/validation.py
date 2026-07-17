from __future__ import annotations

import math
import re
from collections import Counter

_PATTERN_LABEL = re.compile(r"[a-z0-9\u3400-\u9fff-]{1,32}\Z")
_PROFILE_ID = _PATTERN_LABEL
_SECRET_ASSIGNMENT = re.compile(
    r"(?i)\b(?:api[_-]?key|token|secret|bearer|password|pwd)\s*[:=]\s*\S+"
)
_EMAIL = re.compile(r"(?i)\b[a-z0-9.!#$%&'*+/=?^_`{|}~-]+@[a-z0-9-]+(?:\.[a-z0-9-]+)+\b")
_URL_SENSITIVE = re.compile(r"(?i)\bhttps?://(?:[^\s/@]+:[^\s/@]+@|[^\s?#]+[?#]\S*)")
_PATH = re.compile(r"(?:(?:^|\s)(?:~?/|\\\\|[a-zA-Z]:[\\/])\S+)")
_PHONE = re.compile(r"(?<!\w)(?:\+?\d[\d\s().-]{6,}\d)(?!\w)")
_LONG_DIGITS = re.compile(r"(?<!\d)\d{8,}(?!\d)")
_LONG_HEX_OR_B64 = re.compile(r"(?<![A-Za-z0-9])[A-Fa-f0-9]{20,}(?![A-Za-z0-9])|(?<![A-Za-z0-9+/])[A-Za-z0-9+/]{20,}={0,2}(?![A-Za-z0-9+/])")


def is_valid_pattern_label(value: str) -> bool:
    return value == value.lower() and bool(_PATTERN_LABEL.fullmatch(value))


def sanitize_profile_id(value: object) -> str:
    profile_id = str(value or "default").strip().lower()
    if not _PROFILE_ID.fullmatch(profile_id):
        raise ValueError("profile_id must be 1-32 lowercase letters/CJK/digits/hyphen")
    return profile_id


def shannon_entropy(value: str) -> float:
    if not value:
        return 0.0
    counts = Counter(value)
    length = len(value)
    return -sum((count / length) * math.log2(count / length) for count in counts.values())


def scrub_text(value: str) -> tuple[str, int]:
    text = value
    scrubbed = 0
    for pattern in (
        _SECRET_ASSIGNMENT,
        _EMAIL,
        _URL_SENSITIVE,
        _PATH,
        _PHONE,
        _LONG_DIGITS,
        _LONG_HEX_OR_B64,
    ):
        text, count = pattern.subn(" ", text)
        scrubbed += count
    return text, scrubbed


def reject_sensitive_candidate(value: str) -> bool:
    return len(value) >= 16 and shannon_entropy(value) > 4.0
