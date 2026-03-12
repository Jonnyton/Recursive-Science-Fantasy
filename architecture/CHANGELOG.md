# Architecture Changelog

Authoritative history of control-plane changes.

Use this for:

- architecture merges
- control-plane rollbacks
- evaluator changes
- routing changes
- governance changes
- schema changes

Each entry should include:

- change ID
- date
- status
- change kind
- commit
- summary
- files touched
- expected gain
- rollback path
- rollback of
- supersedes or rollback ancestry
- learned result

## Entries

### arch-20260311-eval-hardening

- Date: 2026-03-11
- Status: active
- Change kind: forward_change
- Commit: pre-protocol-change
- Scope: control plane
- Summary: hardened the evaluator and writer-package path
- Files: `evaluate.py`, `writer_stack.py`, `series_engine.py`, `persona_system.py`
- Expected gain:
  - evaluate the real writer package
  - reduce wasted paid calls
  - stabilize early-run comparisons
- Rollback path: restore previous evaluator and writer-stack behavior through a follow-up proposal or git revert of the change set
- Rollback of: none
- Supersedes: none
- Learned result:
  - sparse `best/` coverage is a bigger early-run problem than sparse `kept/`
  - catastrophic slop should be blocked before expensive judging
  - persona routing needs both fit and exploration

### arch-20260312-runtime-doc-split-and-tracking

- Date: 2026-03-12
- Status: active
- Change kind: forward_change
- Commit: pre-protocol-change
- Scope: control plane
- Summary: split runtime startup from maintainer memory and added architecture tracking
- Files: `AI_HANDOFF.md`, `LOOP_RUNTIME.md`, `README.md`, `program.md`, `architecture/OUTER_LOOP.md`, `governance/FRONTIER_APPROVAL_POLICY.md`, `updates/`
- Expected gain:
  - keep control-plane memory out of the writer hot path
  - make architecture evolution auditable and reversible
  - ensure future sessions can brief the user on unread changes
- Rollback path: restore the previous docs and remove the `updates/` and changelog flow through a follow-up proposal
- Rollback of: none
- Supersedes: none
- Learned result:
  - maintainer memory and runtime startup need different documents
  - autonomous architecture evolution still needs a durable human-facing brief layer

### arch-20260312-architecture-commit-protocol

- Date: 2026-03-12
- Status: active
- Change kind: forward_change
- Commit: pre-protocol-change
- Scope: control plane
- Summary: required diagnosis and isolated git units for frontier-gated architecture changes and rollbacks
- Files: `governance/proposal_manifest.schema.json`, `governance/FRONTIER_APPROVAL_POLICY.md`, `governance/ARCHITECTURE_COMMIT_PROTOCOL.md`, `governance/prepare_arch_commit.py`, `architecture/OUTER_LOOP.md`, `proposals/`
- Expected gain:
  - safer rollback decisions
  - clearer distinction between architecture issues and output noise
  - rollbackable git history for control-plane changes
- Rollback path: revert this governance layer through a new frontier-reviewed rollback proposal if the protocol proves too heavy
- Rollback of: none
- Supersedes: none
- Learned result:
  - architecture rollbacks need the same review discipline as forward changes
  - output decline alone is not enough evidence for a control-plane rollback

### arch-20260312-conservative-draft-retry

- Date: 2026-03-12
- Status: active
- Change kind: forward_change
- Commit: pre-protocol-change
- Scope: control plane
- Summary: lowered the default draft token cap and added one conservative local retry on catastrophic generation collapse
- Files: `evaluate.py`
- Expected gain:
  - reduce wasted wall-clock time on runaway drafts
  - bound default chapter length more tightly
  - salvage some hard-fail generations with a cheaper fallback attempt
- Rollback path: remove the conservative retry path through a new frontier-reviewed rollback proposal if it proves unhelpful
- Rollback of: none
- Supersedes: none
- Learned result:
  - tighter output caps reduce runtime noticeably
  - the current local model can still catastrophically repeat even under a conservative retry profile

### arch-20260312-full-universe-hidden-benchmark-gate

- Date: 2026-03-12
- Status: implemented (Phase 0-1 scaffold and code)
- Change kind: forward_change
- Commit: pending
- Scope: control plane
- Summary: added a hidden real-book benchmark lane using public-domain books as a quality gate, phased behind a generation stability prerequisite and a validation spike
- Files: `benchmark/` directory (new), `proposals/20260312_full_universe_hidden_benchmark_gate.md`, `proposals/20260312_full_universe_hidden_benchmark_gate.json`
- Expected gain:
  - grounded quality bar against real published prose instead of synthetic scenarios
  - genuine originality pressure via blind pairwise comparison against source chapters
  - empirical validation before committing to full universe-pack infrastructure
- Rollback path: remove `benchmark/` directory; no existing files were modified
- Rollback of: none
- Supersedes: none
- Learned result:
  - collaborative two-agent proposal review with mutual approval catches scope and protocol issues early
  - phased implementation with explicit exit criteria prevents overbuilding
  - Gutenberg body files may have BOM characters that break regex parsing
