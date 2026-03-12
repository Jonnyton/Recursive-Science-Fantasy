# Architecture Commit Protocol

This protocol exists so control-plane changes are grouped into explicit, rollbackable git units.

## Rule

One frontier-gated architecture proposal should map to one isolated git unit.

That git unit may be:

- one commit
- or one very small stack of tightly related commits

It should never be mixed with unrelated craft edits.

## Why

Architecture changes must be:

- attributable
- reviewable
- rollbackable
- learnable later

If the git history mixes control-plane edits with unrelated output work, later diagnosis becomes weak.

## Required Metadata

Every frontier-gated proposal should define:

- proposal ID
- change kind: `forward_change` or `rollback`
- branch name
- commit message
- files touched
- rollback ancestry

## Branch Naming

Use a proposal-scoped branch name:

- `codex/arch-<proposal_id>`

## Commit Messages

Forward change:

- `arch:<proposal_id>: <short-summary>`

Rollback:

- `arch-rollback:<proposal_id>: revert <rollback_of>`

## Isolation Rule

The commit unit should include only files listed in the proposal.

Do not mix:

- `writing_system.md`
- kept-story artifacts
- unrelated experiment outputs

into an architecture commit unit unless they are explicitly part of the approved proposal.

## Rollback Rule

A rollback is not a blind git revert.

It must have:

- its own proposal ID
- `change_kind: rollback`
- `rollback_of`
- frontier approval
- its own changelog entry
- its own inbox entry if user-visible

## Changelog Rule

After merge, record the actual merge commit hash in `architecture/CHANGELOG.md`.

If the change predates this protocol, mark the commit as `pre-protocol-change`.

## Decision Rule

Do not propose an architecture rollback only because recent outputs declined.

First distinguish:

- output noise
- craft-layer regression
- local model instability
- true control-plane regression

The frontier reviewer is the final judge on that distinction.
