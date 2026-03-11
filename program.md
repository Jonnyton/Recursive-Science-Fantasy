# autoresearch-fantasy

Autonomous research to iteratively improve a fantasy writing craft system. Uses a filter chain: Qwen 3.5 (local, free) screens every experiment, Claude (API, ~$0.11/call) confirms only the promising ones.

## Setup

1. **Agree on a run tag** (e.g. `mar10`). Create branch: `git checkout -b autoresearch/<tag>`
2. **Read all in-scope files** for context: `README.md`, `scenarios.json`, `evaluate.py`, `writing_system.md`
3. **Verify Ollama**: `curl http://localhost:11434/api/tags` — confirm `qwen3.5` is available
4. **Verify API key**: confirm `ANTHROPIC_API_KEY` is set
5. **Initialize results.tsv** with just the header row
6. **Confirm and go**

## The filter chain

This is the core insight of the system. Most experiments fail — maybe 70% of changes won't improve the score. You don't want to spend API money scoring failures. So:

**Pass 1 (free):** Qwen writes a ~4000-word chapter, Qwen scores it. This catches the obvious failures for free.

**Pass 2 (paid, ~$0.11):** Only if Pass 1 shows improvement. Claude scores the *same chapter* (no new generation — the expensive part already happened for free). Two independent models agreeing is a stronger signal than either alone.

The agent decides whether to keep or discard based on the combined verdict.

## Commands

| Command | What | Cost | When |
|---------|------|------|------|
| `python evaluate.py` | Pass 1 only: Qwen writes + scores | $0 | Every experiment |
| `python evaluate.py --pass2` | Both passes: Qwen screens, Claude confirms | ~$0.11 | When Pass 1 shows improvement |
| `python evaluate.py --pass2-only` | Re-score cached chapters with Claude | ~$0.11 | If you want Claude's verdict on the last run |
| `python evaluate.py --scenarios 2` | 2 chapters instead of 1 | $0 (or ~$0.22 with --pass2) | When signal is noisy |

## What you CAN do

- Modify `writing_system.md` — the only file you edit

## What you CANNOT do

- Modify `evaluate.py`, `scenarios.json`, or `program.md`

## The experiment loop

LOOP FOREVER:

1. Read `writing_system.md` and `results.tsv`
2. Identify the weakest dimension — target your experiment there
3. Form a specific hypothesis
4. Make ONE focused edit to `writing_system.md`
5. git commit the change
6. **Pass 1**: `python evaluate.py > eval.log 2>&1`
7. Check results: `grep "^composite_score:\|^weakest" eval.log`
8. **Decision point:**
   - If Pass 1 composite_score **improved** → proceed to Pass 2
   - If Pass 1 composite_score **did not improve** → revert immediately (save the API call)
9. **Pass 2** (only if Pass 1 improved): `python evaluate.py --pass2-only >> eval.log 2>&1`
10. Check combined results: `grep "^composite_score:\|^agreement:\|^weakest" eval.log`
11. **Ratchet decision:**
    - Combined composite improved AND agreement STRONG/MODERATE → **keep**
    - Combined composite did not improve OR agreement WEAK → **revert**
12. Log to results.tsv
13. Repeat from step 1

Note on step 9: `--pass2-only` re-scores the cached chapter from Pass 1 with Claude. It does NOT generate a new chapter. This is important — both critics are judging the *exact same text*, which makes their agreement meaningful.

## Logging results

Tab-separated `results.tsv` with columns:

```
commit	composite_score	qwen_score	claude_score	weakest_dim	agreement	status	description
```

- `qwen_score`: Pass 1 composite (always present)
- `claude_score`: Pass 2 composite (blank if Pass 1 failed and we skipped Pass 2)
- `agreement`: STRONG/MODERATE/WEAK (blank if no Pass 2)
- `status`: `keep`, `discard`, `error`

Example:

```
commit	composite_score	qwen_score	claude_score	weakest_dim	agreement	status	description
a1b2c3d	72.50	72.50		originality:61.0		keep	baseline (Pass 1 only)
b2c3d4e	74.20	75.10	73.30	character_voice:65.0	STRONG	keep	added sensory grounding for action scenes
c3d4e5f	71.80	71.80		originality:60.0		discard	Pass 1 lower — skipped Pass 2
d4e5f6g	73.10	74.50	71.70	tension:67.0	MODERATE	discard	restructured openings — Claude disagreed
e5f6g7h	75.80	76.20	75.40	pacing:68.0	STRONG	keep	added anti-patterns for cliche avoidance
```

## Cost estimate

Assume ~30% of experiments pass the Qwen screen. For 100 experiments overnight:
- Pass 1: 100 × Qwen (free) = **$0**
- Pass 2: ~30 × Claude critic (~$0.11 each) = **~$3.30**
- **Total: ~$3.30 per 100 experiments**

## NEVER STOP

Once the loop begins, do NOT pause to ask the human. They may be asleep. Run indefinitely until manually stopped. Each experiment takes ~3-8 minutes. If you run out of ideas, study scoring patterns, re-read the writing system for gaps, try combining near-misses, try structural reorganization.
