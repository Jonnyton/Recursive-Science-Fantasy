"""
Benchmark Lane -- Remix Compiler

Transforms source chapter text into blind remixed artifacts:
  - source_canon: extracted facts, characters, events (hidden from writer)
  - remixed_canon: renamed characters/places/details (shown to writer)
  - chapter_specs: per-chapter objectives for the writer (shown to writer)

All LLM calls use the local Ollama model to keep costs at zero.

Usage:
    python benchmark/remix_compiler.py --spike-dir benchmark/spike_inputs --chapters 5
"""

import argparse
import json
import os
import re
import sys

# Add parent dir so we can import evaluate.py helpers
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from benchmark.ollama_client import call_local, get_ollama_client


def extract_source_canon(client, chapter_text: str, chapter_num: int,
                         prior_canon: str = "") -> dict:
    """Extract structured facts from a source chapter (hidden from writer)."""
    system = (
        "You are a literary analyst. Extract structured facts from the given "
        "chapter. Output valid JSON only, no commentary."
    )
    user = f"""Analyze this chapter and extract the following as JSON:

{{
  "chapter_number": {chapter_num},
  "characters": [
    {{"name": "...", "role": "...", "key_traits": ["..."], "relationships": ["..."]}}
  ],
  "locations": [
    {{"name": "...", "description": "...", "significance": "..."}}
  ],
  "events": [
    {{"summary": "...", "characters_involved": ["..."], "consequence": "..."}}
  ],
  "themes": ["..."],
  "emotional_arc": "starting emotion -> ending emotion",
  "magic_or_wonder": ["any fantastical elements"],
  "chapter_objective": "one-sentence summary of what this chapter accomplishes narratively"
}}

Prior canon context (if any):
{prior_canon or "(this is the first chapter)"}

Chapter text:
{chapter_text}"""

    raw, _tokens, _meta = call_local(client, system, user, max_tokens=2048, format_json=True)
    return _normalize_source_canon(_parse_json(raw), chapter_num)


def build_name_map(client, source_canons: list[dict]) -> dict:
    """Build a consistent character/location name remapping from extracted canons."""
    system = (
        "You are a fantasy worldbuilder. Create new names for all characters and "
        "locations from the source material. Names should feel like they belong in "
        "a different but equally rich fantasy world. Output valid JSON only."
    )

    # Collect all unique names
    all_characters = set()
    all_locations = set()
    for canon in source_canons:
        for c in canon.get("characters", []):
            all_characters.add(c.get("name", ""))
        for loc in canon.get("locations", []):
            all_locations.add(loc.get("name", ""))

    all_characters.discard("")
    all_locations.discard("")

    user = f"""Create replacement names for these characters and locations.
The new names should:
- Sound like they belong in a different fantasy tradition (not Celtic/Anglo-Saxon)
- Be easy to pronounce and distinct from each other
- Maintain approximate cultural register (a king should still sound regal)

Characters: {sorted(all_characters)}
Locations: {sorted(all_locations)}

Output JSON:
{{
  "characters": {{"original_name": "new_name", ...}},
  "locations": {{"original_name": "new_name", ...}},
  "world_name": "a new name for this fantasy world"
}}"""

    raw, _tokens, _meta = call_local(client, system, user, max_tokens=1024, format_json=True)
    return _normalize_name_map(_parse_json(raw))


def build_remixed_canon(client, source_canon: dict, name_map: dict) -> dict:
    """Transform source canon into remixed canon using the name map."""
    system = (
        "You are a fantasy worldbuilder. Rewrite the given story facts using "
        "the provided name substitutions. Change surface details (specific objects, "
        "colors, materials) while keeping the emotional arc and narrative structure "
        "intact. Output valid JSON only."
    )

    user = f"""Rewrite this chapter's canon using the name map below.
Change surface details (specific imagery, materials, sensory textures) to feel
like a different fantasy world while preserving:
- The emotional arc
- The narrative structure and key plot beats
- Character relationships and motivations
- The chapter's thematic purpose

Name map:
{json.dumps(name_map, indent=2)}

Source canon:
{json.dumps(source_canon, indent=2)}

Output the remixed canon as JSON with the same structure but all names and
surface details changed."""

    raw, _tokens, _meta = call_local(client, system, user, max_tokens=2048, format_json=True)
    return _normalize_remixed_canon(_parse_json(raw), source_canon)


def build_chapter_spec(client, remixed_canon: dict, chapter_num: int,
                       prior_remixed_summary: str = "") -> str:
    """Build a writer-facing chapter objective from remixed canon."""
    system = (
        "You are a writing director. Create a chapter brief for a fantasy writer. "
        "The brief should describe what the chapter must accomplish without "
        "dictating specific prose. Focus on emotional arc, character goals, "
        "key scene beats, and the chapter's purpose in the larger story."
    )

    user = f"""Write a chapter brief (200-300 words) for Chapter {chapter_num}.

The writer will receive ONLY this brief plus prior chapter summaries.
They have never seen the source material.

Include:
- The chapter's narrative objective (what must change by the end)
- The emotional arc (where the POV character starts and ends emotionally)
- 3-5 key scene beats the chapter must hit
- The central tension or question driving the chapter
- One sensory/atmospheric anchor for the setting
- What the chapter should set up for the next chapter

Do NOT include:
- Specific prose suggestions
- Exact dialogue
- Craft instructions (the writer has their own writing system)

Prior story context:
{prior_remixed_summary or "(this is the first chapter)"}

Chapter facts:
{json.dumps(remixed_canon, indent=2)}

Write the brief as plain prose paragraphs, not bullet points."""

    spec, _tokens, _meta = call_local(client, system, user, max_tokens=1024, temperature=0.5)
    spec = spec.strip()
    if not spec:
        raise ValueError(f"Empty chapter spec returned for chapter {chapter_num}")
    return spec


def compile_spike(spike_dir: str, num_chapters: int = 5) -> dict:
    """Run the full remix compilation pipeline for a validation spike.

    Returns a manifest dict with paths to all generated artifacts.
    """
    client = get_ollama_client()

    # Find chapter files
    chapter_files = sorted([
        f for f in os.listdir(spike_dir)
        if f.startswith("chapter_") and f.endswith(".txt")
    ])[:num_chapters]

    if not chapter_files:
        raise FileNotFoundError(f"No chapter files found in {spike_dir}")

    print(f"Compiling remix for {len(chapter_files)} chapters...")

    # Phase 1: Extract source canons
    source_canons = []
    prior_canon_text = ""
    for i, filename in enumerate(chapter_files):
        filepath = os.path.join(spike_dir, filename)
        with open(filepath, "r", encoding="utf-8") as f:
            chapter_text = f.read()

        chapter_num = i + 1
        print(f"  Extracting source canon for chapter {chapter_num}...")
        canon = extract_source_canon(client, chapter_text, chapter_num, prior_canon_text)
        source_canons.append(canon)
        prior_canon_text = json.dumps(canon, indent=2)

    # Phase 2: Build name map
    print("  Building name map...")
    name_map = build_name_map(client, source_canons)

    # Phase 3: Build remixed canons and chapter specs
    remixed_canons = []
    chapter_specs = []
    prior_summary = ""
    for i, canon in enumerate(source_canons):
        chapter_num = i + 1
        print(f"  Remixing canon for chapter {chapter_num}...")
        remixed = build_remixed_canon(client, canon, name_map)
        remixed_canons.append(remixed)

        print(f"  Building chapter spec for chapter {chapter_num}...")
        spec = build_chapter_spec(client, remixed, chapter_num, prior_summary)
        chapter_specs.append(spec)

        # Build running summary for next chapter's context
        objective = remixed.get("chapter_objective", "")
        prior_summary += f"\nChapter {chapter_num}: {objective}"

    # Phase 4: Write artifacts
    source_dir = "benchmark/source_canon"
    remix_dir = "benchmark/remixed_canon"
    specs_dir = "benchmark/chapter_specs"
    os.makedirs(source_dir, exist_ok=True)
    os.makedirs(remix_dir, exist_ok=True)
    os.makedirs(specs_dir, exist_ok=True)

    manifest = {
        "source_book": "The King of Elfland's Daughter",
        "author": "Lord Dunsany",
        "num_chapters": len(chapter_files),
        "name_map": name_map,
        "series_summary": _build_series_summary(name_map, remixed_canons),
        "artifacts": [],
    }

    for i in range(len(chapter_files)):
        chapter_num = i + 1
        prefix = f"chapter_{chapter_num:02d}"

        # Source canon (hidden)
        sc_path = os.path.join(source_dir, f"{prefix}_canon.json")
        with open(sc_path, "w", encoding="utf-8") as f:
            json.dump(source_canons[i], f, indent=2)

        # Remixed canon (hidden from writer, used for fidelity checks)
        rc_path = os.path.join(remix_dir, f"{prefix}_remixed.json")
        with open(rc_path, "w", encoding="utf-8") as f:
            json.dump(remixed_canons[i], f, indent=2)

        # Chapter spec (shown to writer)
        cs_path = os.path.join(specs_dir, f"{prefix}_spec.md")
        with open(cs_path, "w", encoding="utf-8") as f:
            f.write(f"# Chapter {chapter_num} Brief\n\n{chapter_specs[i]}\n")

        manifest["artifacts"].append({
            "chapter": chapter_num,
            "source_canon": sc_path,
            "remixed_canon": rc_path,
            "chapter_spec": cs_path,
            "source_input": os.path.join(spike_dir, chapter_files[i]),
            "recent_summary": _build_recent_summary(remixed_canons[i], chapter_num),
        })

    # Write manifest
    manifest_path = "benchmark/spike_manifest.json"
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)

    print(f"\nSpike compilation complete. Manifest: {manifest_path}")
    print(f"  {len(source_canons)} source canons -> {source_dir}/")
    print(f"  {len(remixed_canons)} remixed canons -> {remix_dir}/")
    print(f"  {len(chapter_specs)} chapter specs -> {specs_dir}/")
    return manifest


def _parse_json(raw: str) -> dict:
    """Extract JSON from LLM output that may contain markdown fences."""
    # Try direct parse first
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        pass

    # Try extracting from markdown code block
    match = re.search(r"```(?:json)?\s*\n(.*?)```", raw, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(1))
        except json.JSONDecodeError:
            pass

    # Try finding first { to last }
    start = raw.find("{")
    end = raw.rfind("}")
    if start != -1 and end != -1 and end > start:
        try:
            return json.loads(raw[start:end + 1])
        except json.JSONDecodeError:
            pass

    print(f"WARNING: Could not parse JSON from LLM output. Raw:\n{raw[:500]}", file=sys.stderr)
    return {}


def _normalize_source_canon(canon: dict, chapter_num: int) -> dict:
    if not isinstance(canon, dict) or not canon:
        raise ValueError(f"Could not parse source canon for chapter {chapter_num}")

    canon.setdefault("chapter_number", chapter_num)
    canon.setdefault("characters", [])
    canon.setdefault("locations", [])
    canon.setdefault("events", [])
    canon.setdefault("themes", [])
    canon.setdefault("emotional_arc", "")
    canon.setdefault("magic_or_wonder", [])
    canon["chapter_objective"] = str(canon.get("chapter_objective", "")).strip()
    if not canon["chapter_objective"]:
        raise ValueError(f"Missing chapter_objective in source canon for chapter {chapter_num}")
    return canon


def _normalize_name_map(name_map: dict) -> dict:
    if not isinstance(name_map, dict) or not name_map:
        raise ValueError("Could not parse benchmark name map")

    characters = name_map.get("characters")
    locations = name_map.get("locations")
    if not isinstance(characters, dict):
        characters = {}
    if not isinstance(locations, dict):
        locations = {}

    return {
        "characters": characters,
        "locations": locations,
        "world_name": str(name_map.get("world_name", "")).strip() or "The Remixed Kingdoms",
    }


def _normalize_remixed_canon(remixed: dict, source_canon: dict) -> dict:
    if not isinstance(remixed, dict) or not remixed:
        raise ValueError(
            f"Could not parse remixed canon for chapter {source_canon.get('chapter_number', '?')}"
        )

    merged = dict(source_canon)
    merged.update(remixed)
    merged.setdefault("characters", source_canon.get("characters", []))
    merged.setdefault("locations", source_canon.get("locations", []))
    merged.setdefault("events", source_canon.get("events", []))
    merged.setdefault("themes", source_canon.get("themes", []))
    merged.setdefault("magic_or_wonder", source_canon.get("magic_or_wonder", []))
    merged["chapter_objective"] = str(merged.get("chapter_objective", "")).strip()
    if not merged["chapter_objective"]:
        raise ValueError(
            f"Missing chapter_objective in remixed canon for chapter {source_canon.get('chapter_number', '?')}"
        )
    return merged


def _build_series_summary(name_map: dict, remixed_canons: list[dict]) -> str:
    world_name = name_map.get("world_name", "the remixed world")
    first = remixed_canons[0] if remixed_canons else {}
    cast = ", ".join(
        character.get("name", "").strip()
        for character in first.get("characters", [])[:4]
        if character.get("name")
    )
    places = ", ".join(
        location.get("name", "").strip()
        for location in first.get("locations", [])[:3]
        if location.get("name")
    )
    objective = first.get("chapter_objective", "").strip()

    parts = [
        f"This is an ongoing fantasy novel set in {world_name}. Maintain continuity across chapters.",
    ]
    if cast:
        parts.append(f"Core cast so far: {cast}.")
    if places:
        parts.append(f"Key places so far: {places}.")
    if objective:
        parts.append(f"Opening movement: {objective}")
    return " ".join(parts)


def _build_recent_summary(remixed_canon: dict, chapter_num: int) -> str:
    objective = remixed_canon.get("chapter_objective", "").strip()
    emotion = remixed_canon.get("emotional_arc", "").strip()
    event_summaries = [
        event.get("summary", "").strip()
        for event in remixed_canon.get("events", [])[:3]
        if event.get("summary")
    ]

    parts = [f"Chapter {chapter_num}: {objective}" if objective else f"Chapter {chapter_num}."]
    if event_summaries:
        parts.append("Key developments: " + "; ".join(event_summaries) + ".")
    if emotion:
        parts.append(f"Emotional arc: {emotion}.")
    return " ".join(parts).strip()


def main():
    parser = argparse.ArgumentParser(description="Compile remix artifacts for benchmark spike.")
    parser.add_argument(
        "--spike-dir",
        default="benchmark/spike_inputs",
        help="Directory containing source chapter files",
    )
    parser.add_argument(
        "--chapters",
        type=int,
        default=5,
        help="Number of chapters to compile (default: 5)",
    )
    args = parser.parse_args()

    compile_spike(args.spike_dir, args.chapters)


if __name__ == "__main__":
    main()
