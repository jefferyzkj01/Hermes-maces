# After installation

1. Confirm `<profile-HERMES_HOME>/data/maces/subconscious.db` is the only MACES database.
2. Keep `shadow_mode: true` for at least seven days.
3. Use `/maces-status` to inspect aggregate health without exposing raw data.
4. Scan database, WAL, and SHM for planted test secrets.
5. Verify Hindsight, Obsidian, session SQLite, profile memory, and normal Hermes responses are unchanged.
6. Enable bounded influence only after manual review.

Rollback immediately with `hermes plugins disable hermes-maces` and a gateway restart if any invariant fails.
