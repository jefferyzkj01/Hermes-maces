"""Compatibility import. All persistence is implemented by secure_store."""

from .secure_store import CognitiveStore

__all__ = ["CognitiveStore"]
