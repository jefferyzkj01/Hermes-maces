# Safe Rollout

1. Install one profile with `--no-enable`.
2. Add two or three safe retrieval allowlist entries.
3. Enable with `shadow_mode: true`.
4. Run for at least seven days.
5. Inspect DB/WAL/SHM privacy, database growth, latency, scrub/error counts, negation behavior, and concept quality.
6. Confirm Hindsight, Obsidian, session SQLite, profile memory, PWA, Discord, CLI, gateway, and cron remain stable.
7. Enable bounded influence only after manual review.
8. Repeat separately for every profile.

A near-empty high-weight table is acceptable. Strict valence and deny-by-default learning intentionally prefer false negatives over fabricated preference signals.
