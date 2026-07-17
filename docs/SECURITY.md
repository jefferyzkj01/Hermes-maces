# Security Boundaries

## Trust

Only `ctx.profile_name` is trusted for profile identity. Commands, hooks, model output, tool data, and persisted legacy rows are untrusted. Operator confirmation is accepted only through the raw-string `/maces-feedback` slash command.

MACES registers no model tool and never originates a tool call.

## Central privacy fence

All text-bearing persistence passes through `CognitiveStore`. Before a write, the recursive scrubber removes or rejects:

- API keys, generic tokens, OAuth, JWT, Bearer, password, credential, authorization, cookie, and session-token fields;
- Base64/hex runs of at least 20 characters and high-entropy candidates;
- email and phone shapes, digit runs of at least eight characters;
- absolute POSIX, UNC, home-relative, and drive-letter paths;
- URLs containing credentials or query/fragment data.

Rejected content is not stored or hashed. Only a `scrubbed_candidates` count may be audited.

## Feedback command

```text
/maces-feedback confirmed 美學,建築設計
/maces-feedback corrected 過度留白 紫色漸層
```

The handler receives `raw_args: str`, uses a strict `shlex`-based parser, accepts only `confirmed`/`corrected`, and validates each complete concept at 2–32 characters. Malformed input writes nothing.

## Tool learning

Learning is deny-by-default. It requires an explicit `ok` status, no `error_type`, and an allowlisted tool. Only named safe string fields are considered. The result contributes only aggregate metadata such as length and success state; its body is not stored.

## Verification

Privacy regression tests scan `subconscious.db`, `subconscious.db-wal`, and `subconscious.db-shm` while a read transaction keeps WAL state available. The real PluginManager E2E also verifies that Hindsight, Obsidian, session SQLite, and profile memory sentinels remain byte-identical.
