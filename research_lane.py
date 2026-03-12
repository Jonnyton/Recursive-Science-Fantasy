"""
Online research lane for weakness-targeted craft and infrastructure research.

Local models should do the heavy summarization and synthesis work.
This script performs web fetches, weak-dimension analysis, and draft card generation.
"""

from __future__ import annotations

import argparse
import datetime
import html
from html.parser import HTMLParser
import json
import os
import re
from typing import Dict, List
from urllib.parse import parse_qs, quote_plus, unquote, urlparse
from urllib.request import Request, urlopen

from openai import OpenAI


LOCAL_MODEL = "qwen3.5"
LOCAL_BASE_URL = "http://localhost:11434"
RESEARCH_DIR = "research"
NOTES_DIR = os.path.join(RESEARCH_DIR, "notes")
QUEUE_FILE = os.path.join(RESEARCH_DIR, "research_queue.json")
TRACKER_FILE = os.path.join(RESEARCH_DIR, "weakness_tracker.json")
SOURCE_FILE = os.path.join(RESEARCH_DIR, "source_registry.json")
CRAFT_DRAFT_DIR = os.path.join("craft_cards", "drafts")
MAX_PAGE_CHARS = 8000


class _TextExtractor(HTMLParser):
    def __init__(self):
        super().__init__()
        self._chunks: List[str] = []
        self._skip = False

    def handle_starttag(self, tag, attrs):
        if tag in {"script", "style", "noscript"}:
            self._skip = True

    def handle_endtag(self, tag):
        if tag in {"script", "style", "noscript"}:
            self._skip = False
        elif tag in {"p", "div", "section", "article", "li", "h1", "h2", "h3", "h4"}:
            self._chunks.append("\n")

    def handle_data(self, data):
        if not self._skip:
            text = data.strip()
            if text:
                self._chunks.append(text)

    def text(self) -> str:
        joined = " ".join(self._chunks)
        joined = re.sub(r"\s+", " ", joined)
        return html.unescape(joined).strip()


def get_local_client() -> OpenAI:
    return OpenAI(base_url=f"{LOCAL_BASE_URL}/v1", api_key="ollama")


def call_local_json(system_prompt: str, user_prompt: str, max_tokens: int = 2048, temperature: float = 0.2) -> Dict:
    client = get_local_client()
    response = client.chat.completions.create(
        model=LOCAL_MODEL,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt + "\n\n/no_think"},
        ],
        max_tokens=max_tokens,
        temperature=temperature,
    )
    raw = response.choices[0].message.content.strip()
    raw = re.sub(r"<think>.*?</think>", "", raw, flags=re.DOTALL).strip()
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[1].rsplit("```", 1)[0].strip()
    if not raw.startswith("{") and not raw.startswith("["):
        match = re.search(r"\{.*\}|\[.*\]", raw, re.DOTALL)
        if match:
            raw = match.group(0)
    return json.loads(raw)


def ensure_dirs():
    os.makedirs(RESEARCH_DIR, exist_ok=True)
    os.makedirs(NOTES_DIR, exist_ok=True)
    os.makedirs(CRAFT_DRAFT_DIR, exist_ok=True)


def load_json(path: str, default):
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    return default


def save_json(path: str, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


BORDERLINE_LEARNINGS_FILE = os.path.join(RESEARCH_DIR, "borderline_learnings.json")
SUCCESS_RECIPES_FILE = os.path.join(RESEARCH_DIR, "success_recipes.json")


def extract_borderline_learnings(limit: int = 10) -> List[Dict]:
    """Extract actionable craft feedback from borderline failures.

    Borderline runs are the most valuable failures: they got real scores from
    the cheap judge (and sometimes focus group readers) but didn't clear the
    gate. Their per-reader rationales contain specific, actionable craft
    critique that should feed back into the writing system.

    Returns a list of learning entries, each containing:
      - scenario_id, timestamp, composite
      - weakest_dim (real, not synthetic)
      - per-dimension scores (real)
      - reader rationales (the actual critique text)
      - distilled_lessons (extracted patterns)
    """
    ensure_dirs()
    records = iter_experiment_records(limit=limit)
    existing = load_json(BORDERLINE_LEARNINGS_FILE, [])
    existing_timestamps = {entry.get("timestamp") for entry in existing}

    new_learnings = []
    for record in records:
        fc = record.get("failure_class", "unknown")
        if fc not in ("borderline", "craft"):
            continue
        ts = record.get("timestamp")
        if ts in existing_timestamps:
            continue  # already extracted

        # Gather real reader critique
        rationales = []
        for ch in record.get("chapter_results", []):
            # From cheap screen scores
            fgpi = ch.get("focus_group_pass_info") or {}
            cheap_screen = fgpi.get("cheap_screen")
            if cheap_screen and cheap_screen.get("composite"):
                rationales.append({
                    "source": "cheap_judge",
                    "scenario_id": ch.get("scenario_id"),
                    "composite": cheap_screen.get("composite"),
                    "scores": {k: v for k, v in cheap_screen.items()
                               if k not in ("pass", "composite", "reasons")},
                })

        # From reader_feedback (focus group readers)
        for rf in record.get("reader_feedback", []):
            if rf.get("rationale"):
                rationales.append({
                    "source": f"reader_{rf.get('reader', 'unknown')}",
                    "scenario_id": rf.get("scenario"),
                    "composite": rf.get("composite"),
                    "rationale": rf.get("rationale"),
                    "scores": rf.get("scores", {}),
                })

        # From Claude pairwise rationale (chapter_results[].rationale)
        # This captures frontier-model critique on discards — the highest
        # quality feedback in the system.
        for ch in record.get("chapter_results", []):
            rat = ch.get("rationale", "")
            verdict = ch.get("verdict", "")
            if rat and verdict in ("OLD_BETTER", "EQUAL"):
                rationales.append({
                    "source": "claude_pairwise",
                    "scenario_id": ch.get("scenario_id"),
                    "composite": ch.get("composite_score"),
                    "rationale": rat,
                    "verdict": verdict,
                })

        if not rationales:
            continue

        learning = {
            "timestamp": ts,
            "scenario_ids": record.get("scenario_ids", []),
            "failure_class": fc,
            "composite": record.get("composite"),
            "weakest_dim": record.get("weakest_dim"),
            "dimensions": record.get("dimensions", {}),
            "rationales": rationales,
        }
        new_learnings.append(learning)

    if new_learnings:
        existing.extend(new_learnings)
        # Keep last 30 learnings to avoid unbounded growth
        existing = existing[-30:]
        save_json(BORDERLINE_LEARNINGS_FILE, existing)

    return new_learnings


def extract_success_recipes(limit: int = 15) -> List[Dict]:
    """Extract what worked from passing and kept runs.

    The system learns plenty from failures but nothing from wins. This
    captures the 'recipe' — which persona, craft cards, weakness target,
    and scenario produced a pass — so the writer can be told what to do
    MORE of, not just what to avoid.

    Also captures positive reader feedback from passing focus groups.
    """
    ensure_dirs()
    records = iter_experiment_records(limit=limit)
    existing = load_json(SUCCESS_RECIPES_FILE, [])
    existing_timestamps = {entry.get("timestamp") for entry in existing}

    new_recipes = []
    for record in records:
        fc = record.get("failure_class", "unknown")
        if fc != "pass":
            continue
        ts = record.get("timestamp")
        if ts in existing_timestamps:
            continue

        for ch in record.get("chapter_results", []):
            writer_meta = ch.get("writer_meta") or {}
            persona_plan = writer_meta.get("persona_plan") or {}
            draft_personas = persona_plan.get("draft_personas", [])
            persona_ids = [
                p.get("id") if isinstance(p, dict) else str(p)
                for p in draft_personas
            ]

            # Positive reader quotes
            positive_notes = []
            for rf in record.get("reader_feedback", []):
                rat = rf.get("rationale", "")
                comp = rf.get("composite", 0)
                if rat and comp and comp >= 60:
                    positive_notes.append(rat[:200])

            # Claude's positive rationale on keeps
            verdict = ch.get("verdict", "")
            if verdict == "NEW_BETTER" and ch.get("rationale"):
                positive_notes.append(ch["rationale"][:200])

            recipe = {
                "timestamp": ts,
                "scenario_id": ch.get("scenario_id"),
                "composite": ch.get("composite_score"),
                "weakness_target": writer_meta.get("weakness_target"),
                "persona_ids": persona_ids,
                "craft_card_ids": writer_meta.get("craft_card_ids", []),
                "status": record.get("status"),
                "verdict": verdict or None,
                "strongest_dims": _top_dims(ch.get("new_scores") or record.get("dimensions", {}), n=3),
                "positive_notes": positive_notes[:2],
            }
            new_recipes.append(recipe)

    if new_recipes:
        existing.extend(new_recipes)
        existing = existing[-20:]
        save_json(SUCCESS_RECIPES_FILE, existing)

    return new_recipes


def _top_dims(scores: Dict, n: int = 3) -> List[str]:
    """Return the top N scoring dimensions from a scores dict."""
    numeric = {k: v for k, v in scores.items()
               if isinstance(v, (int, float)) and k != "brief_rationale"}
    return [k for k, _ in sorted(numeric.items(), key=lambda x: -x[1])[:n]]


def iter_experiment_records(limit: int = 10) -> List[Dict]:
    exp_dir = "experiments"
    if not os.path.exists(exp_dir):
        return []
    names = sorted(
        [name for name in os.listdir(exp_dir) if name.endswith(".json")],
        reverse=True,
    )[:limit]
    records = []
    for name in names:
        path = os.path.join(exp_dir, name)
        with open(path, "r", encoding="utf-8") as f:
            records.append(json.load(f))
    return records


def update_weakness_tracker(limit: int = 10) -> Dict:
    """Update weakness tracker from recent experiments.

    Key insight: slop-blocked runs produce *synthetic* dimension scores that
    don't reflect actual writing weaknesses. The tracker now separates:
      - craft_counts: weakest_dim from runs with real evaluation
      - slop_streak: consecutive slop failures (model capability issue)
      - borderline_counts: weakest_dim from runs that got real cheap-judge
        scores but failed a gate (partial but genuine signal)
    """
    ensure_dirs()
    records = iter_experiment_records(limit=limit)
    tracker = {
        "dimensions": {},
        "slop_health": {},
        "updated_at": datetime.datetime.now().isoformat(),
    }
    if not records:
        save_json(TRACKER_FILE, tracker)
        return tracker

    counts = {}
    sums = {}
    last_seen = {}
    slop_count = 0
    slop_streak = 0       # consecutive slop failures from most recent
    streak_broken = False
    total_records = len(records)

    for record in records:
        fc = record.get("failure_class", "unknown")

        # Track slop streak (records are newest-first from iter_experiment_records)
        if not streak_broken:
            if fc == "slop":
                slop_streak += 1
            else:
                streak_broken = True

        if fc == "slop":
            slop_count += 1
            # Don't count synthetic scores toward craft weakness tracking
            continue

        dim = record.get("weakest_dim")
        if dim:
            # Borderline runs have real scores — count at half weight
            weight = 0.5 if fc == "borderline" else 1.0
            counts[dim] = counts.get(dim, 0) + weight
            last_seen[dim] = record.get("timestamp")

        for key, value in record.get("dimensions", {}).items():
            if isinstance(value, (int, float)):
                sums.setdefault(key, []).append(value)

    all_dims = set(counts) | set(sums)
    for dim in sorted(all_dims):
        avg = None
        if dim in sums and sums[dim]:
            avg = round(sum(sums[dim]) / len(sums[dim]), 2)
        recent_count = counts.get(dim, 0)
        tracker["dimensions"][dim] = {
            "recent_count": recent_count,
            "recent_average": avg,
            "last_seen": last_seen.get(dim),
            "research_status": "needed" if recent_count >= 3 else "clear",
        }

    # Slop health: surface model-capability issues separately from craft
    non_slop = total_records - slop_count
    tracker["slop_health"] = {
        "slop_rate": round(slop_count / total_records, 2) if total_records else 0,
        "slop_streak": slop_streak,
        "slop_count": slop_count,
        "non_slop_count": non_slop,
        "total_records": total_records,
        "model_issue": slop_streak >= 3 or (slop_count / max(total_records, 1)) > 0.6,
        "note": (
            "High slop rate indicates model-capability bottleneck, not craft weakness. "
            "Consider: model swap, temperature adjustment, or prompt restructuring."
            if slop_streak >= 3 or (slop_count / max(total_records, 1)) > 0.6
            else "Slop rate within normal range."
        ),
    }

    save_json(TRACKER_FILE, tracker)
    return tracker


def target_queries_for_dimension(dimension: str) -> List[str]:
    query_map = {
        "dialogue_craft": [
            "site:.edu creative writing dialogue subtext",
            "fantasy writing dialogue subtext craft official",
        ],
        "pacing_and_transitions": [
            "site:.edu creative writing pacing revision transitions",
            "novel scene transitions pacing writing official",
        ],
        "originality": [
            "fantasy writing avoid cliche originality official",
            "creative writing originality metaphor cliche official",
        ],
        "emotional_resonance": [
            "site:.edu creative writing emotional resonance embodiment",
            "fiction writing emotion embodiment official",
        ],
        "continuity": [
            "long story consistency benchmark narrative contradiction arxiv",
            "story state narrative consistency arxiv",
        ],
        "arc_progression": [
            "character arc progression scene by scene creative writing official",
        ],
        "thread_management": [
            "plot thread management long novel official",
            "foreshadowing payoff narrative consistency official",
        ],
    }
    return query_map.get(dimension, [f"{dimension} fantasy writing improvement official"])


def search_duckduckgo(query: str, max_results: int = 5) -> List[Dict]:
    url = f"https://lite.duckduckgo.com/lite/?q={quote_plus(query)}"
    req = Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urlopen(req, timeout=30) as resp:
        body = resp.read().decode("utf-8", errors="ignore")

    matches = re.findall(r'<a[^>]+href="([^"]+)"[^>]*>(.*?)</a>', body, flags=re.IGNORECASE | re.DOTALL)
    results = []
    seen = set()
    for href, title in matches:
        href = html.unescape(href)
        title = re.sub(r"<.*?>", "", html.unescape(title)).strip()
        if "duckduckgo.com/l/?" in href:
            qs = parse_qs(urlparse(href).query)
            href = unquote(qs.get("uddg", [href])[0])
        if not href.startswith("http"):
            continue
        if href in seen:
            continue
        seen.add(href)
        results.append({"title": title, "url": href})
        if len(results) >= max_results:
            break
    return results


def fetch_page_text(url: str) -> str:
    req = Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urlopen(req, timeout=30) as resp:
        body = resp.read().decode("utf-8", errors="ignore")
    parser = _TextExtractor()
    parser.feed(body)
    text = parser.text()
    return text[:MAX_PAGE_CHARS]


def queue_research_from_tracker(limit_targets: int = 2) -> List[Dict]:
    """Queue research based on weakness tracker findings.

    Now respects the slop/craft split: if the tracker shows a model-capability
    issue (high slop rate), it queues a 'model_capability' research item
    instead of (or in addition to) craft research. This prevents the system
    from endlessly researching 'chapter_arc' when the real problem is that
    the local model can't produce coherent text.
    """
    ensure_dirs()
    tracker = update_weakness_tracker()

    # Also extract learnings while we're here
    extract_borderline_learnings()
    extract_success_recipes()

    queue = load_json(QUEUE_FILE, [])
    existing_targets = {item.get("target_dimension") for item in queue if item.get("status") in {"queued", "running"}}

    # If slop health indicates model-capability issue, queue that first
    slop_health = tracker.get("slop_health", {})
    if slop_health.get("model_issue") and "model_capability" not in existing_targets:
        queue.append({
            "id": f"rq-{datetime.datetime.now().strftime('%Y%m%d-%H%M%S')}-model_capability",
            "kind": "infrastructure",
            "target_dimension": "model_capability",
            "trigger": f"slop_streak={slop_health.get('slop_streak', 0)}, slop_rate={slop_health.get('slop_rate', 0)}",
            "priority": "critical",
            "status": "queued",
            "query_brief": (
                "Model is producing catastrophic repetition at high rate. "
                "Investigate: model swap options, generation parameter tuning "
                "(temperature, repetition_penalty, top_p), prompt length reduction, "
                "or structured generation constraints."
            ),
        })

    candidates = sorted(
        [
            (dim, meta)
            for dim, meta in tracker.get("dimensions", {}).items()
            if meta.get("research_status") == "needed" and dim not in existing_targets
        ],
        key=lambda item: (item[1].get("recent_count", 0), -(item[1].get("recent_average") or 100)),
        reverse=True,
    )[:limit_targets]

    for dim, meta in candidates:
        queue.append({
            "id": f"rq-{datetime.datetime.now().strftime('%Y%m%d-%H%M%S')}-{dim}",
            "kind": "craft" if dim in {
                "dialogue_craft",
                "pacing_and_transitions",
                "originality",
                "emotional_resonance",
                "character_voice",
                "prose_quality",
            } else "infrastructure",
            "target_dimension": dim,
            "trigger": f"recent_count={meta.get('recent_count', 0)}",
            "priority": "high",
            "status": "queued",
            "query_brief": f"Find concrete ways to improve {dim} for fantasy writing.",
        })

    save_json(QUEUE_FILE, queue)
    return queue


def research_target(target_dimension: str, max_results: int = 4) -> Dict:
    ensure_dirs()
    notes = {
        "target_dimension": target_dimension,
        "timestamp": datetime.datetime.now().isoformat(),
        "queries": [],
        "sources": [],
    }
    registry = load_json(SOURCE_FILE, [])

    for query in target_queries_for_dimension(target_dimension):
        sources = search_duckduckgo(query, max_results=max_results)
        notes["queries"].append({"query": query, "results": sources})
        for src in sources:
            if any(existing.get("url") == src["url"] for existing in notes["sources"]):
                continue
            try:
                text = fetch_page_text(src["url"])
            except Exception as exc:
                text = f"[fetch failed: {exc}]"
            notes["sources"].append({
                "title": src["title"],
                "url": src["url"],
                "excerpt": text,
            })
            if not any(existing.get("url") == src["url"] for existing in registry):
                registry.append({
                    "source_id": f"src-{len(registry)+1:04d}",
                    "title": src["title"],
                    "url": src["url"],
                    "kind": "web",
                    "approved_for": [target_dimension],
                    "notes": "",
                })

    save_json(SOURCE_FILE, registry)
    note_path = os.path.join(NOTES_DIR, f"{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}_{target_dimension}.json")
    save_json(note_path, notes)
    return notes


def draft_craft_card_from_notes(notes: Dict) -> Dict:
    sources = notes.get("sources", [])[:4]
    source_blob = "\n\n".join(
        f"TITLE: {src['title']}\nURL: {src['url']}\nEXCERPT:\n{src['excerpt'][:2500]}"
        for src in sources
    )
    target_dimension = notes["target_dimension"]
    system_prompt = (
        "You are a writing-craft researcher. Produce one compact, testable craft card for a fantasy-writing system. "
        "Return only valid JSON."
    )
    user_prompt = f"""Target dimension: {target_dimension}

Using the sources below, produce ONE testable craft-card draft for improving this dimension in fantasy writing.

Rules:
- Be concrete.
- Avoid generic advice.
- Tie the card to the target dimension.
- Include likely failure modes.
- Include the source URLs you used.

Sources:
{source_blob}

Return JSON:
{{
  "card_id": "<short-id>",
  "target_dimension": "{target_dimension}",
  "secondary_dimension": "<optional or empty>",
  "technique": "<2-4 sentences>",
  "why_it_may_help": "<2-4 sentences>",
  "failure_modes": ["<mode 1>", "<mode 2>"],
  "source_links": ["<url 1>", "<url 2>"]
}}"""
    return call_local_json(system_prompt, user_prompt, max_tokens=1400, temperature=0.2)


def write_craft_card_draft(card: Dict) -> str:
    ensure_dirs()
    filename = f"{card['card_id']}.md"
    path = os.path.join(CRAFT_DRAFT_DIR, filename)
    content = "\n".join([
        f"# {card['card_id']}",
        "",
        f"- Target dimension: {card['target_dimension']}",
        f"- Secondary dimension: {card.get('secondary_dimension', '')}",
        f"- Source links: {', '.join(card.get('source_links', []))}",
        "",
        "## Technique",
        "",
        card["technique"],
        "",
        "## Why it may help",
        "",
        card["why_it_may_help"],
        "",
        "## Failure modes",
        "",
        *[f"- {item}" for item in card.get("failure_modes", [])],
    ])
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    return path


def main():
    parser = argparse.ArgumentParser(description="Research lane for autoresearch-fantasy")
    parser.add_argument("--update-weaknesses", action="store_true", help="Update weakness tracker from recent experiments")
    parser.add_argument("--queue-from-history", action="store_true", help="Queue research from recent weakness patterns")
    parser.add_argument("--extract-learnings", action="store_true", help="Extract actionable feedback from borderline failures")
    parser.add_argument("--target", type=str, help="Run research for a specific target dimension")
    parser.add_argument("--draft-card", action="store_true", help="Draft a craft card after research")
    args = parser.parse_args()

    if args.extract_learnings:
        learnings = extract_borderline_learnings()
        print(f"Extracted {len(learnings)} new borderline learnings.")
        if learnings:
            print(json.dumps(learnings, indent=2))
        return

    if args.update_weaknesses:
        tracker = update_weakness_tracker()
        print(json.dumps(tracker, indent=2))
        return

    if args.queue_from_history:
        queue = queue_research_from_tracker()
        print(json.dumps(queue, indent=2))
        return

    if args.target:
        notes = research_target(args.target)
        print(json.dumps({
            "target_dimension": notes["target_dimension"],
            "source_count": len(notes.get("sources", [])),
            "note_file": "written to research/notes/",
        }, indent=2))
        if args.draft_card:
            card = draft_craft_card_from_notes(notes)
            card_path = write_craft_card_draft(card)
            print(json.dumps({
                "card_id": card["card_id"],
                "card_path": card_path,
            }, indent=2))
        return

    parser.print_help()


if __name__ == "__main__":
    main()
