# Frontier Approval Policy

## Rule

Architecture changes require approval from the latest available frontier reviewer model.
Architecture rollbacks require approval from the latest available frontier reviewer model too.

Local models may discover problems, draft proposals, run cheap tests, and prepare evidence.
They may not merge architecture, evaluator, schema, routing, or governance changes on their own.

## Frontier-Gated Surfaces

- `evaluate.py`
- `series_engine.py`
- `program.md`
- files under `architecture/`
- files under `governance/`
- routing policy files
- evaluator thresholds and promotion logic
- state and memory schemas

## Locally Ratcheted Surfaces

- `writing_system.md`
- `agent/` output artifacts
- approved persona content under `personas/`
- approved craft cards under `craft_cards/`
- research notes and registries

## Proposal Classes

- `craft_pr`
  Writing-focused changes inside approved product boundaries.
- `persona_pr`
  Adds or modifies persona overlays inside the approved persona framework.
- `infra_pr`
  Changes control-plane behavior.
- `eval_pr`
  Changes grading, thresholds, or promotion logic.
- `schema_pr`
  Changes canon, memory, or state schemas.

## Merge Rule

- `craft_pr` and `persona_pr` can be promoted through the local loop, then optionally audited.
- `infra_pr`, `eval_pr`, and `schema_pr` require explicit frontier approval before merge.
- A rollback touching frontier-gated surfaces requires explicit frontier approval before merge.

## Required Evidence For Frontier Review

Every frontier-gated proposal should include:

- one clear problem statement
- one diagnosis explaining why the issue is architectural instead of just output variance or craft failure
- one expected gain
- smoke-check results
- local regression results
- holdout or audit plan
- budget impact
- hot-path impact
- rollback plan
- changelog entry plan
- user-brief entry plan
- isolated commit-unit plan

## One-Variable Rule

Do not change the benchmark and the strategy in the same proposal.

If the benchmark, grading rubric, or promotion rule needs to change, submit that separately before using it to justify a strategy change.

## Review Standard

Frontier approval should evaluate:

- evidence quality
- diagnosis quality
- expected gain
- regression risk
- budget impact
- hot-path tax
- rollback clarity
- risk of broadening the writer product beyond writing

The frontier reviewer should reject architecture changes or rollbacks when the evidence looks more like:

- writer-quality fluctuation
- scenario-specific output noise
- local model instability without a control-plane root cause
- a craft-layer issue mislabeled as architecture
