"""Hermes MACES plugin entrypoint."""

try:
    from .src.maces.plugin import register
except ImportError:  # direct import during local validation
    from src.maces.plugin import register

__all__ = ["register"]
