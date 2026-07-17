# Architecture

```text
Hermes profile
  ├─ Hindsight / session / profile memory     (host-owned)
  ├─ Obsidian / LLM Wiki                      (Canon)
  └─ native plugin hooks
       └─ profile-bound MACES runtime
            ├─ extraction and valence gates
            ├─ secure CognitiveStore
            │    └─ HERMES_HOME/data/maces/subconscious.db
            ├─ bounded InfluenceEngine
            └─ explicit slash commands
```

## Loading and profile binding

Hermes loads the repository as a namespaced package. The root entrypoint uses a relative import so multiple profile/plugin processes do not depend on a global `maces` module. `register(ctx)` normalizes and validates trusted `ctx.profile_name`, resolves the active home through `hermes_constants.get_hermes_home()`, and creates or reuses a lock-protected runtime keyed by profile and home.

Hook kwargs are never profile inputs. A forged `profile_id` is inert.

## Runtime lifecycle

Pending passive extraction is keyed by `(profile, session_id, turn_id)` and protected by an `RLock`. Completion consumes it; API errors and session end/finalize/reset hooks clear it. Daily decay is guarded by `last_decay_at`, not by an assumption that every session hook represents a unique day.

All hook exceptions degrade MACES only. Hermes continues normally.

## Persistence

`maces.secure_store.CognitiveStore` owns every SQL write. Its context manager yields exactly once. Operations requiring lock retry wrap the entire transaction and open a fresh SQLite connection on each bounded attempt. WAL, `busy_timeout`, foreign keys, and per-store serialization are enabled.

Caps are enforced for patterns, edges, candidates, and open gaps. Pattern pruning deletes incident edges. Edge normalization is limited to nodes changed by the current operation. Decay and pruning are processed in bounded batches.

## Query path

The influence engine uses only:

- `get_relevant_patterns(keys, limit)`
- `get_connected_edges(keys, limit)`
- `get_open_gaps(limit)`

There are no full-table model-facing reads. A second render-side validation fence rejects malformed legacy labels.
