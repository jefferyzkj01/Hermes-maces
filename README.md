# Hermes MACES

**Memory-Agnostic Cognitive Evolution Substrate**

Hermes MACES is a standalone cognitive substrate that sits beneath an agent runtime and above any memory or knowledge provider. It observes normalized events, accumulates machine-oriented cognitive state, identifies epistemic gaps, proposes bounded learning work, stages research artifacts, and routes promotion proposals through an external approval authority.

MACES does not assume Obsidian, Hindsight, Mem0, Graphiti, SQLite session memory, vector databases, or any specific LLM framework.

## Core boundary

```text
Agent runtime
    ↓ CognitiveEvent
Hermes MACES
    ├─ pattern substrate
    ├─ epistemic gap map
    ├─ learning queue
    ├─ staging sandbox
    └─ evolution journal
    ↓ PromotionProposal
External Approval Gate
    ↓ authorized write
Any canonical knowledge system
```

## Safety invariants

- MACES never treats inferred patterns as canonical facts.
- Research output is written only to Staging.
- Canonical writes require an external, digest-bound authorization grant.
- Provider adapters normalize data but do not change source authority.
- Runtime influence is disabled by default and activated by policy level.
- Every state transition is auditable and replayable.

## Status

Clean-room implementation in progress. The repository is intentionally separate from earlier Hermes memory-system specifications to avoid authority and migration ambiguity.
