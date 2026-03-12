"""
Persona loading and routing for the fantasy writer stack.
"""

from __future__ import annotations

import json
import os
from typing import Dict, List, Optional


PERSONA_DIR = "personas"
PERSONA_INDEX = os.path.join(PERSONA_DIR, "index.json")
PERSONA_STATS = os.path.join(PERSONA_DIR, "persona_stats.json")


def load_persona_registry(persona_dir: str = PERSONA_DIR) -> List[Dict]:
    index_path = os.path.join(persona_dir, "index.json")
    if not os.path.exists(index_path):
        return []

    with open(index_path, "r", encoding="utf-8") as f:
        index = json.load(f)

    personas = []
    for entry in index.get("personas", []):
        path = os.path.join(persona_dir, entry["file"])
        if not os.path.exists(path):
            continue
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        data["role"] = entry.get("role", "draft")
        personas.append(data)
    return personas


def load_persona_stats(stats_path: str = PERSONA_STATS) -> Dict:
    if not os.path.exists(stats_path):
        return {}
    with open(stats_path, "r", encoding="utf-8") as f:
        return json.load(f)


def rebuild_persona_stats(
    experiment_dir: str = "experiments",
    persona_dir: str = PERSONA_DIR,
    stats_path: str = PERSONA_STATS,
) -> Dict:
    registry = load_persona_registry(persona_dir=persona_dir)
    stats: Dict[str, Dict] = {
        persona["id"]: {
            "attempts": 0,
            "keeps": 0,
            "blocks": 0,
            "discards": 0,
            "avg_composite": 0.0,
            "_composite_sum": 0.0,
            "last_used_run_index": None,
            "runs_since_last_use": None,
            "stale_rank": 0,
            "scenario_stats": {},
        }
        for persona in registry
    }
    run_index = 0

    if os.path.exists(experiment_dir):
        for name in sorted(os.listdir(experiment_dir)):
            if not name.endswith(".json"):
                continue
            path = os.path.join(experiment_dir, name)
            try:
                with open(path, "r", encoding="utf-8") as f:
                    record = json.load(f)
            except Exception:
                continue

            status = record.get("status")
            failure_class = record.get("failure_class", "unknown")
            for chapter in record.get("chapter_results", []):
                run_index += 1
                writer_meta = chapter.get("writer_meta") or {}
                persona_plan = writer_meta.get("persona_plan") or {}
                scenario_id = chapter.get("scenario_id")
                composite = float(chapter.get("composite_score", 0) or 0)

                # Determine if this chapter was a slop failure (model issue,
                # not persona issue). We check both record-level failure_class
                # and per-chapter gate_reason for backward compat.
                ch_gate = (chapter.get("focus_group_pass_info") or {}).get("gate_reason", "")
                is_slop_failure = failure_class == "slop" or ch_gate == "catastrophic_slop"

                for persona in persona_plan.get("draft_personas", []):
                    persona_id = persona.get("id") if isinstance(persona, dict) else str(persona)
                    if persona_id not in stats:
                        stats[persona_id] = {
                            "attempts": 0,
                            "keeps": 0,
                            "blocks": 0,
                            "discards": 0,
                            "slop_excluded": 0,
                            "avg_composite": 0.0,
                            "_composite_sum": 0.0,
                            "_scored_attempts": 0,
                            "last_used_run_index": None,
                            "runs_since_last_use": None,
                            "stale_rank": 0,
                            "scenario_stats": {},
                        }
                    entry = stats[persona_id]
                    entry["attempts"] += 1
                    entry["last_used_run_index"] = run_index

                    if is_slop_failure:
                        # Track that we saw it, but don't count slop against
                        # the persona's quality stats — the persona didn't
                        # cause the model to degenerate into repetition.
                        entry["slop_excluded"] = entry.get("slop_excluded", 0) + 1
                    else:
                        # Real outcome — count toward persona quality signal
                        entry["_composite_sum"] += composite
                        entry["_scored_attempts"] = entry.get("_scored_attempts", 0) + 1
                        if status == "keep":
                            entry["keeps"] += 1
                        elif status == "blocked":
                            entry["blocks"] += 1
                        elif status == "discard":
                            entry["discards"] += 1

                    if scenario_id:
                        scenario_entry = entry["scenario_stats"].setdefault(
                            scenario_id,
                            {
                                "attempts": 0,
                                "keeps": 0,
                                "best_composite": 0.0,
                                "last_used_run_index": None,
                            },
                        )
                        scenario_entry["attempts"] += 1
                        scenario_entry["last_used_run_index"] = run_index
                        if not is_slop_failure:
                            if status == "keep":
                                scenario_entry["keeps"] += 1
                            scenario_entry["best_composite"] = max(
                                scenario_entry["best_composite"],
                                composite,
                            )

    draft_persona_ids = {
        persona["id"]
        for persona in registry
        if persona.get("role") == "draft"
    }
    staleness_order = sorted(
        (
            (persona_id, entry)
            for persona_id, entry in stats.items()
            if persona_id in draft_persona_ids
        ),
        key=lambda item: item[1]["last_used_run_index"] if item[1]["last_used_run_index"] is not None else -1,
    )
    for persona_id, entry in stats.items():
        # Use scored_attempts (excludes slop) for avg_composite so model
        # degeneration doesn't drag down persona quality signal
        scored = entry.get("_scored_attempts", 0)
        entry["avg_composite"] = round(entry["_composite_sum"] / scored, 2) if scored else 0.0
        last_used = entry.get("last_used_run_index")
        if run_index:
            entry["runs_since_last_use"] = run_index - last_used if last_used is not None else run_index + 1
        else:
            entry["runs_since_last_use"] = 0
        for scenario_entry in entry.get("scenario_stats", {}).values():
            last_scenario_use = scenario_entry.get("last_used_run_index")
            if run_index:
                scenario_entry["runs_since_last_use"] = (
                    run_index - last_scenario_use if last_scenario_use is not None else run_index + 1
                )
            else:
                scenario_entry["runs_since_last_use"] = 0
        entry.pop("_composite_sum", None)
        entry.pop("_scored_attempts", None)
    total_personas = len(staleness_order)
    for index, (_persona_id, entry) in enumerate(staleness_order):
        entry["stale_rank"] = total_personas - index

    os.makedirs(os.path.dirname(stats_path), exist_ok=True)
    with open(stats_path, "w", encoding="utf-8") as f:
        json.dump(stats, f, indent=2)
    return stats


def _score_persona(
    persona: Dict,
    scenario: Dict,
    weakest_dimension: Optional[str],
    series_mode: bool,
    persona_stats: Optional[Dict] = None,
) -> int:
    score = 0
    tags = set(scenario.get("genre_tags", []))
    preferred = set(persona.get("preferred_tags", []))
    focus_dimensions = set(persona.get("focus_dimensions", []))

    score += len(tags & preferred) * 4

    if weakest_dimension and weakest_dimension in focus_dimensions:
        score += 7

    if series_mode and persona.get("series_safe"):
        score += 3
    if series_mode and not persona.get("series_safe"):
        score -= 4

    stats = (persona_stats or {}).get(persona.get("id"), {})
    attempts = stats.get("attempts", 0)
    slop_excluded = stats.get("slop_excluded", 0)
    scored_attempts = max(attempts - slop_excluded, 0)
    keeps = stats.get("keeps", 0)
    if scored_attempts:
        # Use scored_attempts (excludes slop) so model degeneration
        # doesn't unfairly penalize persona keep_rate
        keep_rate = keeps / max(scored_attempts, 1)
        score += int(keep_rate * 10)
        score += int(max(stats.get("avg_composite", 0) - 50, 0) / 5)
    else:
        score += 3
    runs_since_last_use = stats.get("runs_since_last_use", 0) or 0
    if attempts:
        score += min(int(runs_since_last_use / 4), 2)
    score += 1 if stats.get("stale_rank", 0) >= 2 else 0
    scenario_stats = stats.get("scenario_stats", {}).get(scenario.get("id"), {})
    if scenario_stats:
        score += min(scenario_stats.get("keeps", 0) * 3, 6)
        score += min(int(scenario_stats.get("best_composite", 0) / 15), 6)

    return score


def choose_persona_plan(
    scenario: Dict,
    weakest_dimension: Optional[str] = None,
    max_draft_personas: int = 2,
    persona_dir: str = PERSONA_DIR,
) -> Dict:
    personas = load_persona_registry(persona_dir=persona_dir)
    persona_stats = load_persona_stats()
    if not personas:
        return {
            "draft_personas": [],
            "final_persona": None,
            "selection_note": "No persona registry found.",
        }

    series_mode = bool(scenario.get("_series_context"))
    draft_candidates = [p for p in personas if p.get("role") == "draft"]
    final_candidates = [p for p in personas if p.get("role") == "final"]

    ranked = sorted(
        draft_candidates,
        key=lambda p: (_score_persona(p, scenario, weakest_dimension, series_mode, persona_stats), p["id"]),
        reverse=True,
    )
    selected = ranked[:max_draft_personas]

    final_persona = None
    if series_mode:
        final_series = [p for p in final_candidates if p.get("series_safe")]
        if final_series:
            final_persona = sorted(final_series, key=lambda p: p["id"])[0]

    notes = []
    if weakest_dimension:
        notes.append(f"targeting weakest dimension: {weakest_dimension}")
    if scenario.get("genre_tags"):
        notes.append("tags=" + ",".join(scenario["genre_tags"]))
    if selected:
        notes.append("draft=" + ",".join(p["id"] for p in selected))
    if final_persona:
        notes.append("final=" + final_persona["id"])

    return {
        "draft_personas": selected,
        "final_persona": final_persona,
        "selection_note": " | ".join(notes) if notes else "default",
    }


def get_persona_by_id(persona_id: str, persona_dir: str = PERSONA_DIR) -> Optional[Dict]:
    for persona in load_persona_registry(persona_dir=persona_dir):
        if persona.get("id") == persona_id:
            return persona
    return None
