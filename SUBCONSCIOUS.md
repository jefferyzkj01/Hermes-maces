# MACES Subconscious Advisory Specification

## Position in Hermes

MACES is a subordinate advisory subsystem. Hindsight owns conversation and experience memory. Obsidian/LLM Wiki remains the formal knowledge Canon. Session history and profile memory remain host-owned. MACES neither replaces nor controls those systems.

## Inputs

MACES receives passive lifecycle traces from native Hermes hooks and explicit operator feedback from `/maces-feedback`. It never accepts profile selection from hook kwargs, model output, tool arguments, commands, or environment-provided profile identifiers. Profile binding occurs once from trusted `ctx.profile_name`; the active home is resolved through the Hermes home API.

## State

Per-profile state consists of events, weighted patterns, associations, Traditional Chinese candidates, gaps, learning proposals, staged artifacts, promotion proposals, metadata, and selected audit records. This state is disposable and is not a factual authority.

The database path is `<profile-HERMES_HOME>/data/maces/subconscious.db`.

## Signal semantics

- `task.completed`: occurrence/co-occurrence only; it does not raise node or edge weight.
- validated `retrieval.used`: low positive reinforcement.
- explicit `answer.confirmed`: positive reinforcement.
- explicit `answer.corrected`: asymmetric penalty.
- staged-origin material and non-operator events cannot reinforce the substrate.
- passive Traditional Chinese candidates are excluded from influence until recurrence across the configured number of distinct sessions promotes them to zero-weight patterns.

## Influence

Influence is a compact `[intuition — advisory, unverified]` block containing only validated pattern labels, association labels, and open gap topics that clear the minimum weight. It is bounded by a shared item budget and a hard character budget. When no signal clears the threshold, the result is empty. Shadow mode always injects nothing.

Influence never reads staged artifact content, raw events, complete tables, or Canon. Current user instructions and approved knowledge always outrank MACES.

## Surfacing

Staging is dark state. Promotion creates a digest-bound proposal with source and status metadata. Until a separately trusted Canon integration exists, proposals cannot modify Obsidian or any other canonical store and cannot be promoted automatically.

## Journal

The journal is an audit trail of selected transitions. It is not a complete event-sourcing system and does not promise full database reconstruction. Raw user messages, complete tool arguments, and sensitive values are prohibited.

## Failure behavior

Runtime hook failures are contained inside MACES. They do not block a Hermes response, tool result, or session lifecycle transition. Disabling MACES removes advisory behavior while leaving host memory and Canon unchanged.
