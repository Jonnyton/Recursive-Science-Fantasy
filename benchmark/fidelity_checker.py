"""
Benchmark Lane -- Fidelity Checker

Checks that a generated benchmark chapter follows the remixed chapter spec.
Uses the local model to verify the generated chapter hits the required beats
and maintains consistency with the remixed canon.

Returns a fidelity report with pass/fail verdict.
"""

import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from benchmark.ollama_client import call_local, get_ollama_client


def check_fidelity(generated_text: str, chapter_spec: str,
                   remixed_canon: dict) -> dict:
    """Check whether the generated chapter follows the spec and canon.

    Returns:
        {
            "pass": bool,
            "beat_coverage": float (0-1),
            "canon_consistency": float (0-1),
            "missing_beats": list[str],
            "canon_violations": list[str],
            "fail_reasons": list[str],
        }
    """
    client = get_ollama_client()

    system = (
        "You are a story editor checking whether a chapter draft follows its brief. "
        "Be precise. Output valid JSON only."
    )

    # Extract events from remixed canon for the consistency check
    canon_events = remixed_canon.get("events", [])
    canon_characters = remixed_canon.get("characters", [])
    canon_summary = json.dumps({
        "events": canon_events,
        "characters": canon_characters,
        "emotional_arc": remixed_canon.get("emotional_arc", ""),
    }, indent=2)

    user = f"""Check this chapter draft against its brief and canon facts.

CHAPTER BRIEF:
{chapter_spec}

CANON FACTS:
{canon_summary}

GENERATED CHAPTER:
{generated_text[:6000]}

Evaluate and output JSON:
{{
  "beats_required": ["list the 3-5 key beats from the brief"],
  "beats_present": ["which of those beats appear in the draft"],
  "beats_missing": ["which beats are absent or only vaguely hinted"],
  "beat_coverage": 0.0 to 1.0,
  "canon_characters_present": ["characters from canon that appear correctly"],
  "canon_violations": ["any contradictions with canon facts"],
  "canon_consistency": 0.0 to 1.0,
  "emotional_arc_followed": true/false,
  "overall_fidelity": "pass" or "fail",
  "notes": "brief explanation"
}}"""

    try:
        raw, _tokens, _meta = call_local(client, system, user, max_tokens=1536, format_json=True)
    except Exception as exc:
        return {
            "pass": False,
            "beat_coverage": 0.0,
            "canon_consistency": 0.0,
            "missing_beats": [],
            "canon_violations": [],
            "emotional_arc_followed": False,
            "fail_reasons": [f"Local fidelity judge failed: {exc}"],
            "raw_judge": {
                "judge_error": str(exc),
            },
        }

    result = _parse_json(raw)

    # Build structured report
    beat_coverage = float(result.get("beat_coverage", 0))
    canon_consistency = float(result.get("canon_consistency", 0))
    missing = result.get("beats_missing", [])
    violations = result.get("canon_violations", [])
    overall = result.get("overall_fidelity", "fail")

    fail_reasons = []
    if beat_coverage < 0.5:
        fail_reasons.append(f"Beat coverage {beat_coverage:.0%} below 50% minimum")
    if canon_consistency < 0.6:
        fail_reasons.append(f"Canon consistency {canon_consistency:.0%} below 60% minimum")
    if overall == "fail" and not fail_reasons:
        fail_reasons.append("Overall fidelity judged as fail by local model")

    return {
        "pass": len(fail_reasons) == 0,
        "beat_coverage": round(beat_coverage, 2),
        "canon_consistency": round(canon_consistency, 2),
        "missing_beats": missing,
        "canon_violations": violations,
        "emotional_arc_followed": result.get("emotional_arc_followed", False),
        "fail_reasons": fail_reasons,
        "raw_judge": result,
    }


def _parse_json(raw: str) -> dict:
    """Extract JSON from LLM output."""
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        pass

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

    print(f"WARNING: Could not parse fidelity JSON. Raw:\n{raw[:500]}", file=sys.stderr)
    return {}
