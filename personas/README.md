# Persona Registry

Personas are writing overlays for exploration and controlled specialization.

They do not replace the shared writing foundation in `writing_system.md`.

## Rules

- Personas are narrow.
- Personas are evaluated on writing outcomes.
- Personas do not browse or judge.
- Draft personas can vary emphasis and attack angle.
- Final series output should use a stable final-voice persona.
- Routing policy changes are architecture-level changes.

## Routing

The current router should:

- prioritize scenario fit
- consider weakness targeting
- use persona outcome history
- avoid repeating recent losing fits
- give a small exploration bias to long-unused personas

The exploration bias is intentionally small. It exists to prevent one overlooked persona from being starved forever, not to pick poor fits for novelty.

## Current Files

- `index.json`
- `mythic_wonder.json`
- `character_intimacy.json`
- `political_intrigue.json`
- `uncanny_originality.json`
- `action_tactician.json`
- `series_voice.json`

## Suggested Usage

1. Route the scenario to candidate draft personas.
2. Compare openings or outlines when planning is enabled.
3. Draft with the strongest candidate or pair.
4. Normalize long-series output through `series_voice` when needed.
