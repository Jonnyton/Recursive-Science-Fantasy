"""
Benchmark Lane -- Main Driver

Runs the hidden real-book benchmark evaluation for a single chapter.
This is a standalone subsystem that does NOT modify the synthetic evaluation loop.

Flow per chapter:
  1. Load remixed chapter spec and canon
  2. Generate a chapter using the writer package (blind to source)
  3. Run slop check (reuses evaluate.py's check_slop)
  4. Run novelty audit against source chapter
  5. Run fidelity check against remixed canon
  6. Run frontier pairwise comparison against source chapter
  7. Record result

Usage:
    python benchmark/benchmark_lane.py --chapter 1
    python benchmark/benchmark_lane.py --chapter 1 --pass2    # include frontier pairwise
    python benchmark/benchmark_lane.py --all                  # run all spike chapters
    python benchmark/benchmark_lane.py --compile-only         # just compile remix artifacts
"""

import argparse
import json
import os
import re
import sys
import time

# Add parent dir for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from benchmark.remix_compiler import compile_spike
from benchmark.novelty_auditor import audit_novelty
from benchmark.fidelity_checker import check_fidelity
from benchmark.ollama_client import call_local, get_ollama_client

MANIFEST_PATH = "benchmark/spike_manifest.json"
RESULTS_DIR = "benchmark/results"
SPIKE_DIR = "benchmark/spike_inputs"
PROGRESS_FILE = "benchmark/progress.json"
MAX_RECENT_SUMMARIES = 3
MAX_ATTEMPTS_PER_CHAPTER = int(os.environ.get("ARF_BENCHMARK_MAX_ATTEMPTS", "5"))


def load_manifest() -> dict:
    """Load the spike manifest. Compile if missing."""
    if os.path.exists(MANIFEST_PATH):
        with open(MANIFEST_PATH, "r", encoding="utf-8") as f:
            manifest = json.load(f)
        if _manifest_ready(manifest):
            return manifest
        print("Spike manifest is missing required artifacts. Recompiling...")
    else:
        print("No spike manifest found. Running remix compilation first...")
    return compile_spike(SPIKE_DIR)


def _manifest_ready(manifest: dict) -> bool:
    if not isinstance(manifest, dict):
        return False
    artifacts = manifest.get("artifacts")
    if not isinstance(artifacts, list) or not artifacts:
        return False

    required_keys = ("source_canon", "remixed_canon", "chapter_spec", "source_input")
    for artifact in artifacts:
        if not isinstance(artifact, dict):
            return False
        for key in required_keys:
            path = artifact.get(key)
            if not path or not os.path.exists(path):
                return False
    return True


def _clean_chapter_spec(spec_text: str) -> str:
    return re.sub(r"^#\s+Chapter\s+\d+\s+Brief\s*", "", spec_text, count=1, flags=re.IGNORECASE).strip()


def _build_bible_excerpt(remixed_canon: dict) -> str:
    lines = []

    characters = [
        character.get("name", "").strip()
        for character in remixed_canon.get("characters", [])[:4]
        if character.get("name")
    ]
    if characters:
        lines.append("Characters: " + ", ".join(characters))

    locations = [
        location.get("name", "").strip()
        for location in remixed_canon.get("locations", [])[:3]
        if location.get("name")
    ]
    if locations:
        lines.append("Locations: " + ", ".join(locations))

    wonder = [
        item.strip()
        for item in remixed_canon.get("magic_or_wonder", [])[:3]
        if item
    ]
    if wonder:
        lines.append("Fantastical elements: " + "; ".join(wonder))

    return "\n".join(lines)


def _build_recent_summaries(manifest: dict, chapter_num: int) -> str:
    summaries = []
    for artifact in manifest.get("artifacts", []):
        if artifact.get("chapter", 0) >= chapter_num:
            break
        summary = artifact.get("recent_summary", "").strip()
        if summary:
            summaries.append(summary)
    return "\n\n".join(summaries[-MAX_RECENT_SUMMARIES:])


def _estimate_source_body_word_count(source_text: str) -> int:
    lines = source_text.splitlines()
    idx = 0

    while idx < len(lines) and not lines[idx].strip():
        idx += 1

    if idx < len(lines) and lines[idx].strip().upper().startswith("CHAPTER "):
        idx += 1

    while idx < len(lines) and not lines[idx].strip():
        idx += 1

    if idx < len(lines) and 0 < len(lines[idx].split()) <= 20:
        idx += 1

    body = "\n".join(lines[idx:]).strip()
    if not body:
        body = source_text.strip()
    return len(body.split())


def _build_benchmark_scenario(
    manifest: dict,
    chapter_num: int,
    chapter_spec: str,
    remixed_canon: dict,
    *,
    prior_chapters_summary: str = "",
    previous_chapter_text: str = "",
) -> dict:
    chapter_brief = _clean_chapter_spec(chapter_spec)
    required_beats = [
        event.get("summary", "").strip()
        for event in remixed_canon.get("events", [])[:4]
        if event.get("summary")
    ]
    pov_character = ""
    if remixed_canon.get("characters"):
        pov_character = remixed_canon["characters"][0].get("name", "").strip()

    series_context = {
        "series_summary": manifest.get("series_summary", "").strip(),
        "bible_excerpt": _build_bible_excerpt(remixed_canon),
        "recent_summaries": prior_chapters_summary or _build_recent_summaries(manifest, chapter_num),
    }
    if previous_chapter_text:
        series_context["previous_chapter"] = previous_chapter_text[-5000:]

    return {
        "id": f"benchmark_spike_chapter_{chapter_num:02d}",
        "genre_tags": ["fantasy", "series"],
        "chapter_brief": chapter_brief,
        "story_context": "Continue the established fantasy narrative with strong continuity and forward motion.",
        "chapter_position": f"Chapter {chapter_num} of {manifest.get('num_chapters', '?')} in an ongoing fantasy novel",
        "pov_character": pov_character,
        "required_beats": required_beats,
        "_series_context": series_context,
    }


def generate_benchmark_chapter(chapter_spec: str, chapter_num: int,
                               manifest: dict,
                               remixed_canon: dict,
                               reference_words: int,
                               prior_chapters_summary: str = "",
                               previous_chapter_text: str = "") -> tuple[str, int, dict]:
    """Generate a chapter using the writer package, blind to source.

    Returns (chapter_text, local_tokens, writer_meta).
    """
    from writer_stack import build_writer_package, render_writer_system_prompt

    client = get_ollama_client()
    scenario = _build_benchmark_scenario(
        manifest,
        chapter_num,
        chapter_spec,
        remixed_canon,
        prior_chapters_summary=prior_chapters_summary,
        previous_chapter_text=previous_chapter_text,
    )
    writer_package = build_writer_package(scenario)
    system_prompt = render_writer_system_prompt(writer_package, phase="draft")
    chapter_brief = scenario["chapter_brief"]

    user_prompt = f"""Write this as a complete fantasy novel chapter.

Source chapter length for reference only: about {reference_words} words.
Prioritize writing quality, chapter shape, and fidelity to the brief over matching that length exactly.

{chapter_brief}
"""
    if scenario.get("required_beats"):
        beats = "\n".join(f"- {beat}" for beat in scenario["required_beats"])
        user_prompt += f"\nRequired beats:\n{beats}\n"
    if scenario.get("_series_context", {}).get("series_summary"):
        user_prompt += f"\nSeries context:\n{scenario['_series_context']['series_summary']}\n"
    if scenario.get("_series_context", {}).get("bible_excerpt"):
        user_prompt += f"\nStory bible excerpt:\n{scenario['_series_context']['bible_excerpt']}\n"
    if scenario.get("_series_context", {}).get("recent_summaries"):
        user_prompt += f"\nRecent chapters:\n{scenario['_series_context']['recent_summaries']}\n"
    if scenario.get("_series_context", {}).get("previous_chapter"):
        user_prompt += (
            "\nPrevious chapter excerpt for continuity:\n"
            f"{scenario['_series_context']['previous_chapter']}\n"
        )
    user_prompt += """
Hard constraints:
- End after one chapter-level closing turn.
- Do not repeat paragraphs, sentence patterns, or stock emotional beats.
- Do not explain your process.
- Output only the fiction.
"""

    text, tokens, _meta = call_local(
        client,
        system_prompt,
        user_prompt,
        max_tokens=8192,
        temperature=0.8,
    )
    writer_meta = {
        "persona_plan": writer_package.get("persona_plan", {}),
        "craft_card_ids": [card["id"] for card in writer_package.get("craft_cards", [])],
        "generation_profile": "benchmark_spike",
        "reference_word_count": reference_words,
    }
    return text, tokens, writer_meta


def run_slop_check(chapter_text: str) -> tuple[int, list]:
    """Run the existing slop checker from evaluate.py."""
    from evaluate import check_slop, is_catastrophic_slop
    score, issues = check_slop(chapter_text)
    return score, issues, is_catastrophic_slop(score, issues)


def run_pairwise_vs_source(generated_text: str, source_text: str,
                           chapter_num: int) -> dict:
    """Run frontier pairwise comparison: generated vs source chapter.

    The judge sees both chapters blind (labeled A and B, randomized).
    Returns {"verdict": "NEW_BETTER"|"OLD_BETTER"|"EQUAL", "rationale": "..."}.
    """
    from evaluate import get_anthropic_client, API_MODEL
    import random

    client = get_anthropic_client()

    # Randomize order so the judge can't infer which is which
    if random.random() < 0.5:
        chapter_a, chapter_b = generated_text, source_text
        a_is_generated = True
    else:
        chapter_a, chapter_b = source_text, generated_text
        a_is_generated = False

    prompt = f"""You are evaluating two fantasy chapters side by side.
Both chapters cover similar narrative ground. Judge them purely on writing quality.

Evaluate on these dimensions:
- Prose quality (sentence craft, rhythm, clarity)
- Character voice (distinctive, consistent, embodied)
- Emotional resonance (earned feeling, not told)
- Worldbuilding (concrete, immersive, consequential)
- Originality (fresh imagery, unexpected moves, avoids cliche)
- Pacing (tension management, scene rhythm)
- Dialogue (subtext, character revelation)
- Chapter arc (transformation, satisfying shape)

## Chapter A

{chapter_a[:8000]}

## Chapter B

{chapter_b[:8000]}

First analyze each chapter's strengths and weaknesses, then give your verdict.

Output JSON:
{{
  "chapter_a_strengths": ["..."],
  "chapter_a_weaknesses": ["..."],
  "chapter_b_strengths": ["..."],
  "chapter_b_weaknesses": ["..."],
  "verdict": "A_BETTER" or "B_BETTER" or "EQUAL",
  "rationale": "one paragraph explaining the verdict"
}}"""

    response = client.messages.create(
        model=API_MODEL,
        max_tokens=2048,
        messages=[{"role": "user", "content": prompt}],
    )

    raw = response.content[0].text
    result = _parse_json(raw)

    # Translate verdict back to NEW_BETTER / OLD_BETTER
    verdict = result.get("verdict", "EQUAL")
    if verdict == "A_BETTER":
        final_verdict = "NEW_BETTER" if a_is_generated else "OLD_BETTER"
    elif verdict == "B_BETTER":
        final_verdict = "NEW_BETTER" if not a_is_generated else "OLD_BETTER"
    else:
        final_verdict = "EQUAL"

    return {
        "verdict": final_verdict,
        "rationale": result.get("rationale", ""),
        "a_is_generated": a_is_generated,
        "raw_judge": result,
    }


def run_benchmark_chapter(chapter_num: int, manifest: dict, *,
                          pass2: bool = False,
                          prior_chapters_summary: str = "",
                          previous_chapter_text: str = "") -> dict:
    """Run the full benchmark pipeline for one chapter.

    Returns a result dict with all audit/check/comparison data.
    """
    artifacts = None
    for a in manifest["artifacts"]:
        if a["chapter"] == chapter_num:
            artifacts = a
            break
    if not artifacts:
        raise ValueError(f"Chapter {chapter_num} not found in manifest")

    print(f"\n{'='*60}")
    print(f"Benchmark Chapter {chapter_num}")
    print(f"{'='*60}")

    # Load artifacts
    with open(artifacts["chapter_spec"], "r", encoding="utf-8") as f:
        spec_text = f.read()
    with open(artifacts["remixed_canon"], "r", encoding="utf-8") as f:
        remixed_canon = json.load(f)
    with open(artifacts["source_input"], "r", encoding="utf-8") as f:
        source_text = f.read()
    source_word_count = _estimate_source_body_word_count(source_text)

    result = {
        "chapter": chapter_num,
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "status": "pending",
        "source_word_count": source_word_count,
        "reference_word_count": source_word_count,
    }

    # Step 1: Generate
    print("  [1/5] Generating chapter from remixed spec...")
    try:
        generated, local_tokens, writer_meta = generate_benchmark_chapter(
            spec_text,
            chapter_num,
            manifest,
            remixed_canon,
            source_word_count,
            prior_chapters_summary,
            previous_chapter_text,
        )
        result["generated_text"] = generated
        result["local_tokens"] = local_tokens
        result["word_count"] = len(generated.split())
        result["writer_meta"] = writer_meta
        print(
            f"        Generated {result['word_count']} words "
            f"(source reference {source_word_count}, {local_tokens} tokens)"
        )
    except Exception as e:
        result["status"] = "generation_failed"
        result["error"] = str(e)
        print(f"        FAILED: {e}")
        return result

    # Step 2: Slop check
    print("  [2/5] Running slop check...")
    slop_score, slop_issues, catastrophic = run_slop_check(generated)
    result["slop_score"] = slop_score
    result["slop_issues"] = slop_issues
    print(f"        Slop score: {slop_score}")
    if catastrophic:
        result["status"] = "blocked_slop"
        print("        BLOCKED: catastrophic slop")
        return result

    # Step 3: Novelty audit
    print("  [3/5] Running novelty audit vs source...")
    novelty = audit_novelty(source_text, generated)
    result["novelty"] = novelty
    print(f"        4-gram overlap: {novelty['ngram_overlap']:.1%}, "
          f"shared phrases: {novelty['shared_phrase_count']}")
    if not novelty["pass"]:
        result["status"] = "blocked_novelty"
        print(f"        BLOCKED: {'; '.join(novelty['fail_reasons'])}")
        return result

    # Step 4: Fidelity check
    print("  [4/5] Running fidelity check vs remixed canon...")
    fidelity = check_fidelity(generated, spec_text, remixed_canon)
    result["fidelity"] = fidelity
    print(f"        Beat coverage: {fidelity['beat_coverage']:.0%}, "
          f"Canon consistency: {fidelity['canon_consistency']:.0%}")
    if not fidelity["pass"]:
        result["status"] = "blocked_fidelity"
        print(f"        BLOCKED: {'; '.join(fidelity['fail_reasons'])}")
        return result

    # Step 5: Frontier pairwise (only if pass2 requested)
    if pass2:
        print("  [5/5] Running frontier pairwise vs source chapter...")
        pairwise = run_pairwise_vs_source(generated, source_text, chapter_num)
        result["pairwise"] = pairwise
        result["verdict"] = pairwise["verdict"]
        print(f"        Verdict: {pairwise['verdict']}")
        print(f"        Rationale: {pairwise['rationale'][:200]}")
    else:
        print("  [5/5] Skipping frontier pairwise (no --pass2)")
        result["verdict"] = None

    result["status"] = "complete"

    return result


def save_result(result: dict, chapter_num: int):
    """Save benchmark result to disk."""
    os.makedirs(RESULTS_DIR, exist_ok=True)
    path = os.path.join(RESULTS_DIR, f"chapter_{chapter_num:02d}_result.json")

    # Don't save the full generated text in the result file -- too large
    save_result = {k: v for k, v in result.items() if k != "generated_text"}
    with open(path, "w", encoding="utf-8") as f:
        json.dump(save_result, f, indent=2)
    print(f"  Result saved: {path}")

    # Save the generated chapter separately
    if "generated_text" in result:
        chapter_path = os.path.join(RESULTS_DIR, f"chapter_{chapter_num:02d}_generated.txt")
        with open(chapter_path, "w", encoding="utf-8") as f:
            f.write(result["generated_text"])


def print_spike_summary(results: list[dict]):
    """Print a summary of all spike results."""
    print(f"\n{'='*60}")
    print("SPIKE SUMMARY")
    print(f"{'='*60}")

    wins = 0
    losses = 0
    equals = 0
    blocked = 0

    for r in results:
        status = r.get("status", "unknown")
        verdict = r.get("verdict")
        ch = r.get("chapter", "?")

        if status.startswith("blocked"):
            blocked += 1
            print(f"  Chapter {ch}: BLOCKED ({status})")
        elif verdict == "NEW_BETTER":
            wins += 1
            print(f"  Chapter {ch}: WIN")
        elif verdict == "OLD_BETTER":
            losses += 1
            print(f"  Chapter {ch}: LOSS")
        elif verdict == "EQUAL":
            equals += 1
            print(f"  Chapter {ch}: EQUAL")
        else:
            print(f"  Chapter {ch}: {status} (no verdict)")

    print(f"\nWins: {wins} | Losses: {losses} | Equal: {equals} | Blocked: {blocked}")
    print(f"Total: {len(results)}")

    if wins >= 1:
        print("\nPhase 1 exit criteria: PASSED (at least 1 win)")
    elif any(r.get("verdict") for r in results):
        print("\nPhase 1 exit criteria: NOT MET (zero wins)")
    else:
        print("\nPhase 1 exit criteria: PENDING (no pairwise verdicts yet)")


def _parse_json(raw: str) -> dict:
    """Extract JSON from LLM output."""
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        pass

    import re
    match = re.search(r"```(?:json)?\s*\n(.*?)```", raw, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(1))
        except json.JSONDecodeError:
            pass

    start = raw.find("{")
    end = raw.rfind("}")
    if start != -1 and end != -1 and end > start:
        try:
            return json.loads(raw[start:end + 1])
        except json.JSONDecodeError:
            pass

    return {}


def load_progress() -> dict:
    """Load sequential progress tracker."""
    if os.path.exists(PROGRESS_FILE):
        with open(PROGRESS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"current_chapter": 1, "chapters": {}}


def save_progress(progress: dict):
    """Save sequential progress tracker."""
    os.makedirs(os.path.dirname(PROGRESS_FILE) or ".", exist_ok=True)
    with open(PROGRESS_FILE, "w", encoding="utf-8") as f:
        json.dump(progress, f, indent=2)


def run_sequential(manifest: dict, *, pass2: bool = False):
    """Run the benchmark sequentially: retry each chapter until it passes,
    then advance to the next. This is the primary benchmark mode.

    Sequence:
      1. Load progress (which chapter we're on, attempt counts)
      2. Generate chapter N
      3. If it passes all gates -> accept, save as canonical, advance to N+1
      4. If it fails -> increment attempt counter, retry up to MAX_ATTEMPTS
      5. If max attempts exhausted -> pick best attempt, force-advance
      6. Repeat until all chapters in the book are done
    """
    progress = load_progress()
    all_chapters = sorted([a["chapter"] for a in manifest["artifacts"]])
    total_chapters = len(all_chapters)
    current = progress.get("current_chapter", all_chapters[0])

    # Resume from where we left off
    remaining = [ch for ch in all_chapters if ch >= current]
    if not remaining:
        print("All benchmark chapters completed!")
        _print_final_summary(progress)
        return

    previous_chapter_text = _load_last_accepted_text(progress, current)

    for chapter_num in remaining:
        ch_key = str(chapter_num)
        ch_progress = progress.get("chapters", {}).setdefault(ch_key, {
            "attempts": 0,
            "best_score": 0,
            "best_attempt_file": None,
            "status": "in_progress",
            "results": [],
        })

        if ch_progress.get("status") == "accepted":
            print(f"\n  Chapter {chapter_num} already accepted, skipping.")
            previous_chapter_text = _load_accepted_chapter_text(chapter_num)
            continue

        print(f"\n{'='*60}")
        print(f"BENCHMARK CHAPTER {chapter_num}/{total_chapters}  "
              f"(attempt {ch_progress['attempts'] + 1}/{MAX_ATTEMPTS_PER_CHAPTER})")
        print(f"{'='*60}")

        while ch_progress["attempts"] < MAX_ATTEMPTS_PER_CHAPTER:
            ch_progress["attempts"] += 1
            attempt_num = ch_progress["attempts"]

            result = run_benchmark_chapter(
                chapter_num, manifest, pass2=pass2,
                prior_chapters_summary=_build_recent_summaries(manifest, chapter_num),
                previous_chapter_text=previous_chapter_text,
            )
            save_result(result, chapter_num)

            # Track this attempt
            attempt_record = {
                "attempt": attempt_num,
                "status": result.get("status"),
                "slop_score": result.get("slop_score"),
                "word_count": result.get("word_count"),
                "verdict": result.get("verdict"),
                "timestamp": result.get("timestamp"),
            }
            if result.get("fidelity"):
                attempt_record["beat_coverage"] = result["fidelity"].get("beat_coverage")
            ch_progress["results"].append(attempt_record)

            # Score this attempt for best-attempt tracking
            attempt_score = _score_attempt(result)
            if attempt_score > ch_progress["best_score"]:
                ch_progress["best_score"] = attempt_score
                # Save the generated text for potential forced advance
                if result.get("generated_text"):
                    best_path = os.path.join(
                        RESULTS_DIR,
                        f"chapter_{chapter_num:02d}_best.txt"
                    )
                    os.makedirs(RESULTS_DIR, exist_ok=True)
                    with open(best_path, "w", encoding="utf-8") as f:
                        f.write(result["generated_text"])
                    ch_progress["best_attempt_file"] = best_path

            save_progress(progress)

            # Did it pass?
            if result.get("status") == "complete":
                verdict = result.get("verdict")
                if verdict == "NEW_BETTER" or (not pass2 and result["status"] == "complete"):
                    # Accept this chapter
                    ch_progress["status"] = "accepted"
                    ch_progress["accepted_attempt"] = attempt_num
                    _save_accepted_chapter(chapter_num, result.get("generated_text", ""))
                    previous_chapter_text = result.get("generated_text", "")
                    print(f"\n  >>> Chapter {chapter_num} ACCEPTED on attempt {attempt_num}")
                    break
                elif verdict in ("OLD_BETTER", "EQUAL"):
                    print(f"\n  Chapter {chapter_num} attempt {attempt_num}: "
                          f"passed gates but lost pairwise ({verdict}). Retrying...")
                    continue
            else:
                block_reason = result.get("status", "unknown")
                print(f"\n  Chapter {chapter_num} attempt {attempt_num}: "
                      f"blocked ({block_reason}). Retrying...")

        # Max attempts exhausted — force advance with best attempt
        if ch_progress.get("status") != "accepted":
            print(f"\n  Chapter {chapter_num}: max attempts ({MAX_ATTEMPTS_PER_CHAPTER}) "
                  f"exhausted. Force-advancing with best attempt (score: {ch_progress['best_score']:.1f})")
            ch_progress["status"] = "forced_advance"
            best_text = ""
            if ch_progress.get("best_attempt_file") and os.path.exists(ch_progress["best_attempt_file"]):
                with open(ch_progress["best_attempt_file"], "r", encoding="utf-8") as f:
                    best_text = f.read()
            if best_text:
                _save_accepted_chapter(chapter_num, best_text)
                previous_chapter_text = best_text
            else:
                print(f"  WARNING: No usable text for chapter {chapter_num}, skipping.")
                ch_progress["status"] = "skipped"

        # Advance to next chapter
        next_chapters = [ch for ch in all_chapters if ch > chapter_num]
        if next_chapters:
            progress["current_chapter"] = next_chapters[0]
        save_progress(progress)

    _print_final_summary(progress)


def _score_attempt(result: dict) -> float:
    """Score a benchmark attempt for best-attempt ranking.
    Higher is better. Weights: passing more gates > higher fidelity > lower slop."""
    score = 0.0

    status = result.get("status", "")
    if status == "complete":
        score += 100
        if result.get("verdict") == "NEW_BETTER":
            score += 50
        elif result.get("verdict") == "EQUAL":
            score += 20
    elif status == "blocked_fidelity":
        score += 30
        if result.get("fidelity", {}).get("beat_coverage"):
            score += result["fidelity"]["beat_coverage"] * 30
    elif status == "blocked_novelty":
        score += 20
    elif status == "blocked_slop":
        score += 5

    # Reward lower slop
    slop = result.get("slop_score", 100)
    score += max(0, (100 - slop)) * 0.1

    return score


def _save_accepted_chapter(chapter_num: int, text: str):
    """Save the accepted chapter text as canonical."""
    os.makedirs(RESULTS_DIR, exist_ok=True)
    path = os.path.join(RESULTS_DIR, f"chapter_{chapter_num:02d}_accepted.txt")
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)
    print(f"  Accepted chapter saved: {path}")


def _load_accepted_chapter_text(chapter_num: int) -> str:
    """Load a previously accepted chapter for continuity context."""
    path = os.path.join(RESULTS_DIR, f"chapter_{chapter_num:02d}_accepted.txt")
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    return ""


def _load_last_accepted_text(progress: dict, current_chapter: int) -> str:
    """Find the most recent accepted chapter before current for continuity."""
    for ch in range(current_chapter - 1, 0, -1):
        text = _load_accepted_chapter_text(ch)
        if text:
            return text
    return ""


def _print_final_summary(progress: dict):
    """Print summary of the full sequential run."""
    print(f"\n{'='*60}")
    print("SEQUENTIAL BENCHMARK SUMMARY")
    print(f"{'='*60}")

    accepted = 0
    forced = 0
    skipped = 0
    total_attempts = 0

    for ch_key, ch_data in sorted(progress.get("chapters", {}).items()):
        status = ch_data.get("status", "?")
        attempts = ch_data.get("attempts", 0)
        total_attempts += attempts
        label = f"  Chapter {ch_key}: {status} ({attempts} attempts)"

        if status == "accepted":
            accepted += 1
            label += f" - accepted on attempt {ch_data.get('accepted_attempt', '?')}"
        elif status == "forced_advance":
            forced += 1
            label += f" - best score: {ch_data.get('best_score', 0):.1f}"
        elif status == "skipped":
            skipped += 1
        print(label)

    print(f"\nAccepted: {accepted} | Forced: {forced} | Skipped: {skipped}")
    print(f"Total attempts: {total_attempts}")


def main():
    parser = argparse.ArgumentParser(description="Run benchmark lane evaluation.")
    parser.add_argument("--chapter", type=int, help="Run a single attempt for a specific chapter")
    parser.add_argument("--run", action="store_true",
                        help="Run the sequential benchmark: retry each chapter until pass, then advance")
    parser.add_argument("--pass2", action="store_true", help="Include frontier pairwise comparison")
    parser.add_argument("--compile-only", action="store_true", help="Only compile remix artifacts")
    parser.add_argument("--reset", action="store_true", help="Reset progress and start from chapter 1")
    parser.add_argument("--status", action="store_true", help="Show current benchmark progress")
    args = parser.parse_args()

    if args.compile_only:
        compile_spike(SPIKE_DIR)
        return

    if args.status:
        progress = load_progress()
        _print_final_summary(progress)
        return

    if args.reset:
        if os.path.exists(PROGRESS_FILE):
            os.remove(PROGRESS_FILE)
            print("Progress reset. Next --run starts from chapter 1.")
        else:
            print("No progress file to reset.")
        return

    manifest = load_manifest()

    if args.run:
        run_sequential(manifest, pass2=args.pass2)
    elif args.chapter:
        result = run_benchmark_chapter(args.chapter, manifest, pass2=args.pass2)
        save_result(result, args.chapter)
    else:
        parser.print_help()
        print("\nPrimary mode:")
        print("  --run           Sequential benchmark (chapter 1 until pass, then 2, etc.)")
        print("  --run --pass2   Same but with frontier pairwise vs source")
        print("\nUtility:")
        print("  --chapter N     Single attempt for chapter N")
        print("  --status        Show current progress")
        print("  --reset         Start over from chapter 1")
        print("  --compile-only  Rebuild remix artifacts")


if __name__ == "__main__":
    main()
