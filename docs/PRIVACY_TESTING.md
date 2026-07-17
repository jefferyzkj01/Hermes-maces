# Privacy Testing

Tests plant credential assignments, generic tokens, Bearer/JWT-like values, email addresses, phone and digit shapes, absolute paths, credential/query URLs, long identifiers, and high-entropy strings across events, metadata, journal payloads, gaps, candidates, proposals, staging, and promotion identifiers.

The raw bytes of all existing files below are scanned before the final SQLite checkpoint:

```text
subconscious.db
subconscious.db-wal
subconscious.db-shm
```

No planted secret may appear. Parsed-row assertions alone are insufficient.
