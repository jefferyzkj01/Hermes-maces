from __future__ import annotations

import json
import logging
import re
import shlex
import shutil
import threading
from dataclasses import dataclass, field
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from time import perf_counter
from typing import Any

from .engine import MacesEngine
from .models import CognitiveEvent
from .policy import MacesPolicy
from .secure_store import CognitiveStore
from .validation import (
    is_valid_explicit_concept,
    is_valid_pattern_label,
    normalize_text,
    reject_sensitive_candidate,
    sanitize_profile_id,
    scrub_text,
)

log = logging.getLogger("hermes-maces")
_PLUGIN_ROOT = Path(__file__).resolve().parents[2]
_LATIN = re.compile(r"[A-Za-z0-9][A-Za-z0-9-]{3,31}")
_CJK_RUN = re.compile(r"[\u3400-\u9fff]+")
_NEGATIONS = ("不要", "別", "不喜歡", "不想要", "不需要", "避免", "不是", "不可")
_POSITIVE_PREFIXES = ("我喜歡", "我偏好", "我想要", "喜歡", "偏好", "想要", "請用", "使用")
_PREFIX_WINDOW = 8
_USAGE = (
    "Usage: /maces-feedback confirmed <concept,concept>\n"
    "       /maces-feedback corrected <concept,concept>"
)
_RUNTIME_LOCK = threading.RLock()
_RUNTIMES: dict[tuple[str, str], "ProfileRuntime"] = {}


@dataclass(slots=True)
class ExtractedConcepts:
    patterns: list[str]
    candidates: list[str]
    scrubbed: int

    @property
    def query(self) -> list[str]:
        return list(dict.fromkeys(self.patterns + self.candidates))

    @property
    def candidate_concepts(self) -> tuple[str, ...]:
        """Compatibility alias for the two-stage Chinese candidate list."""
        return tuple(self.candidates)


@dataclass(slots=True)
class PendingTurn:
    extracted: ExtractedConcepts


def _extract_passive(text: str, policy: MacesPolicy | None = None) -> ExtractedConcepts:
    active = policy or MacesPolicy()
    scrubbed_text, scrubbed = scrub_text(text)
    patterns: list[str] = []
    for match in _LATIN.findall(scrubbed_text):
        candidate = match.lower()
        if reject_sensitive_candidate(candidate) or not is_valid_pattern_label(candidate):
            scrubbed += 1
            continue
        if candidate not in patterns:
            patterns.append(candidate)
        if len(patterns) >= 8:
            break

    stopwords = set(active.zh_stopwords)
    candidates: list[str] = []
    for match_obj in _CJK_RUN.finditer(scrubbed_text):
        match = match_obj.group(0)
        # Long prose is deliberately ignored instead of being sliced into arbitrary
        # fragments. Explicit feedback remains the path for long intentional labels.
        if not 2 <= len(match) <= 32:
            continue
        prefix = scrubbed_text[max(0, match_obj.start() - _PREFIX_WINDOW):match_obj.start()]
        prefix = re.sub(r"[\s，,。！？!?：:；;、]+", "", prefix)
        suffix = scrubbed_text[match_obj.end():match_obj.end() + 3]
        suffix = re.sub(r"[\s，,。！？!?：:；;、]+", "", suffix)
        negated = (
            any(negation in match for negation in _NEGATIONS)
            or any(prefix.endswith(negation) for negation in _NEGATIONS)
            or (prefix.endswith("太") and suffix.startswith("了"))
            or (match.startswith("太") and match.endswith("了"))
        )
        if negated:
            continue
        for positive_prefix in _POSITIVE_PREFIXES:
            if match.startswith(positive_prefix) and len(match) > len(positive_prefix) + 1:
                match = match[len(positive_prefix):]
                break
        if match in stopwords or any(stopword and stopword in match for stopword in stopwords):
            continue
        normalized = normalize_text(match).lower()
        if not is_valid_pattern_label(normalized):
            continue
        if normalized not in candidates:
            candidates.append(normalized)
        if len(candidates) >= 8:
            break
    return ExtractedConcepts(patterns, candidates, scrubbed)


def _extract_concepts(text: str, limit: int = 8) -> tuple[list[str], int]:
    """Backwards-compatible Latin extractor used by older integrations/tests."""

    result = _extract_passive(text)
    return result.patterns[:limit], result.scrubbed


def _parse_feedback(raw_args: str) -> tuple[str, list[str]] | None:
    try:
        tokens = shlex.split(str(raw_args or ""), posix=True)
    except ValueError:
        return None
    if len(tokens) < 2:
        return None
    verdict = tokens[0].strip().lower()
    if verdict not in {"confirmed", "corrected"}:
        return None
    raw_concepts = re.split(r"[,，\s]+", " ".join(tokens[1:]).strip())
    concepts: list[str] = []
    for raw in raw_concepts:
        if not raw:
            continue
        cleaned, scrubbed = scrub_text(raw)
        concept = normalize_text(cleaned).lower()
        if scrubbed or concept != normalize_text(raw).lower():
            return None
        if reject_sensitive_candidate(concept) or not is_valid_explicit_concept(concept):
            return None
        if concept not in concepts:
            concepts.append(concept)
    if not concepts or len(concepts) > 16:
        return None
    return verdict, concepts


def _trusted_profile_name(ctx: Any) -> str:
    raw = getattr(ctx, "profile_name", None)
    if raw in (None, ""):
        raise RuntimeError("Hermes MACES requires trusted ctx.profile_name")
    try:
        from hermes_cli.profiles import normalize_profile_name, validate_profile_name

        normalized = normalize_profile_name(str(raw))
        validate_profile_name(normalized)
        return normalized
    except ImportError:
        return sanitize_profile_id(raw)


def _profile_home() -> Path:
    from hermes_constants import get_hermes_home

    return Path(get_hermes_home()).expanduser().resolve()


def _plugin_id(ctx: Any) -> str:
    manifest = getattr(ctx, "manifest", None)
    return str(getattr(manifest, "key", None) or getattr(manifest, "name", None) or "hermes-maces")


def _load_plugin_entry(ctx: Any) -> tuple[dict[str, Any], list[str]]:
    try:
        from hermes_cli.config import load_config

        config = load_config() or {}
    except Exception as exc:
        return {}, [f"Hermes config loader failed: {exc}"]
    if not isinstance(config, dict):
        return {}, ["Hermes config root must be a mapping"]
    plugins = config.get("plugins")
    if not isinstance(plugins, dict):
        return {}, []
    entries = plugins.get("entries")
    if not isinstance(entries, dict):
        return {}, []
    entry = entries.get(_plugin_id(ctx), entries.get("hermes-maces", {}))
    if entry is None:
        return {}, []
    if not isinstance(entry, dict):
        return {}, ["plugins.entries.hermes-maces must be a mapping"]
    return entry, []


def _load_policy(ctx: Any) -> tuple[MacesPolicy, bool]:
    entry, errors = _load_plugin_entry(ctx)
    policy, policy_errors = MacesPolicy.from_mapping(entry)
    errors.extend(policy_errors)
    raw_shadow = entry.get("shadow_mode", True)
    if not isinstance(raw_shadow, bool):
        errors.append("shadow_mode must be boolean")
        raw_shadow = True
    shadow_mode = bool(raw_shadow or errors)
    if errors:
        log.warning("Invalid MACES config; forcing shadow mode: %s", "; ".join(errors))
    return policy, shadow_mode


def _move_with_sidecars(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(source), str(destination))
    for suffix in ("-wal", "-shm"):
        sidecar = Path(str(source) + suffix)
        if sidecar.exists():
            shutil.move(str(sidecar), str(destination) + suffix)


def _migrate_legacy_databases(data_dir: Path, profile_name: str, policy: MacesPolicy) -> None:
    legacy_paths = (
        _PLUGIN_ROOT / "data" / "subconscious.db",
        _PLUGIN_ROOT / "data" / "default" / "subconscious.db",
    )
    destination = data_dir / "subconscious.db"
    migrated: list[str] = []
    for index, legacy in enumerate(legacy_paths, start=1):
        if not legacy.exists():
            continue
        if not destination.exists():
            target = destination
        else:
            stamp = datetime.now(UTC).strftime("%Y%m%d%H%M%S%f")
            target = data_dir / f"legacy-subconscious-{stamp}-{index}.db"
        _move_with_sidecars(legacy, target)
        migrated.append(target.name)
    if migrated:
        store = CognitiveStore(destination, policy)
        store.journal(
            "migration",
            profile_name,
            {"legacy_databases": migrated, "destination": "data/maces"},
        )


def _session_digest(profile_name: str, session_id: str) -> str:
    stable = f"{profile_name}\x00{session_id or 'session'}"
    return sha256(stable.encode()).hexdigest()[:24]


def _tool_call_succeeded(result: object, kwargs: dict[str, Any]) -> bool:
    """Fail closed unless a normalized tool status explicitly reports success.

    Hermes 0.18 exposes the final JSON result to ``post_tool_call``. Newer
    runtimes may also pass normalized ``status``/``error_type`` kwargs, so both
    surfaces are supported without retaining result content.
    """

    payload: dict[str, Any] = {}
    if isinstance(result, dict):
        payload = result
    elif isinstance(result, str):
        try:
            parsed = json.loads(result)
            if isinstance(parsed, dict):
                payload = parsed
        except (TypeError, ValueError, json.JSONDecodeError):
            payload = {}

    status = kwargs.get("status", payload.get("status"))
    error_type = kwargs.get("error_type", payload.get("error_type"))
    if status != "ok" or error_type is not None:
        return False
    if payload.get("success") is False or payload.get("error") not in (None, ""):
        return False
    return True


@dataclass(slots=True)
class ProfileRuntime:
    profile_name: str
    hermes_home: Path
    engine: MacesEngine
    policy: MacesPolicy
    shadow_mode: bool
    pending: dict[tuple[str, str, str], PendingTurn] = field(default_factory=dict)
    lock: threading.RLock = field(default_factory=threading.RLock)
    error_count: int = 0
    last_influence_items: int = 0
    last_influence_latency_ms: float = 0.0

    def _turn_key(self, session_id: str, kwargs: dict[str, Any]) -> tuple[str, str, str]:
        turn_id = str(
            kwargs.get("turn_id")
            or kwargs.get("api_request_id")
            or kwargs.get("request_id")
            or kwargs.get("task_id")
            or session_id
            or "turn"
        )
        return self.profile_name, str(session_id or "session"), turn_id

    def _journal_scrubbed(self, count: int) -> None:
        if count:
            self.engine.store.journal(
                "candidates.scrubbed", None, {"scrubbed_candidates": int(count)}
            )

    def _mark_error(self) -> None:
        with self.lock:
            self.error_count += 1

    def _record_influence(self, rendered: str, started_at: float) -> None:
        with self.lock:
            self.last_influence_items = rendered.count("\n-") if rendered else 0
            self.last_influence_latency_ms = (perf_counter() - started_at) * 1_000

    def pre_llm_call(self, user_message: str = "", session_id: str = "", **kwargs: Any):
        key = self._turn_key(session_id, kwargs)
        started_at = perf_counter()
        try:
            extracted = _extract_passive(str(user_message or ""), self.policy)
            with self.lock:
                self.pending[key] = PendingTurn(extracted)
            self._journal_scrubbed(extracted.scrubbed)
            if self.shadow_mode:
                self._record_influence("", started_at)
                return None
            rendered = self.engine.influence(extracted.query).render()
            self._record_influence(rendered, started_at)
            return {"context": rendered} if rendered else None
        except Exception:
            self._mark_error()
            self._record_influence("", started_at)
            log.exception("MACES influence failed; continuing without advisory context")
            return None

    def post_llm_call(
        self,
        session_id: str = "",
        user_message: str = "",
        assistant_response: str = "",
        **kwargs: Any,
    ) -> None:
        key = self._turn_key(session_id, kwargs)
        try:
            with self.lock:
                pending = self.pending.pop(key, None)
            extracted = (
                pending.extracted
                if pending is not None
                else _extract_passive(str(user_message or ""), self.policy)
            )
            if pending is None:
                self._journal_scrubbed(extracted.scrubbed)
            self.engine.observe(
                CognitiveEvent(
                    kind="task.completed",
                    source="hermes-runtime",
                    subject=" ".join(extracted.query[:3]) or None,
                    payload={
                        "concepts": extracted.patterns,
                        "candidates": extracted.candidates,
                        "operator_driven": True,
                        "_candidate_session_key": _session_digest(
                            self.profile_name, session_id
                        ),
                    },
                )
            )
            log.debug("absorbed completed turn (%d chars)", len(assistant_response or ""))
        except Exception:
            self._mark_error()
            log.exception("MACES turn absorption failed; Hermes response is unaffected")
        finally:
            with self.lock:
                self.pending.pop(key, None)

    def post_tool_call(
        self,
        tool_name: str,
        args: dict | None = None,
        result: str = "",
        **kwargs: Any,
    ) -> None:
        try:
            if not _tool_call_succeeded(result, kwargs):
                return
            fields = self.policy.learnable_fields_for(tool_name)
            if not fields:
                return
            safe_args = args if isinstance(args, dict) else {}
            values = [safe_args.get(field) for field in fields]
            text = " ".join(value for value in values if isinstance(value, str))
            extracted = _extract_passive(text, self.policy)
            self._journal_scrubbed(extracted.scrubbed)
            concepts = list(dict.fromkeys(extracted.patterns + extracted.candidates))
            if not concepts:
                return
            self.engine.observe(
                CognitiveEvent(
                    kind="retrieval.used",
                    source="hermes-tool",
                    subject=str(tool_name)[:128],
                    payload={
                        "concepts": concepts,
                        "operator_driven": True,
                        "result_size": len(str(result or "")),
                        "status": "ok",
                    },
                )
            )
        except Exception:
            self._mark_error()
            log.exception("MACES tool absorption failed; tool result is unaffected")

    def _clear_session(self, session_id: str) -> None:
        prefix = (self.profile_name, str(session_id or "session"))
        with self.lock:
            for key in [key for key in self.pending if key[:2] == prefix]:
                self.pending.pop(key, None)

    def on_turn_error(self, session_id: str = "", **kwargs: Any) -> None:
        key = self._turn_key(session_id, kwargs)
        with self.lock:
            self.pending.pop(key, None)

    def on_session_cleanup(self, session_id: str = "", **kwargs: Any) -> None:
        del kwargs
        try:
            self._clear_session(session_id)
            self.engine.consolidate()
        except Exception:
            self._mark_error()
            log.exception("MACES session cleanup failed; Hermes lifecycle is unaffected")

    def feedback_command(self, raw_args: str) -> str:
        parsed = _parse_feedback(raw_args)
        if parsed is None:
            return _USAGE
        verdict, concepts = parsed
        try:
            output = self.engine.observe(
                CognitiveEvent(
                    kind=f"answer.{verdict}",
                    source="trusted-operator-feedback",
                    payload={"concepts": concepts, "operator_driven": True},
                )
            )
        except Exception:
            self._mark_error()
            log.exception("MACES feedback write failed")
            return "MACES feedback could not be recorded; Hermes remains unaffected."
        return (
            f"MACES recorded {verdict} feedback for {len(concepts)} concept(s) "
            f"({output['patterns']} pattern update(s))."
        )

    def status_command(self, raw_args: str = "") -> str:
        if str(raw_args or "").strip():
            return "Usage: /maces-status"
        try:
            counts = self.engine.store.counts()
            audit = self.engine.store.audit_summary()
            decay = audit["last_decay_at"] or "never"
            db_size = Path(self.engine.store.path).stat().st_size
            with self.lock:
                error_count = self.error_count
                influence_items = self.last_influence_items
                influence_latency_ms = self.last_influence_latency_ms
            return (
                f"MACES profile={self.profile_name} shadow_mode={str(self.shadow_mode).lower()} "
                f"patterns={counts['patterns']} edges={counts['edges']} "
                f"gaps={counts['gaps']} candidates={counts['candidates']} "
                f"db_bytes={db_size} last_decay_at={decay} "
                f"errors={error_count} scrubbed={audit['scrubbed_candidates']} "
                f"last_influence_items={influence_items} "
                f"last_influence_ms={influence_latency_ms:.2f}"
            )
        except Exception:
            self._mark_error()
            log.exception("MACES status read failed")
            return "MACES status is temporarily unavailable."

    def top_command(self, raw_args: str = "") -> str:
        value = str(raw_args or "").strip()
        if value:
            try:
                limit = int(value)
            except ValueError:
                return "Usage: /maces-top [1-20]"
        else:
            limit = 10
        if not 1 <= limit <= 20:
            return "Usage: /maces-top [1-20]"
        try:
            rows = self.engine.store.top_patterns(limit, self.policy.minimum_influence_weight)
        except Exception:
            self._mark_error()
            log.exception("MACES top-pattern read failed")
            return "MACES top concepts are temporarily unavailable."
        if not rows:
            return "MACES has no weighted concepts yet."
        return "MACES top concepts:\n" + "\n".join(
            f"- {row['label']} ({float(row['weight']):.2f})" for row in rows
        )


def register(ctx: Any) -> ProfileRuntime:
    profile_name = _trusted_profile_name(ctx)
    hermes_home = _profile_home()
    data_dir = (hermes_home / "data" / "maces").resolve()
    if hermes_home != data_dir and hermes_home not in data_dir.parents:
        raise ValueError("MACES data directory escaped the active Hermes home")
    data_dir.mkdir(parents=True, exist_ok=True)
    policy, shadow_mode = _load_policy(ctx)
    _migrate_legacy_databases(data_dir, profile_name, policy)

    registry_key = (profile_name, str(hermes_home))
    with _RUNTIME_LOCK:
        runtime = _RUNTIMES.get(registry_key)
        if runtime is None:
            store = CognitiveStore(data_dir / "subconscious.db", policy)
            runtime = ProfileRuntime(
                profile_name=profile_name,
                hermes_home=hermes_home,
                engine=MacesEngine(store, policy),
                policy=policy,
                shadow_mode=shadow_mode,
            )
            _RUNTIMES[registry_key] = runtime
        else:
            # ``discover_and_load(force=True)`` may re-register a plugin after a
            # profile config change. Refresh the cached per-profile runtime rather
            # than retaining stale limits or shadow-mode state.
            runtime.policy = policy
            runtime.shadow_mode = shadow_mode
            runtime.engine.policy = policy
            runtime.engine.influence_engine.policy = policy
            runtime.engine.store.configure(policy)

    ctx.register_hook("pre_llm_call", runtime.pre_llm_call)
    ctx.register_hook("post_llm_call", runtime.post_llm_call)
    ctx.register_hook("post_tool_call", runtime.post_tool_call)
    ctx.register_hook("api_request_error", runtime.on_turn_error)
    ctx.register_hook("on_session_end", runtime.on_session_cleanup)
    ctx.register_hook("on_session_finalize", runtime.on_session_cleanup)
    ctx.register_hook("on_session_reset", runtime.on_session_cleanup)
    ctx.register_command(
        "maces-feedback",
        runtime.feedback_command,
        description="Confirm or correct MACES concepts explicitly",
        args_hint="<confirmed|corrected> <concepts>",
    )
    ctx.register_command(
        "maces-status",
        runtime.status_command,
        description="Show non-sensitive MACES health and storage counts",
    )
    ctx.register_command(
        "maces-top",
        runtime.top_command,
        description="Show the highest-weight MACES concepts",
        args_hint="[1-20]",
    )
    return runtime


def _reset_runtime_registry_for_tests() -> None:
    with _RUNTIME_LOCK:
        _RUNTIMES.clear()
