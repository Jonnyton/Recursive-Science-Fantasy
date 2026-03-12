# autoresearch-fantasy

*Adapted from [karpathy/autoresearch](https://github.com/karpathy/autoresearch)*

Two AI agents iteratively improve a fantasy writing craft system. Qwen 3.5 (local, free) generates ~4000-word chapters and screens them. Claude (API) confirms only the promising results. A research agent modifies the writing system one change at a time, keeping only changes that both models agree are improvements.

**Cost: ~$3 per 100 experiments** (Claude only scores the ~30% that pass Qwen screening).

## Filter chain architecture

```
Every experiment:
  Pass 1 (free)  →  Qwen writes chapter  →  Qwen scores it
                          ↓
                    Score improved?
                     ↓           ↓
                    YES          NO → revert (saved ~$0.11)
                     ↓
  Pass 2 (~$0.11) →  Claude scores SAME chapter
                          ↓
                    Both agree?
                     ↓           ↓
                    YES          NO → revert
                     ↓
                   KEEP ✓
```

Two independent models agreeing is a stronger signal than either alone.

## Quick start

```bash
# 1. Ollama with Qwen 3.5
ollama run qwen3.5    # pulls if needed, ctrl+D to exit

# 2. Dependencies
pip install openai anthropic
# or: uv sync

# 3. API key (for Claude critic)
export ANTHROPIC_API_KEY="sk-ant-..."

# 4. Git init
cd autoresearch-fantasy
git init && git add -A && git commit -m "initial commit"

# 5. Test Pass 1 (free, ~3-8 min)
python evaluate.py

# 6. Test full filter chain
python evaluate.py --pass2
```

## Running the agent

Open Claude Code in this directory:

```
Hi, have a look at program.md and let's kick off a new experiment!
```

## Commands

```bash
python evaluate.py                # Pass 1: Qwen writes + scores (free)
python evaluate.py --pass2        # Both passes: Qwen screens, Claude confirms
python evaluate.py --pass2-only   # Re-score cached chapters with Claude
python evaluate.py --scenarios 2  # 2 chapters per evaluation
```

## Files

| File | Role | Modifiable? |
|------|------|-------------|
| `writing_system.md` | Chapter-level craft principles | Yes (agent) |
| `evaluate.py` | Writer + Critic agents | No |
| `scenarios.json` | 12 chapter briefs with full story context | No |
| `program.md` | Agent instructions | No (human edits) |

## Scoring dimensions

prose_quality, worldbuilding, character_voice, chapter_arc, pacing_and_transitions, sensory_immersion, originality, emotional_resonance — each 0-100.

## License

MIT
