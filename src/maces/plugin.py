from __future__ import annotations

import json
import logging
import re
import shutil
from pathlib import Path
from typing import Any

from .engine import MacesEngine
from .models import CognitiveEvent
from .policy import MacesPolicy
from .secure_store import CognitiveStore
from .validation import is_valid_pattern_label, reject_sensitive_candidate, sanitize_profile_id, scrub_text

log = logging.getLogger("hermes-maces")
_PLUGIN_ROOT = Path(__file__).resolve().parents[2]
_POLICY = MacesPolicy()
_ENGINES: dict[str, MacesEngine] = {}
_PENDING: dict[str, tuple[str, list[str]]] = {}
_WARNED_DEFAULT_PROFILE = False


def _context_value(kwargs: dict[str, Any], name: str) -> Any:
    if kwargs.get(name) not in (None, ""):
        return kwargs[name]
    for container_name in ("context", "hook_context", "runtime_context"):
        container = kwargs.get(container_name)
        if isinstance(container, dict) and container.get(name) not in (None, ""):
            return container[name]
        value = getattr(container, name, None)
        if value not in (None, ""):
            return value
    return None


def _profile_id(kwargs: dict[str, Any]) -> str:
    global _WARNED_DEFAULT_PROFILE
    raw = None
    for name in ("profile_id", "group_id", "profile"):
        raw = _context_value(kwargs, name)
        if raw not in (None, ""):
            break
    if raw in (None, ""):
        if not _WARNED_DEFAULT_PROFILE:
            log.warning("MACES hook context has no profile identifier; using isolated 'default' store")
            _WARNED_DEFAULT_PROFILE = True
        return "default"
    return sanitize_profile_id(raw)


def _migrate_legacy_database(data: Path, profile_id: str) -> None:
    legacy = data / "subconscious.db"
    destination = data / "default" / "subconscious.db"
    if profile_id != "default" or not legacy.exists() or destination.exists():
        return
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(legacy), str(destination))
    store = CognitiveStore(destination)
    store.journal("store.migrated", "default", {"from": "legacy", "to": "default"})


def _engine(profile_id: str) -> MacesEngine:
    existing = _ENGINES.get(profile_id)
    if existing is not None:
        return existing
    data = (_PLUGIN_ROOT / "data").resolve()
    data.mkdir(parents=True, exist_ok=True)
    _migrate_legacy_database(data, profile_id)
    profile_dir = (data / profile_id).resolve()
    if data not in profile_dir.parents:
        raise ValueError("profile database path escaped plugin data directory")
    profile_dir.mkdir(parents=True, exist_ok=True)
    engine = MacesEngine(CognitiveStore(profile_dir / "subconscious.db"), _POLICY)
    _ENGINES[profile_id] = engine
    return engine


def _extract_concepts(text: str, limit: int = 8) -> tuple[list[str], int]:
    scrubbed_text, scrubbed = scrub_text(text)
    latin = re.findall(r"[A-Za-z0-9][A-Za-z0-9-]{3,31}", scrubbed_text.lower())
    cjk = re.findall(r"[\u3400-\u9fff]{2,8}", scrubbed_text)
    concepts: list[str] = []
    for candidate in latin + cjk:
        if reject_sensitive_candidate(candidate) or not is_valid_pattern_label(candidate):
            scrubbed += 1
            continue
        if candidate not in concepts:
            concepts.append(candidate)
        if len(concepts) >= limit:
            break
    return concepts, scrubbed


def _concepts(text: str, limit: int = 8) -> list[str]:
    return _extract_concepts(text, limit)[0]


def _learnable_tool_text(tool_name: str, args: dict[str, Any]) -> str:
    fields = _POLICY.learnable_fields_for(tool_name)
    values = [args.get(field) for field in fields]
    return " ".join(value for value in values if isinstance(value, str))


def _assert_session_profile(session_id: str, profile_id: str) -> list[str] | None:
    pending = _PENDING.pop(session_id, None)
    if pending is None:
        return None
    pending_profile, concepts = pending
    if pending_profile != profile_id:
        raise RuntimeError(
            f"MACES profile mismatch for session {session_id!r}: "
            f"{pending_profile!r} != {profile_id!r}"
        )
    return concepts


def pre_llm_call(user_message: str, session_id: str = "", **kwargs: Any):
    profile_id = _profile_id(kwargs)
    concepts, scrubbed = _extract_concepts(user_message)
    _PENDING[session_id] = (profile_id, concepts)
    if scrubbed:
        _engine(profile_id).store.journal(
            "candidates.scrubbed", None, {"scrubbed_candidates": scrubbed}
        )
    rendered = _engine(profile_id).influence(concepts).render()
    return {"context": rendered} if rendered else None


def post_llm_call(
    session_id: str, user_message: str, assistant_response: str, **kwargs: Any
):
    profile_id = _profile_id(kwargs)
    concepts = _assert_session_profile(session_id, profile_id)
    if concepts is None:
        concepts, scrubbed = _extract_concepts(user_message)
        if scrubbed:
            _engine(profile_id).store.journal(
                "candidates.scrubbed", None, {"scrubbed_candidates": scrubbed}
            )
    _engine(profile_id).observe(
        CognitiveEvent(
            kind="task.completed",
            source="hermes-runtime",
            subject=" ".join(concepts[:3]) or None,
            payload={"concepts": concepts, "operator_driven": True},
        )
    )
    log.debug("absorbed completed turn (%d chars)", len(assistant_response or ""))


def post_tool_call(tool_name: str, args: dict, result: str, **kwargs: Any):
    profile_id = _profile_id(kwargs)
    concepts, scrubbed = _extract_concepts(_learnable_tool_text(tool_name, args))
    engine = _engine(profile_id)
    if scrubbed:
        engine.store.journal(
            "candidates.scrubbed", None, {"scrubbed_candidates": scrubbed}
        )
    if not concepts:
        return
    engine.observe(
        CognitiveEvent(
            kind="retrieval.used",
            source="hermes-tool",
            subject=tool_name,
            payload={
                "concepts": concepts,
                "operator_driven": True,
                "result_size": len(result or ""),
            },
        )
    )


def on_session_end(session_id: str = "", **kwargs: Any):
    profile_id = _profile_id(kwargs)
    pending = _PENDING.get(session_id)
    if pending is not None and pending[0] != profile_id:
        raise RuntimeError("MACES session ended under a different profile")
    _PENDING.pop(session_id, None)
    _engine(profile_id).consolidate()


def feedback_tool(params: dict, **kwargs: Any) -> str:
    profile_id = _profile_id({**kwargs, **params})
    verdict = str(params.get("verdict", "")).strip().lower()
    raw_concepts = [str(x) for x in params.get("concepts", [])]
    concepts: list[str] = []
    scrubbed = 0
    for raw in raw_concepts:
        extracted, count = _extract_concepts(raw, limit=16)
        concepts.extend(extracted)
        scrubbed += count
    concepts = list(dict.fromkeys(concepts))[:16]
    if verdict not in {"confirmed", "corrected"}:
        return json.dumps({"success": False, "error": "verdict must be confirmed or corrected"})
    engine = _engine(profile_id)
    if scrubbed:
        engine.store.journal(
            "candidates.scrubbed", None, {"scrubbed_candidates": scrubbed}
        )
    output = engine.observe(
        CognitiveEvent(
            kind=f"answer.{verdict}",
            source="operator-feedback",
            payload={"concepts": concepts, "operator_driven": True},
        )
    )
    return json.dumps({"success": True, **output})


def register(ctx):
    ctx.register_hook("pre_llm_call", pre_llm_call)
    ctx.register_hook("post_llm_call", post_llm_call)
    ctx.register_hook("post_tool_call", post_tool_call)
    ctx.register_hook("on_session_end", on_session_end)
    ctx.register_tool(
        name="maces_feedback",
        toolset="maces",
        description="Record explicit operator confirmation or correction for subconscious concepts.",
        schema={
            "name": "maces_feedback",
            "description": "Record explicit confirmed/corrected operator feedback for concepts.",
            "parameters": {
                "type": "object",
                "properties": {
                    "verdict": {"type": "string", "enum": ["confirmed", "corrected"]},
                    "concepts": {"type": "array", "items": {"type": "string"}},
                    "profile_id": {"type": "string"},
                },
                "required": ["verdict", "concepts"],
            },
        },
        handler=feedback_tool,
    )
