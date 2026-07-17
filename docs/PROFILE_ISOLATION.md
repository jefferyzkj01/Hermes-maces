# Profile Isolation Contract

A runtime is bound at `register(ctx)` from normalized and validated `ctx.profile_name`. The active Hermes home is resolved by `hermes_constants.get_hermes_home()` and the database is `<HERMES_HOME>/data/maces/subconscious.db`.

Profile-like values supplied in hook kwargs, tool arguments, command text, model output, or plugin-specific environment variables are ignored. Runtime caching is protected by a lock and keyed by both profile name and resolved home.

Legacy checkout databases are moved out of the repository on first registration. Two profile homes therefore use disjoint SQLite files even when session and turn identifiers are identical.
