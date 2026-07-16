# SUBCONSCIOUS.md — The Subconscious Layer

Status: normative v1 specification

MACES is the subconscious layer embedded beneath Hermes's existing memory architecture. Existing episodic memory, canonical knowledge, and session history remain the conscious architecture.

## Definition

The layer passively absorbs operator-driven usage traces, consolidates them into weighted concept nodes, associations, and epistemic gaps, and communicates with Hermes through exactly two channels:

1. **Influence** — advisory bias injected through `pre_llm_call`; never facts and never staged content.
2. **Surfacing** — digest-bound promotion proposals through an external approval gate.

It never speaks with authority, never originates tool calls, and never writes canon directly.

## Event sources

- `retrieval.used`
- `answer.confirmed`
- `answer.corrected`
- `task.completed`
- `decision.confirmed`
- `gap.observed`

All ingestion is idempotent.

## State

- `patterns` — weighted concept nodes
- `edges` — co-occurrence associations
- `gaps` — epistemic gap map
- `learning_proposals`
- `staged_artifacts`
- `promotion_proposals`
- `journal`

State is disposable and must never be treated as a source of truth.

## Dynamics

- Reinforcement: `w ← w + α(1 − w)`, `α = 0.10`
- Correction penalty: `w ← w(1 − β)`, `β = 0.35`
- Decay: `w ← w exp(−days / τ)`, `τ = 45 days`
- Prune below `0.02`
- Co-occurring concepts reinforce edges.
- Outbound edge weight is normalized above `3.0`.
- Staging-originated events feed no weights.

## Influence

`influence(concepts)` returns at most eight statistics-only items under:

```text
[intuition — advisory, unverified]
```

It may contain weighted concept labels, association labels, and gap topics. It must never query, quote, or summarize `staged_artifacts`.

## Surfacing

Subconscious state becomes explicit only through a promotion proposal and external digest-bound authorization. Grant issuance and canonical writes live on the Hermes side.

## Learning

Observed gaps may create bounded learning proposals. Research output goes only to staging. Nothing in staging is retrievable by the conscious system until approved and surfaced.

## Invariants

1. Subconscious state is never canonical.
2. Influence is never fact.
3. Research writes only to staging.
4. Canon and rule writes require external authorization.
5. No tool action originates from MACES.
6. Every transition is journaled.
7. Disabling MACES leaves Hermes fully functional.
