# Outer Architecture Loop

This loop improves the control plane without broadening the writer product.

It is separate from routine chapter experimentation.

## Goal

Make the system better at improving itself:

- better routing
- better evaluation
- better memory
- better research distillation
- better budget use
- better long-series continuity support

The writer product should remain narrow and writing-focused while the control plane becomes more capable.

## Core Rule

All architecture work is proposal-driven.

Local models can discover problems, draft changes, and run cheap evidence.
Frontier review is required before merge for infrastructure, evaluator, schema, routing, and governance changes.
This includes rollbacks.

## When To Enter The Outer Loop

Enter the outer loop when any of these is true:

- every 12 routine loops
- the same weak dimension appears in 3 of the last 5 experiments and craft changes are not fixing it
- persona routing repeatedly chooses losing plans
- evaluator drift or grader noise is suspected
- continuity failures recur despite stable craft guidance
- paid escalation rate becomes too high for the yield
- there is a credible new infrastructure idea with evidence

## Inputs

Use these sources:

- `results.tsv`
- recent `experiments/`
- `personas/persona_stats.json`
- `research/weakness_tracker`
- proposal backlog under `proposals/`
- current architecture docs

Do not use raw writer outputs alone as evidence for architecture changes.
Poor output can be a symptom, but it is not by itself proof that the architecture is at fault.

## Proposal Lanes

### Craft lane

Changes that improve writing quality inside approved product boundaries:

- `writing_system.md`
- persona content
- craft cards

These can move quickly through the inner loop.

### Architecture lane

Changes that alter the control plane:

- evaluator logic
- routing policy
- memory schema
- research workflow
- governance rules
- budget or escalation policy

These must go through the outer loop.

## Proposal Procedure

1. Name one bottleneck.
2. Write one proposal using `proposals/TEMPLATE.md`.
3. Diagnose whether the problem is architectural or only a craft/output issue.
4. Define one benchmark ladder:
   - smoke check
   - local regression
   - holdout or audit check
   - budget impact check
5. Define one isolated git unit for the proposal.
6. Run local evidence collection.
7. Keep the benchmark fixed while testing the change.
8. Submit for frontier review.
9. Merge only if approved.
10. Append the change to `architecture/CHANGELOG.md`.
11. Add a short user-facing summary to `updates/USER_INBOX.md`.
12. Log the result in `AI_HANDOFF.md`.
13. If the change affects operators, update `LOOP_RUNTIME.md` too.

## One-Variable Rule

Do not change both:

- the benchmark or grading rule
- and the strategy being benchmarked

in the same proposal.

If the benchmark must change, do that first as its own proposal.

## Review Standard

Every architecture proposal should answer:

- What exact problem is being fixed?
- Why is this problem architectural rather than just output variance?
- What is the expected gain?
- What regressions are possible?
- What is the hot-path tax?
- What is the budget impact?
- How is rollback handled?
- How will the change be recorded for later learning and future briefings?
- What isolated commit unit will carry the change?

## Suggested Cadence

### Every 5 loops

- weakness review
- persona usage review
- research queue refresh
- craft-card review

### Every 12 loops

- architecture review
- proposal triage
- benchmark sanity review
- escalation-rate review

### Every keep or notable failure cluster

- ask whether the issue is really craft or actually control-plane behavior

## Good Outer-Loop Targets

- cheap-gate quality
- focus-group calibration
- pairwise escalation thresholds
- persona routing policy
- series state schema
- contradiction detection
- research-to-craft-card pipeline
- proposal ranking and triage

## Bad Outer-Loop Targets

- stuffing more infrastructure context into the writer
- letting the writer browse raw research
- letting judges see proposal notes or runtime memory
- changing multiple control-plane subsystems without isolation
- relying on frontier models for routine bulk labor
- rolling back architecture just because recent output got worse without proving the control plane caused it

## Why This Exists

The project should improve two things over time:

1. the writer product
2. the machinery that improves the writer product

Keeping those loops separate is what lets the architecture become smarter without turning the writer into a general-purpose agent.
