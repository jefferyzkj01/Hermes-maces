from __future__ import annotations

import sys
import types
from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def add_src(monkeypatch):
    root = Path(__file__).resolve().parents[1]
    monkeypatch.syspath_prepend(str(root / "src"))
    from maces.plugin import _reset_runtime_registry_for_tests

    _reset_runtime_registry_for_tests()


@pytest.fixture
def install_fake_hermes(monkeypatch):
    def install(home: Path, config: dict | None = None):
        hermes_constants = types.ModuleType("hermes_constants")
        hermes_constants.get_hermes_home = lambda: home

        hermes_cli = types.ModuleType("hermes_cli")
        hermes_cli.__path__ = []
        profiles = types.ModuleType("hermes_cli.profiles")
        profiles.normalize_profile_name = lambda value: str(value).strip().lower()

        def validate(name: str) -> None:
            import re

            if name != "default" and not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,63}", name):
                raise ValueError("invalid profile")

        profiles.validate_profile_name = validate
        config_module = types.ModuleType("hermes_cli.config")
        config_module.load_config = lambda: config or {}

        monkeypatch.setitem(sys.modules, "hermes_constants", hermes_constants)
        monkeypatch.setitem(sys.modules, "hermes_cli", hermes_cli)
        monkeypatch.setitem(sys.modules, "hermes_cli.profiles", profiles)
        monkeypatch.setitem(sys.modules, "hermes_cli.config", config_module)
        return home

    return install
