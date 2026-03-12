# V4 Architecture Spec

## Goal

Build the best fantasy writer possible while keeping the writer product narrowly focused on writing.

The system is split into two planes:

1. Product plane
   The deployable fantasy-writer product in `agent/`.
2. Control plane
   The research, evaluation, governance, memory, and packaging system that improves the product over time.

## Doc Split

- `LOOP_RUNTIME.md`: active loop startup and operator cadence
- `AI_HANDOFF.md`: maintainer memory and control-plane continuity
- `architecture/OUTER_LOOP.md`: architecture self-improvement process

This split is intentional. Do not use maintainer memory as hot-path runtime input.

## Core Principles

- The writer learns only writing.
- Heavy token use stays local.
- Frontier models are sparse alpha reviewers, not routine workers.
- Architecture changes require frontier approval.
- Craft changes can iterate quickly inside approved product boundaries.
- Online research is converted into small approved artifacts before the writer sees it.

## Product Plane

Artifacts:

- `writing_system.md`
- `agent/LATEST.md`
- approved persona overlays from `personas/`
- approved craft cards from `craft_cards/`
- approved exemplars from `best/`

Responsibilities:

- outline
- draft
- revise
- maintain chapter voice
- maintain series voice

Non-responsibilities:

- web research
- eval design
- git operations
- infrastructure changes
- proposal approval
- budget decisions

## Control Plane

Subsystems:

- evaluator
- focus group
- persona router
- research lane
- proposal lane
- lore and continuity support
- packager
- frontier reviewer

Responsibilities:

- gather and distill research
- track weak dimensions
- create craft cards
- manage proposals
- maintain eval and memory systems
- govern architecture changes

## Runtime Funnel

1. Draft locally.
2. Run anti-slop checks.
3. Run one cheap local judge.
4. Run the 6-reader focus group only if the cheap gate passes.
5. Escalate only strong or ambiguous candidates.
6. Ratchet with frontier review when needed.

## Loops

### Inner loop: craft evolution

Purpose:
Improve the writer product on writing quality.

Editable surfaces:

- `writing_system.md`
- approved persona overlays
- approved craft cards

Workflow:

1. Identify the weak dimension from recent experiments.
2. Pull relevant personas and craft cards.
3. Produce drafts locally.
4. Score locally.
5. Escalate only when warranted.
6. If promoted, rebuild `agent/LATEST.md`.

### Outer loop: architecture evolution

Purpose:
Improve the control plane itself.

Editable surfaces:

- evaluator behavior
- routing policy
- state schema
- memory design
- research workflow
- governance rules

All outer-loop changes are proposal-driven and architecture-gated.

See `architecture/OUTER_LOOP.md`.

## Cost Policy

### Local-first

Local models do:

- chapter generation
- persona exploration
- outlining
- revision
- focus-group judging
- continuity extraction
- state updates
- research summarization
- craft-card drafting
- proposal drafting

### Frontier-limited

Frontier models do:

- architecture approval
- sparse calibration
- hard tie-breaks
- periodic audits
- final review of infrastructure proposals

## Product Invariant

The writer product must improve at writing without becoming a general-purpose research or ops agent.
