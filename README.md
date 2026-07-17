# Hermes MACES

MACES is a **low-weight, unverified advisory layer** for Hermes Agent. It learns only bounded preference signals, concept associations, Traditional Chinese candidates, and epistemic gaps. It does not replace Hindsight, profile memory, session history, or Obsidian/LLM Wiki, and it never writes Canon directly.

## Safety contract

- Obsidian/LLM Wiki remains the only formal knowledge Canon.
- Hindsight remains responsible for conversational and experiential memory.
- MACES state is disposable advisory state, never a source of truth.
- Model output cannot confirm or correct a MACES concept.
- MACES never originates tool calls or modifies the Hermes system prompt.
- Disabling the plugin removes its hooks without changing Hermes core, Hindsight, Obsidian, session SQLite, or profile `MEMORY.md`.

## Compatibility

The real-PluginManager CI job is pinned to `hermes-agent==0.18.2`. The plugin targets Python 3.11–3.13 and uses the native Hermes general-plugin contract.

## Install one profile at a time

```bash
hermes profile use default
hermes plugins install jefferyzkj01/Hermes-maces --no-enable
```

Copy the relevant section from [`config.example.yaml`](config.example.yaml) into the active profile's Hermes `config.yaml`. User behavior settings belong in the profile configuration, not in the plugin checkout.

Before a meaningful shadow evaluation, add only two or three successful retrieval tools and their safe string fields to `learnable_tool_fields`. The default allowlist is intentionally empty.

Then enable and restart:

```bash
hermes plugins enable hermes-maces
hermes gateway restart
```

MACES resolves the active profile through trusted `ctx.profile_name` and `hermes_constants.get_hermes_home()`. Its database is always:

```text
<active-profile-HERMES_HOME>/data/maces/subconscious.db
```

The plugin checkout must not contain a live database. On first registration, a legacy checkout database is moved into the active profile data directory and the transition is recorded as a `migration` audit event.

## Configuration

```yaml
plugins:
  enabled:
    - hermes-maces
  entries:
    hermes-maces:
      shadow_mode: true
      influence:
        max_items: 4
        max_chars: 700
        minimum_weight: 0.10
      learnable_tool_fields:
        web_search:
          - query
      limits:
        max_patterns: 5000
        max_edges: 20000
        max_open_gaps: 500
        max_candidates: 5000
      maintenance:
        decay_interval_hours: 24
        prune_batch_size: 500
      traditional_chinese:
        candidate_min_sessions: 3
        stopwords:
          - 我們
          - 你們
          - 這個
          - 那個
```

All numeric values are bounded. Invalid settings force MACES into shadow mode and log a warning; they do not prevent Hermes from starting.

### Tool-learning gate

A tool call can reinforce concepts only when all of the following are true:

```text
status == "ok"
error_type is None
tool_name is present in learnable_tool_fields
```

Only explicitly listed string fields are read. Full arguments and result bodies are never persisted. Failed, cancelled, approval-denied, unlisted, or status-ambiguous calls do not create a positive signal.

### Traditional Chinese learning

Passive Traditional Chinese text enters a two-stage path:

1. a bounded full concept becomes a low-weight candidate;
2. it becomes a zero-weight pattern only after recurring in at least three distinct sessions.

Candidates never enter influence. Explicit feedback or a validated successful retrieval can create the complete concept immediately. Configurable stopwords and bounded negation prefixes such as `不要`, `別`, `不喜歡`, and `避免` suppress candidate creation. MACES does not call an additional model for extraction.

## Slash commands

Feedback is available only as an explicit operator command, never as a model tool:

```text
/maces-feedback confirmed 美學,建築設計
/maces-feedback corrected 過度留白,紫色漸層
/maces-status
/maces-top 10
```

Invalid feedback returns usage text and writes nothing. Status output is aggregate-only and never displays raw sensitive material.

## Shadow rollout

Keep `shadow_mode: true` for at least seven days. Shadow mode records safe signals but injects no advisory context. Review these acceptance conditions:

- database, WAL, and SHM contain no planted sensitive strings;
- the database exists only under the correct profile home;
- complaints and negations do not reinforce preferences;
- concepts are not sentence fragments;
- PWA, Discord, CLI, gateway, and cron operation remain stable;
- latency is not perceptible;
- Hindsight, Obsidian, session SQLite, and profile memory remain unchanged.

With strict valenced learning, a nearly empty high-weight table is expected and is not a failure. Learning richness is not a shadow acceptance criterion.

After review, set `shadow_mode: false` for that profile and restart its gateway. Repeat the process separately for every other profile.

## Privacy and reliability

Every persistence path crosses `maces.secure_store.CognitiveStore`. It scrubs credentials, tokens, JWT/Bearer values, email addresses, phone and long-digit shapes, absolute paths, sensitive URLs, long identifiers, and high-entropy candidates before SQLite writes. SQLite uses WAL, a busy timeout, per-store serialization, and bounded whole-transaction retries on fresh connections.

Influence reads only bounded indexed queries and emits at most the configured item and character budgets. Staged research content is never queried by the influence engine. Promotion creates a proposal only; no code path writes Obsidian or another canonical store.

## Disable, remove, and clear data

```bash
hermes plugins disable hermes-maces
hermes gateway restart
```

Confirm ordinary Hermes behavior, Hindsight recall, Canon files, session SQLite, and profile memory are unchanged. Preserve the MACES database for inspection. To remove the plugin later:

```bash
hermes plugins remove hermes-maces
```

To clear MACES state, stop Hermes and delete only:

```text
<active-profile-HERMES_HOME>/data/maces/
```

Never delete Hindsight data, Obsidian, Hermes session SQLite, profile `MEMORY.md`, or Hermes core files as part of MACES cleanup.

## Development

```bash
python -m pip install -e '.[dev]'
ruff check src tests __init__.py
pytest -q -m "not e2e"
python -m pip install hermes-agent==0.18.2
pytest -q -m e2e
```

See [`SUBCONSCIOUS.md`](SUBCONSCIOUS.md), [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md), [`docs/SECURITY.md`](docs/SECURITY.md), and [`docs/INSTALLATION.md`](docs/INSTALLATION.md).
