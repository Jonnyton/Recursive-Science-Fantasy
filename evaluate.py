"""
AutoResearch Fantasy — Chapter Evaluation Script
Two agents: one writes a full chapter, one critiques it.

Filter chain architecture:
  - Pass 1 (free):  Qwen 3.5 writes a chapter, Qwen 3.5 scores it
  - Pass 2 (paid):  Claude scores the SAME chapter (only if Pass 1 showed improvement)

The research agent runs Pass 1 for every experiment. If the Qwen critic says
the score improved, it then runs Pass 2 on the same chapter to get Claude's
verdict. The change is only kept if BOTH models agree it's an improvement.

This means you only pay for Claude on the ~30% of experiments that look promising,
while getting two independent judges agreeing — a stronger signal than either alone.

Usage:
  python evaluate.py                   # Pass 1 only (Qwen writes + Qwen scores, free)
  python evaluate.py --pass2           # Both passes (Qwen writes + Qwen scores + Claude scores)
  python evaluate.py --pass2-only      # Pass 2 only on last chapter (re-score with Claude)
  python evaluate.py --scenarios 2     # Evaluate 2 chapters instead of 1

Requires:
  - Ollama running locally with qwen3.5 model
  - ANTHROPIC_API_KEY (only for --pass2 or --pass2-only)

This is the evaluation harness — do not modify this file.
"""

import argparse
import json
import os
import random
import re
import sys
import time

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

LOCAL_MODEL = "qwen3.5"                    # Ollama model name
LOCAL_BASE_URL = "http://localhost:11434"   # Ollama default
API_MODEL = "claude-opus-4-6"             # For Pass 2
CHAPTER_TARGET_WORDS = 4000                # Target chapter length
DEFAULT_NUM_SCENARIOS = 1                  # Chapters per evaluation
MAX_RETRIES = 3

# ---------------------------------------------------------------------------
# Auto-load .env file if present (so API key works without manual export)
# ---------------------------------------------------------------------------

def _load_dotenv():
    """Load key=value pairs from .env file into os.environ."""
    env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
    if os.path.exists(env_path):
        with open(env_path) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, _, value = line.partition("=")
                    os.environ.setdefault(key.strip(), value.strip())

_load_dotenv()

# ---------------------------------------------------------------------------
# Client setup
# ---------------------------------------------------------------------------

def get_ollama_client():
    """Get an OpenAI-compatible client pointing at Ollama."""
    from openai import OpenAI
    return OpenAI(
        base_url=f"{LOCAL_BASE_URL}/v1",
        api_key="ollama",
    )

def get_anthropic_client():
    """Get the Anthropic client for Pass 2."""
    import anthropic
    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("ERROR: ANTHROPIC_API_KEY required for --pass2", file=sys.stderr)
        sys.exit(1)
    return anthropic.Anthropic()

# ---------------------------------------------------------------------------
# Load files
# ---------------------------------------------------------------------------

def load_writing_system():
    with open("writing_system.md", "r") as f:
        return f.read()

def load_scenarios():
    with open("scenarios.json", "r") as f:
        return json.load(f)

# ---------------------------------------------------------------------------
# Agent 1: The Writer (always local Qwen)
# ---------------------------------------------------------------------------

def generate_chapter(client, writing_system, scenario):
    """Agent 1 writes a full fantasy chapter. Always uses local Qwen."""

    system_prompt = f"""You are a skilled fantasy novelist. You have deeply internalized the following writing system and craft principles. Apply them naturally — don't reference the rules explicitly, just write excellent fiction that embodies them.

You write full chapters, not scenes or excerpts. A chapter is a self-contained unit of a novel with its own arc: it opens with a hook, develops through multiple beats or scenes, builds tension across scene transitions, and closes on a turning point that propels the reader forward. You manage pacing across thousands of words, weaving together action, interiority, dialogue, and description.

<writing_system>
{writing_system}
</writing_system>"""

    # Build the chapter brief
    brief_parts = [scenario["chapter_brief"]]
    if scenario.get("story_context"):
        brief_parts.insert(0, f"STORY CONTEXT: {scenario['story_context']}")
    if scenario.get("chapter_position"):
        brief_parts.insert(0, f"POSITION IN NOVEL: {scenario['chapter_position']}")
    if scenario.get("pov_character"):
        brief_parts.append(f"POV CHARACTER: {scenario['pov_character']}")
    if scenario.get("required_beats"):
        beats = "\n".join(f"  - {b}" for b in scenario["required_beats"])
        brief_parts.append(f"KEY BEATS THIS CHAPTER MUST HIT:\n{beats}")

    brief = "\n\n".join(brief_parts)

    user_prompt = f"""{brief}

Write this as a complete chapter of approximately {CHAPTER_TARGET_WORDS} words. Structure it as a real novel chapter — with an opening hook, multiple scenes or beats, transitions between them, rising tension, and a chapter ending that makes the reader turn the page. Include scene breaks (marked with a blank line or "* * *") where appropriate.

Write only the chapter — no preamble, no author's note, no commentary, no chapter number or title. Just the fiction. Do not use any thinking tags or reasoning blocks — output only the story text."""

    for attempt in range(MAX_RETRIES):
        try:
            response = client.chat.completions.create(
                model=LOCAL_MODEL,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                max_tokens=16384,
                temperature=0.8,
            )
            text = response.choices[0].message.content
            tokens = (response.usage.prompt_tokens or 0) + (response.usage.completion_tokens or 0)
            text = re.sub(r'<think>.*?</think>', '', text, flags=re.DOTALL).strip()
            return text, tokens
        except Exception as e:
            if attempt < MAX_RETRIES - 1:
                print(f"  Writer retry {attempt + 1}: {e}", file=sys.stderr)
                time.sleep(3)
            else:
                raise

# ---------------------------------------------------------------------------
# Scoring rubric (shared by both critics)
# ---------------------------------------------------------------------------

SCORING_RUBRIC = """You are an expert literary critic and developmental editor specializing in fantasy novels. You will evaluate a FULL CHAPTER (not a scene or excerpt) on 8 dimensions, each scored 0-100.

You are reading this as a chapter of a novel — judge it as such. A chapter must work as a self-contained unit while serving the larger story. It should have its own arc, manage pacing across multiple beats, and end in a way that compels the reader forward.

## Scoring Dimensions

1. **prose_quality** (0-100): Sentence-level craft sustained across thousands of words. Rhythm, word choice, clarity, elegance. Does the prose maintain quality without becoming monotonous or purple? Does the writer vary their register — tighter for action, more expansive for reflection? Is there control and intentionality in every paragraph?

2. **worldbuilding** (0-100): Does the chapter build a coherent, lived-in world through immersion rather than exposition? Are fantastical elements woven naturally into the action? Does the world have texture, history, and specificity? Does the reader learn about the world *while something else is happening*?

3. **character_voice** (0-100): Does the POV character have a distinct, sustained internal voice across the full chapter? Does their interiority deepen as the chapter progresses? Do they have a consistent but evolving emotional state? Can you tell who is narrating from the texture of the prose alone?

4. **chapter_arc** (0-100): Does the chapter have its own dramatic shape — a beginning, middle, and end? Does it open with a hook that earns the reader's attention? Does it build through complication toward a turning point? Does it end on a beat that changes something and compels the reader to continue? Is there a sense of *movement* from where the chapter begins to where it ends?

5. **pacing_and_transitions** (0-100): Does the chapter manage rhythm across its full length? Are there purposeful shifts between fast and slow, tension and release? Do scene transitions land cleanly — do they orient the reader in time, place, and emotional state without over-explaining? Does the chapter sustain momentum without feeling rushed or padded?

6. **sensory_immersion** (0-100): Does the chapter ground the reader physically in its world across multiple settings or moments? Are there specific sights, sounds, smells, textures, tastes? Does the sensory palette shift with the emotional register? Does the fantastical have physical weight and consequence?

7. **originality** (0-100): Does the chapter avoid fantasy cliches at both the sentence level and the structural level? Are there surprising images, fresh metaphors, unexpected turns? Does the chapter subvert or complicate genre expectations? Does it feel like something you haven't read before?

8. **emotional_resonance** (0-100): Does the chapter make you feel something real and earned? Is there an emotional throughline that builds across the chapter's beats? Are the emotions anchored in universal human experience rather than genre convention? Does the chapter earn its emotional moments through setup and accumulation rather than shortcuts?

## Scoring Guidelines

- **90-100**: Exceptional. Publication-quality by top-tier fantasy authors (Le Guin, Hobb, Jemisin, Abercrombie). Rare.
- **80-89**: Strong. Genuine craft that sustains engagement across the full chapter.
- **70-79**: Solid. Competent chapter-level craft with clear strengths. Some sections stronger than others.
- **60-69**: Adequate. Readable but sags in places or relies on convention too heavily.
- **50-59**: Below average. Struggles to sustain arc, voice, or pacing across its length.
- **Below 50**: Significant structural problems. Reads like disconnected scenes, not a chapter.

Be rigorous and honest. Do not grade inflate.

## Output Format

You MUST respond with ONLY a JSON object, no other text. No thinking, no reasoning, no preamble:
{
    "prose_quality": <int>,
    "worldbuilding": <int>,
    "character_voice": <int>,
    "chapter_arc": <int>,
    "pacing_and_transitions": <int>,
    "sensory_immersion": <int>,
    "originality": <int>,
    "emotional_resonance": <int>,
    "brief_rationale": "<3-4 sentences: what works best, what's weakest, how well the chapter sustains quality>"
}"""

# ---------------------------------------------------------------------------
# Critic implementations
# ---------------------------------------------------------------------------

def make_critic_prompt(chapter, scenario):
    """Build the critic prompt (shared between local and API critics)."""
    return f"""Evaluate the following complete fantasy chapter.

CHAPTER BRIEF: {scenario['chapter_brief'][:200]}

<chapter>
{chapter}
</chapter>

Score this as a chapter of a novel. Consider how well it manages its length, builds its arc, sustains voice, handles transitions, and earns its ending.

IMPORTANT: Respond with ONLY the JSON object. No thinking, no reasoning, no preamble. Just the JSON."""


def parse_scores(raw):
    """Parse JSON scores from raw model output, handling thinking tags and code blocks."""
    raw = re.sub(r'<think>.*?</think>', '', raw, flags=re.DOTALL).strip()
    if not raw:
        raise ValueError("Model returned empty response (all content was in thinking tags)")
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[1].rsplit("```", 1)[0].strip()
    # Try to extract JSON if there's extra text around it
    if not raw.startswith("{"):
        match = re.search(r'\{[^{}]*\}', raw, re.DOTALL)
        if match:
            raw = match.group(0)
    return json.loads(raw)


def score_chapter_local(client, chapter, scenario):
    """Score using local Qwen via Ollama."""
    user_prompt = make_critic_prompt(chapter, scenario)
    # Append /no_think to suppress Qwen's thinking mode for structured output
    user_prompt_no_think = user_prompt + "\n\n/no_think"

    for attempt in range(MAX_RETRIES):
        try:
            response = client.chat.completions.create(
                model=LOCAL_MODEL,
                messages=[
                    {"role": "system", "content": SCORING_RUBRIC},
                    {"role": "user", "content": user_prompt_no_think}
                ],
                max_tokens=2048,
                temperature=0.3,
            )
            raw = response.choices[0].message.content.strip()
            tokens = (response.usage.prompt_tokens or 0) + (response.usage.completion_tokens or 0)
            scores = parse_scores(raw)
            return scores, tokens
        except (json.JSONDecodeError, ValueError) as e:
            if attempt < MAX_RETRIES - 1:
                print(f"  Local critic JSON/parse retry {attempt + 1}: {e}", file=sys.stderr)
                time.sleep(2)
            else:
                raise
        except Exception as e:
            if attempt < MAX_RETRIES - 1:
                print(f"  Local critic retry {attempt + 1}: {e}", file=sys.stderr)
                time.sleep(3)
            else:
                raise


def score_chapter_api(api_client, chapter, scenario):
    """Score using Claude API."""
    user_prompt = make_critic_prompt(chapter, scenario)

    for attempt in range(MAX_RETRIES):
        try:
            response = api_client.messages.create(
                model=API_MODEL,
                max_tokens=1024,
                system=SCORING_RUBRIC,
                messages=[{"role": "user", "content": user_prompt}]
            )
            raw = response.content[0].text.strip()
            tokens = response.usage.input_tokens + response.usage.output_tokens
            scores = parse_scores(raw)
            return scores, tokens
        except json.JSONDecodeError as e:
            if attempt < MAX_RETRIES - 1:
                print(f"  API critic JSON retry {attempt + 1}: {e}", file=sys.stderr)
                time.sleep(2)
            else:
                raise
        except Exception as e:
            if attempt < MAX_RETRIES - 1:
                print(f"  API critic retry {attempt + 1}: {e}", file=sys.stderr)
                time.sleep(5 * (attempt + 1))
            else:
                raise

# ---------------------------------------------------------------------------
# Dimensions
# ---------------------------------------------------------------------------

DIMENSIONS = [
    "prose_quality", "worldbuilding", "character_voice", "chapter_arc",
    "pacing_and_transitions", "sensory_immersion", "originality", "emotional_resonance"
]

def compute_composite(scores_dict):
    """Compute composite score from a dimension scores dict."""
    vals = [scores_dict.get(d, 0) for d in DIMENSIONS]
    return round(sum(vals) / len(vals), 2) if vals else 0.0

def find_weakest(scores_dict):
    """Find the weakest dimension."""
    return min(scores_dict, key=scores_dict.get)

# ---------------------------------------------------------------------------
# Pass 1: Qwen writes + Qwen scores (free)
# ---------------------------------------------------------------------------

def run_pass1(local_client, writing_system, scenarios, num_scenarios):
    """Generate chapters and score with Qwen. Returns chapters for potential Pass 2."""

    eval_scenarios = random.sample(scenarios, min(num_scenarios, len(scenarios)))
    print(f"[Pass 1 / Qwen] Generating and scoring {len(eval_scenarios)} chapter(s)...")

    chapters = []  # Store generated chapters for Pass 2
    all_scores = {dim: [] for dim in DIMENSIONS}
    total_tokens = 0

    for i, scenario in enumerate(eval_scenarios):
        print(f"\n[Pass 1] Chapter {i+1}/{len(eval_scenarios)}: {scenario['id']}")
        print(f"  Brief: {scenario['chapter_brief'][:100]}...")

        # Write
        print(f"  [Writer / Qwen] Generating chapter (~{CHAPTER_TARGET_WORDS} words)...")
        t0 = time.time()
        chapter, writer_tokens = generate_chapter(local_client, writing_system, scenario)
        elapsed = time.time() - t0
        word_count = len(chapter.split())
        print(f"  [Writer / Qwen] Done. {word_count} words, {writer_tokens} tokens, {elapsed:.1f}s")
        total_tokens += writer_tokens

        # Score
        print(f"  [Critic / Qwen] Scoring chapter...")
        t0 = time.time()
        scores, critic_tokens = score_chapter_local(local_client, chapter, scenario)
        elapsed = time.time() - t0
        print(f"  [Critic / Qwen] Done. {critic_tokens} tokens, {elapsed:.1f}s")
        total_tokens += critic_tokens

        for dim in DIMENSIONS:
            val = scores.get(dim, 0)
            all_scores[dim].append(val)
            print(f"    {dim}: {val}")

        if "brief_rationale" in scores:
            print(f"    rationale: {scores['brief_rationale']}")

        chapters.append({"chapter": chapter, "scenario": scenario, "qwen_scores": scores})

    # Compute averages
    avg_scores = {}
    for dim in DIMENSIONS:
        avg_scores[dim] = round(sum(all_scores[dim]) / len(all_scores[dim]), 1)

    composite = compute_composite(avg_scores)

    # Save chapters for potential Pass 2
    cache = {
        "chapters": [{"scenario_id": c["scenario"]["id"], "text": c["chapter"]} for c in chapters],
        "scenario_details": [c["scenario"] for c in chapters],
    }
    with open(".chapter_cache.json", "w") as f:
        json.dump(cache, f)

    return composite, avg_scores, total_tokens, chapters


# ---------------------------------------------------------------------------
# Pass 2: Claude scores the same chapters (paid, only when needed)
# ---------------------------------------------------------------------------

def run_pass2(api_client, chapters=None):
    """Score previously-generated chapters with Claude. Uses cached chapters if none provided."""

    if chapters is None:
        # Load from cache (for --pass2-only mode)
        if not os.path.exists(".chapter_cache.json"):
            print("ERROR: No cached chapters found. Run Pass 1 first.", file=sys.stderr)
            sys.exit(1)
        with open(".chapter_cache.json", "r") as f:
            cache = json.load(f)
        chapters = []
        for ch, sc in zip(cache["chapters"], cache["scenario_details"]):
            chapters.append({"chapter": ch["text"], "scenario": sc, "qwen_scores": None})

    print(f"\n[Pass 2 / Claude] Scoring {len(chapters)} chapter(s) with Claude API...")

    all_scores = {dim: [] for dim in DIMENSIONS}
    total_api_tokens = 0

    for i, entry in enumerate(chapters):
        scenario = entry["scenario"]
        chapter = entry["chapter"]
        qwen_scores = entry.get("qwen_scores")

        print(f"\n[Pass 2] Chapter {i+1}/{len(chapters)}: {scenario['id']}")

        # Claude scores
        print(f"  [Critic / Claude] Scoring chapter...")
        t0 = time.time()
        scores, critic_tokens = score_chapter_api(api_client, chapter, scenario)
        elapsed = time.time() - t0
        print(f"  [Critic / Claude] Done. {critic_tokens} tokens, {elapsed:.1f}s")
        total_api_tokens += critic_tokens

        for dim in DIMENSIONS:
            val = scores.get(dim, 0)
            all_scores[dim].append(val)

        # Print comparison if we have Qwen scores
        if qwen_scores:
            print(f"  --- Qwen vs Claude ---")
            for dim in DIMENSIONS:
                qval = qwen_scores.get(dim, 0)
                cval = scores.get(dim, 0)
                diff = qval - cval
                marker = " <<<" if abs(diff) > 10 else ""
                print(f"    {dim}: qwen={qval} claude={cval} diff={diff:+d}{marker}")
        else:
            for dim in DIMENSIONS:
                print(f"    {dim}: {scores.get(dim, 0)}")

        if "brief_rationale" in scores:
            print(f"    rationale: {scores['brief_rationale']}")

    # Compute averages
    avg_scores = {}
    for dim in DIMENSIONS:
        avg_scores[dim] = round(sum(all_scores[dim]) / len(all_scores[dim]), 1)

    composite = compute_composite(avg_scores)
    return composite, avg_scores, total_api_tokens


# ---------------------------------------------------------------------------
# Main evaluation
# ---------------------------------------------------------------------------

def run_evaluation(pass2=False, pass2_only=False, num_scenarios=DEFAULT_NUM_SCENARIOS):
    """Main entry point.

    Flow:
      Default:      Pass 1 only (free Qwen screening)
      --pass2:      Pass 1 + Pass 2 (Qwen screens, Claude confirms on same chapters)
      --pass2-only: Pass 2 only (re-score cached chapters with Claude)
    """

    local_client = get_ollama_client()
    api_client = None
    if pass2 or pass2_only:
        api_client = get_anthropic_client()

    writing_system = load_writing_system()
    scenarios = load_scenarios()

    if pass2_only:
        mode_label = "PASS 2 ONLY (Claude re-scores cached chapters)"
    elif pass2:
        mode_label = "FILTER CHAIN (Qwen screens → Claude confirms)"
    else:
        mode_label = "PASS 1 ONLY (Qwen writes + Qwen scores, free)"

    print(f"=== AutoResearch Fantasy — Chapter Evaluation ===")
    print(f"Writing system: {len(writing_system)} chars, {len(writing_system.split())} words")
    print(f"Mode: {mode_label}")
    if not pass2_only:
        print(f"Chapters per eval: {num_scenarios}")
    print(f"Target chapter length: ~{CHAPTER_TARGET_WORDS} words")
    print(f"---")

    # --- Pass 2 Only mode ---
    if pass2_only:
        claude_composite, claude_avg, api_tokens = run_pass2(api_client)
        weakest = find_weakest(claude_avg)

        print(f"\n{'='*60}")
        print(f"PASS 2 RESULTS (Claude)")
        print(f"{'='*60}")
        print(f"---")
        print(f"composite_score:     {claude_composite}")
        for dim in DIMENSIONS:
            pad = " " * (25 - len(dim))
            print(f"{dim}:{pad}{claude_avg[dim]}")
        print(f"weakest_dim:         {weakest}:{claude_avg[weakest]}")
        print(f"api_tokens_used:     {api_tokens}")

        write_result_json(
            composite=claude_composite, avg_scores=claude_avg,
            local_tokens=0, api_tokens=api_tokens,
            scenario_ids=[], pass_info={"pass": 2, "critic": "claude"}
        )
        return

    # --- Pass 1 ---
    qwen_composite, qwen_avg, local_tokens, chapters = run_pass1(
        local_client, writing_system, scenarios, num_scenarios
    )

    weakest = find_weakest(qwen_avg)

    print(f"\n{'='*60}")
    print(f"PASS 1 RESULTS (Qwen)")
    print(f"{'='*60}")
    print(f"---")
    print(f"composite_score:     {qwen_composite}")
    for dim in DIMENSIONS:
        pad = " " * (25 - len(dim))
        print(f"{dim}:{pad}{qwen_avg[dim]}")
    print(f"weakest_dim:         {weakest}:{qwen_avg[weakest]}")
    print(f"local_tokens_used:   {local_tokens}")

    if not pass2:
        # Pass 1 only — write results and exit
        write_result_json(
            composite=qwen_composite, avg_scores=qwen_avg,
            local_tokens=local_tokens, api_tokens=0,
            scenario_ids=[c["scenario"]["id"] for c in chapters],
            pass_info={"pass": 1, "critic": "qwen"}
        )
        print(f"\nResults written to eval_result.json")
        print(f"Chapters cached for potential Pass 2 (run with --pass2-only to re-score with Claude)")
        return

    # --- Pass 2: Claude confirms on the same chapters ---
    claude_composite, claude_avg, api_tokens = run_pass2(api_client, chapters)

    # Combined verdict
    weakest_qwen = find_weakest(qwen_avg)
    weakest_claude = find_weakest(claude_avg)

    # Agreement: average the two composites
    combined_composite = round((qwen_composite + claude_composite) / 2, 2)
    delta = abs(qwen_composite - claude_composite)
    agreement = "STRONG" if delta < 3.0 else "MODERATE" if delta < 6.0 else "WEAK"

    # Combined per-dimension scores (average of both critics)
    combined_avg = {}
    for dim in DIMENSIONS:
        combined_avg[dim] = round((qwen_avg[dim] + claude_avg[dim]) / 2, 1)

    weakest_combined = find_weakest(combined_avg)

    print(f"\n{'='*60}")
    print(f"COMBINED VERDICT (Qwen + Claude)")
    print(f"{'='*60}")
    print(f"---")
    print(f"qwen_composite:      {qwen_composite}")
    print(f"claude_composite:    {claude_composite}")
    print(f"delta:               {delta:.2f}")
    print(f"agreement:           {agreement}")
    print(f"composite_score:     {combined_composite}")
    for dim in DIMENSIONS:
        pad = " " * (25 - len(dim))
        print(f"{dim}:{pad}{combined_avg[dim]}  (qwen: {qwen_avg[dim]}, claude: {claude_avg[dim]})")
    print(f"weakest_dim:         {weakest_combined}:{combined_avg[weakest_combined]}")
    print(f"local_tokens_used:   {local_tokens}")
    print(f"api_tokens_used:     {api_tokens}")

    write_result_json(
        composite=combined_composite, avg_scores=combined_avg,
        local_tokens=local_tokens, api_tokens=api_tokens,
        scenario_ids=[c["scenario"]["id"] for c in chapters],
        pass_info={
            "qwen_composite": qwen_composite,
            "claude_composite": claude_composite,
            "qwen_scores": qwen_avg,
            "claude_scores": claude_avg,
            "delta": delta,
            "agreement": agreement
        }
    )
    print(f"\nResults written to eval_result.json")


def write_result_json(composite, avg_scores, local_tokens, api_tokens, scenario_ids, pass_info=None):
    """Write machine-readable results."""
    weakest = find_weakest(avg_scores)
    result = {
        "composite_score": composite,
        "dimensions": avg_scores,
        "weakest_dim": weakest,
        "weakest_score": avg_scores[weakest],
        "chapters_evaluated": len(scenario_ids) if scenario_ids else "cached",
        "local_tokens_used": local_tokens,
        "api_tokens_used": api_tokens,
        "scenario_ids": scenario_ids,
    }
    if pass_info:
        result["pass_info"] = pass_info
    with open("eval_result.json", "w") as f:
        json.dump(result, f, indent=2)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Evaluate the fantasy writing system (chapter-level)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python evaluate.py                 # Free: Qwen writes + Qwen scores
  python evaluate.py --pass2         # Filter chain: Qwen screens, Claude confirms
  python evaluate.py --pass2-only    # Re-score cached chapters with Claude
  python evaluate.py --scenarios 2   # Generate and score 2 chapters
        """
    )
    parser.add_argument("--pass2", action="store_true",
                        help="Run both passes: Qwen screens, then Claude confirms on the same chapters")
    parser.add_argument("--pass2-only", action="store_true",
                        help="Run Pass 2 only: re-score cached chapters with Claude (no new generation)")
    parser.add_argument("--scenarios", type=int, default=DEFAULT_NUM_SCENARIOS,
                        help=f"Number of chapters to generate per evaluation (default: {DEFAULT_NUM_SCENARIOS})")
    args = parser.parse_args()

    if args.pass2 and args.pass2_only:
        print("ERROR: Cannot use both --pass2 and --pass2-only", file=sys.stderr)
        sys.exit(1)

    run_evaluation(pass2=args.pass2, pass2_only=args.pass2_only, num_scenarios=args.scenarios)
