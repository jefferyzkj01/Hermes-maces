from __future__ import annotations

import math
import re
import unicodedata
from collections import Counter
from typing import Any

_PATTERN_LABEL = re.compile(r"[a-z0-9\u3400-\u9fff-]{1,32}\Z")
_EXPLICIT_CONCEPT = re.compile(r"[a-z0-9\u3400-\u9fff-]{2,32}\Z")
_PROFILE_FALLBACK = re.compile(r"[a-z0-9][a-z0-9_-]{0,63}\Z")
_SECRET_KEY = re.compile(
    r"(?i)(?:api[_-]?key|access[_-]?token|refresh[_-]?token|token|oauth|jwt|secret|"
    r"authorization|bearer|password|passwd|pwd|credential|cookie|session[_-]?token)"
)
_SECRET_ASSIGNMENT = re.compile(
    r"(?i)\b(?:api[_-]?key|access[_-]?token|refresh[_-]?token|token|oauth|jwt|secret|"
    r"authorization|bearer|password|passwd|pwd|credential|cookie|session[_-]?token)"
    r"\s*[:=]\s*[^\s,;]+"
)
_BEARER = re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]{8,}")
_JWT = re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\b")
_EMAIL = re.compile(r"(?i)\b[a-z0-9.!#$%&'*+/=?^_`{|}~-]+@[a-z0-9-]+(?:\.[a-z0-9-]+)+\b")
_URL_SENSITIVE = re.compile(
    r"(?i)\bhttps?://(?:[^\s/@]+:[^\s/@]+@|[^\s?#]+[?#][^\s]*)"
)
_ABSOLUTE_PATH = re.compile(
    r"(?<![\w:])(?:~?/|\\\\|[A-Za-z]:[\\/])(?:[^\s,;]+)"
)
_PHONE = re.compile(r"(?<!\w)(?:\+?\d[\d\s().-]{6,}\d)(?!\w)")
_LONG_DIGITS = re.compile(r"(?<!\d)\d{8,}(?!\d)")
_LONG_HEX = re.compile(r"(?<![A-Za-z0-9])[A-Fa-f0-9]{20,}(?![A-Za-z0-9])")
_LONG_BASE64 = re.compile(
    r"(?<![A-Za-z0-9+/])[A-Za-z0-9+/]{20,}={0,2}(?![A-Za-z0-9+/])"
)
_TOKENISH = re.compile(r"[A-Za-z0-9._~+/=-]{16,}")


def normalize_text(value: object) -> str:
    return unicodedata.normalize("NFKC", str(value or "")).strip()


def is_valid_pattern_label(value: str) -> bool:
    normalized = normalize_text(value)
    return normalized == normalized.lower() and bool(_PATTERN_LABEL.fullmatch(normalized))


def is_valid_explicit_concept(value: str) -> bool:
    normalized = normalize_text(value).lower()
    return bool(_EXPLICIT_CONCEPT.fullmatch(normalized))


def sanitize_profile_id(value: object) -> str:
    """Compatibility fallback used only when Hermes profile helpers are unavailable."""

    profile_id = normalize_text(value).lower()
    if profile_id == "default":
        return profile_id
    if not _PROFILE_FALLBACK.fullmatch(profile_id):
        raise ValueError("invalid trusted Hermes profile name")
    return profile_id


def shannon_entropy(value: str) -> float:
    if not value:
        return 0.0
    counts = Counter(value)
    length = len(value)
    return -sum((count / length) * math.log2(count / length) for count in counts.values())


def reject_sensitive_candidate(value: str) -> bool:
    normalized = normalize_text(value)
    return len(normalized) >= 16 and shannon_entropy(normalized) > 4.0


def scrub_text(value: object) -> tuple[str, int]:
    """Remove secret and personal-data shapes before persistence or extraction."""

    text = normalize_text(value)
    scrubbed = 0
    for pattern in (
        _SECRET_ASSIGNMENT,
        _BEARER,
        _JWT,
        _EMAIL,
        _URL_SENSITIVE,
        _ABSOLUTE_PATH,
        _PHONE,
        _LONG_DIGITS,
        _LONG_HEX,
        _LONG_BASE64,
    ):
        text, count = pattern.subn(" ", text)
        scrubbed += count

    def entropy_filter(match: re.Match[str]) -> str:
        nonlocal scrubbed
        candidate = match.group(0)
        if reject_sensitive_candidate(candidate):
            scrubbed += 1
            return " "
        return candidate

    text = _TOKENISH.sub(entropy_filter, text)
    text = " ".join(text.split())
    return text, scrubbed


def scrub_value(value: Any, key: str = "") -> tuple[Any, int]:
    """Recursively sanitize a value before it crosses the SQLite boundary."""

    if key and _SECRET_KEY.search(normalize_text(key)):
        return None, 1
    if isinstance(value, str):
        return scrub_text(value)
    if isinstance(value, dict):
        output: dict[str, Any] = {}
        count = 0
        for child_key, child_value in value.items():
            safe_key, key_count = scrub_text(child_key)
            if safe_key and _SECRET_KEY.search(safe_key):
                count += key_count + 1
                continue
            cleaned, removed = scrub_value(child_value, safe_key)
            if safe_key:
                output[safe_key[:128]] = cleaned
            count += key_count + removed
        return output, count
    if isinstance(value, (list, tuple, set)):
        output: list[Any] = []
        count = 0
        for child in value:
            cleaned, removed = scrub_value(child)
            output.append(cleaned)
            count += removed
        return output, count
    if value is None or isinstance(value, (bool, int, float)):
        return value, 0
    return scrub_text(value)
