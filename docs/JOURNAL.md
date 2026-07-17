# Journal Semantics

The journal records selected state transitions in the same transaction as the mutation when that transition is audited. Examples include event observation, migration, decay, staging, learning proposals, promotion proposals, and scrub counters.

It is an operational audit aid only. It is not complete event sourcing, does not retain raw user messages or full tool arguments, and cannot be assumed to reconstruct the whole database.
