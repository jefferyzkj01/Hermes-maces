# Hermes MACES

## The Subconscious Layer for AI Agents

> **MACES is a subconscious learning mechanism that resides beneath the AI memory architecture, enabling an agent to autonomously accumulate experience and dynamically influence future outputs and decisions through adaptive weighting.**

> **Status: Public Beta. Install in Shadow Mode first.** MACES learns local advisory signals; it does not train model weights, replace memory providers, or write canonical knowledge.

MACES stands for **Memory Association & Cognitive Evolution System**. It is designed as a profile-scoped layer beneath explicit memory, retrieval, and knowledge systems. Instead of storing another authoritative answer, MACES gradually learns which concepts, preferences, associations, and behavioral tendencies should receive more or less influence during future inference.

Think of MACES as the AI equivalent of the human subconscious: it quietly accumulates experience beneath explicit memory and gradually shapes future reasoning without replacing conscious knowledge.

## What MACES is

Traditional memory systems answer questions such as:

- What happened before?
- What facts should be recalled?
- Which document or conversation is relevant?

MACES addresses a different question:

> **How should accumulated experience subtly influence the way the agent responds and decides?**

MACES observes bounded, privacy-filtered signals and develops low-weight concept associations over time. Those associations can later provide a small advisory influence to the host agent. They are never treated as facts, instructions, or canonical truth.

```text
Foundation LLM
      ▲
Context / Retrieval
      ▲
Explicit Long-term Memory
      ▲
Canonical Knowledge
      ▲
────────────────────────────────
MACES — Subconscious Learning Layer
────────────────────────────────
• Association Learning
• Preference Formation
• Behavioral Reinforcement
• Adaptive Weighting
• Bounded Influence
```

**Memory remembers. Knowledge answers. MACES gradually shapes how the agent thinks.**

## What MACES is not

MACES does **not**:

- fine-tune or modify foundation-model weights;
- replace Hindsight, profile memory, session history, RAG, or a knowledge base;
- rewrite `USER.md`, `MEMORY.md`, Obsidian, LLM Wiki, or another Canon;
- treat learned associations as verified facts;
- originate tool calls or autonomous actions;
- allow model output to confirm its own learned concepts;
- inject arbitrary or unbounded prompts.

MACES influences inference only through a bounded advisory context produced from validated, profile-local signals.

## How MACES works

```text
Installation
    ↓
Shadow Mode
    ↓
Passive, privacy-filtered observation
    ↓
Concept association and recurrence
    ↓
Adaptive weight formation
    ↓
Bounded influence
    ↓
Future responses and decisions
```

### 1. Observe

MACES receives selected lifecycle events from the host agent. It extracts only bounded candidate concepts and explicitly allowlisted retrieval fields.

### 2. Associate

Repeated concepts, validated retrieval usage, and explicit operator feedback create or adjust profile-local associations. Mention frequency alone does not automatically become a preference.

### 3. Weight

Each signal changes a bounded advisory weight. Negative or corrected feedback can reduce influence. Strict thresholds prevent speculative candidates from entering inference too early.

### 4. Influence

When active, MACES can return a small advisory context before an LLM call. The host model remains responsible for the final response. MACES does not override system instructions, memory, knowledge, or tool policy.

## Shadow Mode

MACES should begin in **Shadow Mode**:

> **Observe first. Influence later.**

During Shadow Mode, MACES can learn privacy-safe signals and build profile-local associations, but it injects no advisory context into model inference.

The intended lifecycle is a per-profile local Shadow period followed by activation. Automatic, persistent per-profile activation is tracked in [Issue #9](https://github.com/visiblemem/Hermes-maces/issues/9). Until that runtime state machine is merged, the current Public Beta uses the explicit `shadow_mode` configuration switch and should remain in Shadow Mode until locally reviewed.

Each profile has an independent MACES database and must be evaluated independently. No repository update, GitHub report, Tag, or maintainer action should be required for an installed profile's eventual local activation.

## Safety contract

- Obsidian/LLM Wiki remains the formal knowledge Canon.
- Hindsight remains responsible for conversational and experiential memory.
- MACES state is disposable advisory state, never a source of truth.
- MACES never trains or modifies model weights.
- Model output cannot confirm or correct a MACES concept.
- MACES never originates tool calls or modifies the Hermes system prompt.
- The default is `shadow_mode: true` with an empty `learnable_tool_fields` allowlist.
- Invalid configuration fails closed into Shadow Mode.
- Disabling MACES removes its hooks without changing Hermes core, Hindsight, Obsidian, Session SQLite, `USER.md`, or `MEMORY.md`.

## Core capabilities

- **Autonomous experience accumulation** — learns from recurring interaction signals without requiring every pattern to be manually authored.
- **Concept association** — forms bounded links between recurring concepts.
- **Preference evolution** — adjusts influence only when evidence supports a directional signal.
- **Adaptive weighting** — reinforces, weakens, or suppresses advisory concepts over time.
- **Profile isolation** — each Hermes profile owns an independent database and learning state.
- **Shadow deployment** — learning can be evaluated without changing model output.
- **Privacy-first persistence** — every stored value crosses a centralized scrub-and-validation boundary.
- **Canonical separation** — promotion remains proposal-only; MACES cannot directly modify formal knowledge.

## Verified compatibility

- Verified Hermes host baseline: `hermes-agent==0.18.2`.
- CI covers Python 3.11, 3.12, and 3.13 on Ubuntu and macOS.
- The blocking real-PluginManager E2E is pinned to Hermes Agent 0.18.2 and Python 3.11.
- `hermes plugins install owner/repo` shallow-clones the repository's default branch. It does not pin a GitHub Release tag.
- `main` is therefore the version users install and must contain only reviewed, CI-green commits.

Windows and Hermes versions outside the listed baseline are not yet part of the verified compatibility matrix.

## Install one profile at a time

1. Select one profile and install without enabling:

   ```bash
   hermes profile use default
   hermes plugins install visiblemem/Hermes-maces --no-enable
   ```

2. Back up the active profile's Hermes `config.yaml`.
3. Copy the safe defaults from [`config.example.yaml`](config.example.yaml) into that profile's config.
4. Keep `shadow_mode: true` and `learnable_tool_fields: {}` until fields have been reviewed.
5. Add only reviewed retrieval tools and query-like string fields when a meaningful Shadow evaluation is required.
6. Enable the plugin and restart the gateway:

   ```bash
   hermes plugins enable hermes-maces --no-allow-tool-override
   hermes gateway restart
   ```

7. Confirm that MACES state exists only at:

   ```text
   <active-profile-HERMES_HOME>/data/maces/
   ```

MACES resolves the trusted profile through `ctx.profile_name` and `hermes_constants.get_hermes_home()`. Its database is stored at:

```text
<active-profile-HERMES_HOME>/data/maces/subconscious.db
```

The plugin checkout must not contain a live database. On first registration, a legacy checkout database is moved into the active profile data directory and recorded as a `migration` audit event.

## Safe default configuration

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
      learnable_tool_fields: {}
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

All numeric values are bounded. Invalid settings force MACES into Shadow Mode and log a warning; they do not prevent Hermes from starting. The repository contains no user `config.yaml`, so plugin updates cannot overwrite profile behavior settings.

### Reviewed tool-learning allowlist

The default allowlist is empty. After reviewing a tool and confirming that only query-like strings are exposed, a profile may explicitly add fields such as:

```yaml
learnable_tool_fields:
  session_search:
    - query
  web_search:
    - query
```

Do not allowlist write tools, file contents, credentials, paths, complete result bodies, or arbitrary unreviewed fields.

A tool call can reinforce concepts only when all of the following are true:

```text
status == "ok"
error_type is None
tool_name is present in learnable_tool_fields
```

Only explicitly listed string fields are read. Full arguments and result bodies are never persisted. Failed, cancelled, approval-denied, unlisted, or status-ambiguous calls do not create a positive signal.

## Traditional Chinese learning

Passive Traditional Chinese text uses a two-stage path:

1. a bounded complete concept becomes a low-weight candidate;
2. it becomes a zero-weight pattern only after recurring in at least three distinct sessions.

Candidates never enter influence. Explicit operator feedback or a validated successful retrieval can create a complete concept immediately. Configurable stopwords and bounded negation prefixes such as `不要`, `別`, `不喜歡`, and `避免` suppress candidate creation. MACES does not call an additional model for extraction.

## Operator commands

Feedback is available only as an explicit operator command, never as a model tool:

```text
/maces-feedback confirmed 美學,建築設計
/maces-feedback corrected 過度留白,紫色漸層
/maces-status
/maces-top 10
```

Invalid feedback returns usage text and writes nothing. Status output is aggregate-only and never displays raw sensitive material.

## Privacy and reliability

Every persistence path crosses `maces.secure_store.CognitiveStore`. It scrubs credentials, tokens, JWT/Bearer values, email addresses, phone and long-digit shapes, absolute paths, sensitive URLs, long identifiers, and high-entropy candidates before SQLite writes.

SQLite uses WAL, a busy timeout, per-store serialization, and bounded whole-transaction retries on fresh connections. Influence reads bounded indexed queries and emits no more than the configured item and character budgets. Staged research content is never queried by the influence engine.

Report suspected credential retention, profile-boundary violations, path disclosure, or unintended Canon writes through the private process in [`docs/SECURITY.md`](docs/SECURITY.md). Never upload a real MACES database, Vault, Session SQLite file, credential, or private absolute path.

## Known limitations

- Patterns are speculative advisory signals, not facts.
- Strict learning gates may produce little data; this is expected behavior.
- Traditional Chinese segmentation uses bounded rules and is not full semantic understanding.
- Automatic per-profile Shadow activation is not yet implemented; see [Issue #9](https://github.com/visiblemem/Hermes-maces/issues/9).
- Only the listed Hermes, Python, and operating-system combinations are verified.
- Unsafe user-added allowlist fields can expand privacy risk.
- MACES provides no cloud sync, cross-device synchronization, or remote backup.
- Promotion remains proposal-only; MACES does not automatically write Obsidian or another Canon.

## Disable, remove, and clear data

Disable first:

```bash
hermes plugins disable hermes-maces
hermes gateway restart
```

Confirm ordinary Hermes behavior, Hindsight recall, Canon files, Session SQLite, and profile memory remain normal. Preserve the MACES database for local investigation.

Remove the plugin only after that verification:

```bash
hermes plugins remove hermes-maces
```

To clear MACES state, stop the gateway, verify the active profile, and delete only:

```text
<active-profile-HERMES_HOME>/data/maces/
```

Never delete Hindsight data, Obsidian, Hermes Session SQLite, `USER.md`, `MEMORY.md`, or Hermes core files as part of MACES cleanup.

## Integration with Hermes and other agents

MACES is currently built on top of the **Hermes Agent** runtime and uses its lifecycle hooks, trusted profile isolation, plugin architecture, and local configuration model.

The subconscious learning mechanism itself is conceptually framework-agnostic, but it should not be installed blindly into another AI agent. Before integration, the target agent must understand—or be analyzed by an AI agent that understands—its execution lifecycle, memory hierarchy, trust boundaries, tool hooks, profile model, and extension mechanisms. MACES must then be adapted to that host architecture so that subconscious influence remains bounded and does not interfere with explicit memory, canonical knowledge, system instructions, or security policy.

> **MACES is not intended to replace an AI agent. It is intended to become the subconscious layer beneath one.**

## Vision

Just as humans develop intuition through accumulated experience beneath conscious thought, MACES enables AI agents to gradually develop their own subconscious—quietly shaping future reasoning through adaptive weighting while leaving the foundation model, explicit memory, and canonical knowledge untouched.

## Development and release checks

```bash
python -m pip install -e '.[dev]'
ruff check src tests __init__.py
python -m compileall -q src __init__.py
pytest -q -m "not e2e"
python -m pip install 'hermes-agent==0.18.2'
pytest -q -m e2e
python -m pip install build twine
python -m build
python -m twine check dist/*
```

See [`SUBCONSCIOUS.md`](SUBCONSCIOUS.md), [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md), [`docs/SECURITY.md`](docs/SECURITY.md), [`docs/INSTALLATION.md`](docs/INSTALLATION.md), and [`docs/PUBLIC_RELEASE_GUIDE.md`](docs/PUBLIC_RELEASE_GUIDE.md).
