"""
Series Engine — Manages long-form series generation for the autoresearch loop.

This is NOT about producing stories. Stories are TEST CASES. The writing system
is the product. Series writing is a harder, more comprehensive evaluation that
teaches continuity, arc progression, and thread management — skills that
standalone chapters can never test.

The loop's goal: recursive self-improvement of the writing system for
science fantasy long series.

Usage (called by the autoresearch loop, not directly):
  from series_engine import SeriesEngine
  engine = SeriesEngine()
  scenario = engine.get_next_scenario()       # Returns evaluate.py-compatible scenario
  engine.accept_chapter(chapter_text, scores)  # After ratchet keep
  engine.reject_chapter()                      # After ratchet revert
"""

import datetime
import json
import os
import random
import re
import time

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

SERIES_DIR = "series"
SERIES_CONFIG_FILE = os.path.join(SERIES_DIR, "config.json")

LOCAL_MODEL = "qwen3.5"
LOCAL_BASE_URL = "http://localhost:11434"
MAX_RETRIES = 3

# Context budget (tokens, approximate)
SERIES_SUMMARY_BUDGET = 400      # ~400 words for series arc summary
BOOK_OUTLINE_BUDGET = 600        # ~600 words for current book outline
BIBLE_EXCERPT_BUDGET = 1200      # ~1200 words for relevant bible entries
RECENT_SUMMARIES_BUDGET = 800    # ~800 words for last 3 chapter summaries
PREV_CHAPTER_BUDGET = 4000       # ~4000 words for full previous chapter
# Total: ~7000 words of context + writing system + chapter brief ≈ 12-15K tokens

# How many chapter failures before we move on (with a note in the bible)
MAX_CHAPTER_ATTEMPTS = 5

# How many books before rotating to a new series concept
SERIES_ROTATION_BOOKS = 3


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_ollama_client():
    from openai import OpenAI
    return OpenAI(base_url=f"{LOCAL_BASE_URL}/v1", api_key="ollama")


def _qwen_generate(client, system_prompt, user_prompt, max_tokens=4096, temperature=0.7):
    """Call Qwen with retry logic and thinking-tag stripping."""
    for attempt in range(MAX_RETRIES):
        try:
            response = client.chat.completions.create(
                model=LOCAL_MODEL,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt + "\n\n/no_think"}
                ],
                max_tokens=max_tokens,
                temperature=temperature,
            )
            text = response.choices[0].message.content
            text = re.sub(r'<think>.*?</think>', '', text, flags=re.DOTALL).strip()
            return text
        except Exception as e:
            if attempt < MAX_RETRIES - 1:
                print(f"  [Qwen] Retry {attempt + 1}: {e}")
                time.sleep(3)
            else:
                raise


def _extract_json(text):
    """Extract JSON from LLM output, handling markdown code blocks and preamble."""
    text = re.sub(r'<think>.*?</think>', '', text, flags=re.DOTALL).strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1].rsplit("```", 1)[0].strip()
    if not text.startswith("{") and not text.startswith("["):
        # Find first JSON structure
        for start_char, end_char in [("{", "}"), ("[", "]")]:
            if start_char in text:
                start = text.index(start_char)
                end = text.rindex(end_char) + 1
                text = text[start:end]
                break
    return json.loads(text)


def _truncate_words(text, max_words):
    """Truncate text to max_words."""
    words = text.split()
    if len(words) <= max_words:
        return text
    return " ".join(words[:max_words]) + "\n\n[... truncated ...]"


# ---------------------------------------------------------------------------
# Series Engine
# ---------------------------------------------------------------------------

class SeriesEngine:
    """Manages series state: outlines, bible, summaries, chapter progression."""

    def __init__(self, series_dir=SERIES_DIR):
        self.series_dir = series_dir
        os.makedirs(series_dir, exist_ok=True)
        self.config = self._load_config()

    # --- Config ---

    def _load_config(self):
        if os.path.exists(SERIES_CONFIG_FILE):
            with open(SERIES_CONFIG_FILE) as f:
                return json.load(f)
        return {"active_series": None, "series_list": []}

    def _save_config(self):
        with open(SERIES_CONFIG_FILE, "w") as f:
            json.dump(self.config, f, indent=2)

    # --- Path helpers ---

    def _series_path(self, series_id=None):
        sid = series_id or self.config["active_series"]
        return os.path.join(self.series_dir, sid)

    def _book_path(self, book_num, series_id=None):
        return os.path.join(self._series_path(series_id), f"book_{book_num:02d}")

    def _bible_path(self, series_id=None):
        return os.path.join(self._series_path(series_id), "series_bible.json")

    def _outline_path(self, series_id=None):
        return os.path.join(self._series_path(series_id), "series_outline.json")

    def _book_outline_path(self, book_num, series_id=None):
        return os.path.join(self._book_path(book_num, series_id), "outline.json")

    def _progress_path(self, book_num, series_id=None):
        return os.path.join(self._book_path(book_num, series_id), "progress.json")

    def _summary_path(self, book_num, chapter_num, series_id=None):
        sdir = os.path.join(self._book_path(book_num, series_id), "summaries")
        os.makedirs(sdir, exist_ok=True)
        return os.path.join(sdir, f"ch_{chapter_num:02d}.json")

    def _chapter_path(self, book_num, chapter_num, series_id=None):
        cdir = os.path.join(self._book_path(book_num, series_id), "chapters")
        os.makedirs(cdir, exist_ok=True)
        return os.path.join(cdir, f"ch_{chapter_num:02d}.md")

    def _chapter_meta_path(self, book_num, chapter_num, series_id=None):
        cdir = os.path.join(self._book_path(book_num, series_id), "chapters")
        os.makedirs(cdir, exist_ok=True)
        return os.path.join(cdir, f"ch_{chapter_num:02d}_meta.json")

    def _attempts_dir(self, book_num, chapter_num, series_id=None):
        adir = os.path.join(self._book_path(book_num, series_id), "attempts", f"ch_{chapter_num:02d}")
        os.makedirs(adir, exist_ok=True)
        return adir

    # --- Load helpers ---

    def _load_json(self, path, default=None):
        if os.path.exists(path):
            with open(path) as f:
                return json.load(f)
        return default if default is not None else {}

    def _save_json(self, path, data):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            json.dump(data, f, indent=2)

    def _ensure_bible_shape(self, bible):
        bible.setdefault("characters", {})
        bible.setdefault("world_facts", [])
        bible.setdefault("magic_tech_rules", [])
        bible.setdefault("locations", {})
        bible.setdefault("foreshadowing", [])
        bible.setdefault("active_threads", [])
        bible.setdefault("resolved_threads", [])
        bible.setdefault("timeline", [])
        bible.setdefault("relationships", [])
        bible.setdefault("killed_characters", [])
        bible.setdefault("forced_advances", [])
        bible.setdefault("skipped_chapters", [])
        return bible

    # --- Series initialization ---

    def initialize_series(self, force=False):
        """Generate a new science fantasy series outline using Qwen.
        Returns the series_id."""
        client = _get_ollama_client()

        print("[Series] Generating new science fantasy series concept...")

        # Step 1: Generate series concept
        concept = _qwen_generate(client,
            system_prompt="""You are a master science fantasy author and story architect.
You design sprawling multi-book series that blend science fiction and fantasy:
technology and magic coexist, ancient cosmic forces meet advanced civilizations,
the wonder of fantasy merges with the rigor of sci-fi worldbuilding.

Think: Dune, Book of the New Sun, Broken Earth, Hyperion, Warhammer 40K,
Final Fantasy, Star Wars but darker, Numenera, Horizon Zero Dawn.""",

            user_prompt="""Design a 10-book SCIENCE FANTASY series. This must be epic in scope
with deep characters, layered mysteries, and a world that blends technology and magic.

Requirements:
- A central mystery/conflict that spans all 10 books but escalates meaningfully
- 4-6 POV characters with distinct wounds, voices, and arcs across the series
- A world where technology and magic are intertwined (not separate systems)
- Political/social structures that create conflict
- An antagonistic force that is MORE than simple evil
- Escalating stakes: personal → political → civilizational → cosmic
- Each book should have its own complete arc while advancing the series

Output ONLY valid JSON:
{
  "series_id": "<kebab-case-id, 2-4 words>",
  "series_title": "<the series name>",
  "genre": "science fantasy",
  "premise": "<2-3 sentences: the hook, the world, the central question>",
  "central_mystery": "<what drives the overarching plot across 10 books>",
  "world": {
    "name": "<world/setting name>",
    "tech_magic_fusion": "<how technology and magic blend in this world>",
    "political_structure": "<who holds power and how>",
    "key_locations": ["<location 1>", "<location 2>", "<location 3>", "<location 4>"],
    "history_seed": "<one paragraph of deep history that matters to the plot>"
  },
  "characters": [
    {
      "name": "<name>",
      "role": "<their role in the story>",
      "wound": "<the foundational lie/wound that drives them>",
      "arc_across_series": "<how they transform over 10 books>",
      "voice": "<what makes their POV chapters distinct in prose style>"
    }
  ],
  "antagonist": {
    "nature": "<what the antagonistic force IS>",
    "motivation": "<why it does what it does — not simple evil>",
    "escalation": "<how the threat grows across the series>"
  },
  "book_arcs": [
    {"book": 1, "title": "<title>", "arc_summary": "<2-3 sentences: this book's complete arc>", "pov_characters": ["<name>"], "stakes": "<what's at risk>"},
    {"book": 2, "title": "<title>", "arc_summary": "<2-3 sentences>", "pov_characters": ["<name>"], "stakes": "<what's at risk>"},
    {"book": 3, "title": "<title>", "arc_summary": "<2-3 sentences>", "pov_characters": ["<name>"], "stakes": "<what's at risk>"},
    {"book": 4, "title": "<title>", "arc_summary": "<2-3 sentences>", "pov_characters": ["<name>"], "stakes": "<what's at risk>"},
    {"book": 5, "title": "<title>", "arc_summary": "<2-3 sentences>", "pov_characters": ["<name>"], "stakes": "<what's at risk>"},
    {"book": 6, "title": "<title>", "arc_summary": "<2-3 sentences>", "pov_characters": ["<name>"], "stakes": "<what's at risk>"},
    {"book": 7, "title": "<title>", "arc_summary": "<2-3 sentences>", "pov_characters": ["<name>"], "stakes": "<what's at risk>"},
    {"book": 8, "title": "<title>", "arc_summary": "<2-3 sentences>", "pov_characters": ["<name>"], "stakes": "<what's at risk>"},
    {"book": 9, "title": "<title>", "arc_summary": "<2-3 sentences>", "pov_characters": ["<name>"], "stakes": "<what's at risk>"},
    {"book": 10, "title": "<title>", "arc_summary": "<2-3 sentences>", "pov_characters": ["<name>"], "stakes": "<what's at risk>"}
  ],
  "themes": ["<theme 1>", "<theme 2>", "<theme 3>"]
}""",
            max_tokens=8192,
            temperature=0.9,
        )

        outline = _extract_json(concept)
        series_id = outline["series_id"]

        # Save series outline
        series_path = os.path.join(self.series_dir, series_id)
        os.makedirs(series_path, exist_ok=True)
        self._save_json(self._outline_path(series_id), outline)

        # Initialize bible
        bible = {
            "characters": {},
            "world_facts": [],
            "magic_tech_rules": [],
            "locations": {},
            "foreshadowing": [],  # {planted_book, planted_chapter, description, resolved: bool}
            "active_threads": [],
            "resolved_threads": [],
            "timeline": [],
            "relationships": [],
            "killed_characters": [],
            "forced_advances": [],
            "skipped_chapters": [],
            "last_updated": datetime.datetime.now().isoformat(),
        }
        # Seed characters from outline
        for char in outline.get("characters", []):
            bible["characters"][char["name"]] = {
                "role": char["role"],
                "wound": char["wound"],
                "arc": char["arc_across_series"],
                "voice": char["voice"],
                "status": "alive",
                "current_state": "as introduced",
                "known_facts": [],
                "relationships": [],
            }
        # Seed world facts
        world = outline.get("world", {})
        bible["world_facts"].append(f"Setting: {world.get('name', 'unknown')}")
        bible["world_facts"].append(f"Tech-magic fusion: {world.get('tech_magic_fusion', '')}")
        bible["world_facts"].append(f"Political structure: {world.get('political_structure', '')}")
        bible["world_facts"].append(f"History: {world.get('history_seed', '')}")
        for loc in world.get("key_locations", []):
            bible["world_facts"].append(f"Key location: {loc}")
            bible["locations"][loc] = {
                "status": "introduced",
                "facts": [],
                "last_seen": None,
            }

        self._save_json(self._bible_path(series_id), bible)

        # Update config
        self.config["active_series"] = series_id
        if series_id not in self.config.get("series_list", []):
            self.config.setdefault("series_list", []).append(series_id)
        self._save_config()

        print(f"[Series] Created: '{outline.get('series_title', series_id)}' ({series_id})")
        print(f"[Series] {len(outline.get('characters', []))} characters, 10 books planned")

        # Generate Book 1 chapter outline
        self.generate_book_outline(1, series_id)

        return series_id

    def generate_book_outline(self, book_num, series_id=None):
        """Generate chapter-by-chapter outline for a specific book."""
        sid = series_id or self.config["active_series"]
        client = _get_ollama_client()
        outline = self._load_json(self._outline_path(sid))
        bible = self._load_json(self._bible_path(sid))

        book_arc = None
        for ba in outline.get("book_arcs", []):
            if ba["book"] == book_num:
                book_arc = ba
                break

        if not book_arc:
            print(f"[Series] No arc found for book {book_num}")
            return None

        # Get series context for the outline generator
        series_summary = f"""Series: {outline.get('series_title', '')}
Premise: {outline.get('premise', '')}
Central mystery: {outline.get('central_mystery', '')}
Genre: science fantasy"""

        # Include previous book summaries if they exist
        prev_book_summaries = ""
        for prev_b in range(1, book_num):
            prev_progress = self._load_json(self._progress_path(prev_b, sid))
            if prev_progress.get("book_summary"):
                prev_book_summaries += f"\nBook {prev_b}: {prev_progress['book_summary']}"

        characters_brief = ""
        for name, info in bible.get("characters", {}).items():
            characters_brief += f"\n- {name}: {info.get('role', '')}. Wound: {info.get('wound', '')}. Voice: {info.get('voice', '')}. Status: {info.get('current_state', 'as introduced')}"

        print(f"[Series] Generating Book {book_num} chapter outline...")

        book_outline_text = _qwen_generate(client,
            system_prompt="You are a master story architect designing chapter outlines for a science fantasy novel. Each chapter must advance both its own arc and the book's arc. Output ONLY valid JSON.",
            user_prompt=f"""{series_summary}

CHARACTERS:{characters_brief}

{f"PREVIOUS BOOKS:{prev_book_summaries}" if prev_book_summaries else "This is Book 1."}

THIS BOOK:
Title: {book_arc.get('title', '')}
Arc: {book_arc.get('arc_summary', '')}
POV characters: {', '.join(book_arc.get('pov_characters', []))}
Stakes: {book_arc.get('stakes', '')}

Design a 25-chapter outline. Each chapter needs:
- A POV character (rotate POVs meaningfully)
- A clear dramatic purpose (what changes by the end of this chapter)
- Required beats that create a complete chapter arc
- Connection to the book's overall arc

Pace it: Chapters 1-5 setup, 6-12 rising action, 13 midpoint turn, 14-20 escalation, 21-24 climax, 25 resolution/hook.

Output JSON:
{{
  "book_num": {book_num},
  "title": "{book_arc.get('title', '')}",
  "chapters": [
    {{
      "chapter_num": 1,
      "pov_character": "<name>",
      "chapter_position": "<where this falls in the book's arc>",
      "story_context": "<what the reader knows at this point>",
      "chapter_brief": "<full paragraph: what happens, what changes, what's at stake>",
      "pov_character_detail": "<name, age, how they think, what makes their voice distinct in THIS chapter>",
      "required_beats": ["<beat 1>", "<beat 2>", "<beat 3>", "<beat 4>", "<beat 5>", "<beat 6>"],
      "genre_tags": ["science fantasy", "<subgenre>", "<mood>"]
    }}
  ]
}}""",
            max_tokens=16384,
            temperature=0.8,
        )

        book_outline = _extract_json(book_outline_text)

        # Save
        book_path = self._book_path(book_num, sid)
        os.makedirs(book_path, exist_ok=True)
        self._save_json(self._book_outline_path(book_num, sid), book_outline)

        # Initialize progress
        progress = {
            "current_chapter": 1,
            "total_chapters": len(book_outline.get("chapters", [])),
            "chapters_completed": 0,
            "chapter_attempts": {},  # {chapter_num: attempt_count}
            "book_summary": None,
            "started": datetime.datetime.now().isoformat(),
            "completed": None,
        }
        self._save_json(self._progress_path(book_num, sid), progress)

        n_chapters = len(book_outline.get("chapters", []))
        print(f"[Series] Book {book_num} outline: {n_chapters} chapters")
        return book_outline

    # --- Context building ---

    def build_series_summary(self):
        """Build a compressed series summary for the writer's context."""
        outline = self._load_json(self._outline_path())
        if not outline:
            return ""

        parts = [
            f"SERIES: {outline.get('series_title', '')}",
            f"GENRE: Science Fantasy",
            f"PREMISE: {outline.get('premise', '')}",
            f"CENTRAL MYSTERY: {outline.get('central_mystery', '')}",
        ]

        # Add completed book summaries
        for ba in outline.get("book_arcs", []):
            book_num = ba["book"]
            progress = self._load_json(self._progress_path(book_num))
            if progress.get("book_summary"):
                parts.append(f"BOOK {book_num} ({ba.get('title', '')}): {progress['book_summary']}")

        return "\n".join(parts)

    def build_bible_excerpt(self, chapter_info):
        """Extract relevant bible entries for the current chapter."""
        bible = self._load_json(self._bible_path())
        if not bible:
            return ""

        parts = []

        # Always include the POV character's full entry
        pov_name = chapter_info.get("pov_character", "")
        if pov_name and pov_name in bible.get("characters", {}):
            char = bible["characters"][pov_name]
            parts.append(f"POV CHARACTER — {pov_name}:")
            parts.append(f"  Role: {char.get('role', '')}")
            parts.append(f"  Wound: {char.get('wound', '')}")
            parts.append(f"  Current state: {char.get('current_state', 'as introduced')}")
            if char.get("known_facts"):
                parts.append(f"  Key facts: {'; '.join(char['known_facts'][-5:])}")
            if char.get("relationships"):
                parts.append(f"  Relationships: {'; '.join(char['relationships'][-5:])}")

        # Include other characters mentioned in the chapter brief
        brief = chapter_info.get("chapter_brief", "")
        for name, char in bible.get("characters", {}).items():
            if name != pov_name and name.lower() in brief.lower():
                parts.append(f"\n{name}: {char.get('role', '')}. Status: {char.get('current_state', 'as introduced')}")

        # Active foreshadowing that hasn't been resolved
        active_foreshadowing = [f for f in bible.get("foreshadowing", []) if not f.get("resolved")]
        if active_foreshadowing:
            parts.append("\nACTIVE FORESHADOWING:")
            for fs in active_foreshadowing[-5:]:
                parts.append(f"  - (Book {fs.get('planted_book')}, Ch {fs.get('planted_chapter')}): {fs.get('description', '')}")

        # Recent world facts (last 10)
        world_facts = bible.get("world_facts", [])
        if world_facts:
            parts.append("\nESTABLISHED WORLD FACTS:")
            for fact in world_facts[-10:]:
                parts.append(f"  - {fact}")

        # Magic/tech rules
        rules = bible.get("magic_tech_rules", [])
        if rules:
            parts.append("\nMAGIC/TECH RULES:")
            for rule in rules:
                parts.append(f"  - {rule}")

        return "\n".join(parts)

    def build_recent_summaries(self, book_num, current_chapter):
        """Get summaries of the last 3 chapters."""
        parts = []
        for ch in range(max(1, current_chapter - 3), current_chapter):
            summary_data = self._load_json(self._summary_path(book_num, ch))
            if summary_data:
                parts.append(f"CHAPTER {ch} SUMMARY:")
                parts.append(summary_data.get("summary", ""))
                if summary_data.get("emotional_state"):
                    parts.append(f"  Emotional state at end: {summary_data['emotional_state']}")
                parts.append("")
        return "\n".join(parts)

    def get_previous_chapter_text(self, book_num, current_chapter):
        """Get the full text of the previous chapter for voice continuity."""
        if current_chapter <= 1:
            return ""
        prev_path = self._chapter_path(book_num, current_chapter - 1)
        if os.path.exists(prev_path):
            with open(prev_path) as f:
                text = f.read()
            return _truncate_words(text, PREV_CHAPTER_BUDGET)
        return ""

    # --- Main interface: get scenario for evaluate.py ---

    def get_next_scenario(self):
        """Get the next chapter as an evaluate.py-compatible scenario dict.
        This is the main interface between the series engine and the evaluation loop."""

        sid = self.config.get("active_series")
        if not sid:
            # No series exists — generate one
            sid = self.initialize_series()

        # Find current position
        outline = self._load_json(self._outline_path())
        current_book = self._find_current_book()
        book_outline = self._load_json(self._book_outline_path(current_book))

        if not book_outline:
            # Need to generate this book's outline
            book_outline = self.generate_book_outline(current_book)

        progress = self._load_json(self._progress_path(current_book))
        current_chapter = progress.get("current_chapter", 1)
        total_chapters = progress.get("total_chapters", 25)

        # Check if book is done
        if current_chapter > total_chapters:
            self._complete_book(current_book)
            current_book += 1
            # Check if series is done or should rotate
            if current_book > 10 or current_book > SERIES_ROTATION_BOOKS:
                self._rotate_series()
                return self.get_next_scenario()  # Recurse with new series
            book_outline = self.generate_book_outline(current_book)
            progress = self._load_json(self._progress_path(current_book))
            current_chapter = 1

        # Get chapter info from outline
        chapter_info = None
        for ch in book_outline.get("chapters", []):
            if ch.get("chapter_num") == current_chapter:
                chapter_info = ch
                break

        if not chapter_info:
            print(f"[Series] No chapter info for Book {current_book}, Chapter {current_chapter}")
            # Generate a fallback
            chapter_info = {
                "chapter_num": current_chapter,
                "pov_character": outline.get("characters", [{}])[0].get("name", "Unknown"),
                "chapter_position": f"Chapter {current_chapter} of Book {current_book}",
                "story_context": "Continuing the narrative.",
                "chapter_brief": "Continue the story from where the previous chapter left off.",
                "required_beats": ["Opening hook", "Rising tension", "Key revelation", "Character moment", "Climactic beat", "Chapter-ending hook"],
                "genre_tags": ["science fantasy"],
            }

        # Build context layers
        series_summary = self.build_series_summary()
        bible_excerpt = self.build_bible_excerpt(chapter_info)
        recent_summaries = self.build_recent_summaries(current_book, current_chapter)
        prev_chapter = self.get_previous_chapter_text(current_book, current_chapter)

        # Track attempts
        attempt_key = str(current_chapter)
        attempts = progress.get("chapter_attempts", {}).get(attempt_key, 0)

        # Build evaluate.py-compatible scenario
        scenario = {
            "id": f"b{current_book:02d}_ch{current_chapter:02d}",
            "chapter_position": chapter_info.get("chapter_position",
                f"Chapter {current_chapter} of Book {current_book}: {book_outline.get('title', '')}"),
            "story_context": chapter_info.get("story_context", ""),
            "chapter_brief": chapter_info.get("chapter_brief", ""),
            "pov_character": chapter_info.get("pov_character_detail",
                chapter_info.get("pov_character", "")),
            "required_beats": chapter_info.get("required_beats", []),
            "genre_tags": chapter_info.get("genre_tags", ["science fantasy"]),

            # Series-specific context (used by generate_chapter if present)
            "_series_context": {
                "series_summary": series_summary,
                "bible_excerpt": bible_excerpt,
                "recent_summaries": recent_summaries,
                "previous_chapter": prev_chapter,
                "book_num": current_book,
                "chapter_num": current_chapter,
                "total_chapters": total_chapters,
                "attempt": attempts + 1,
                "series_id": sid,
            }
        }

        # Increment attempt counter
        progress.setdefault("chapter_attempts", {})[attempt_key] = attempts + 1
        self._save_json(self._progress_path(current_book), progress)

        return scenario

    def _find_current_book(self):
        """Find which book we're currently writing."""
        for book_num in range(1, 11):
            progress = self._load_json(self._progress_path(book_num))
            if not progress:
                return book_num
            if not progress.get("completed"):
                return book_num
        return 1  # Fallback

    # --- After evaluation: store, accept, or reject ---

    def store_attempt(self, chapter_text, scores, scenario):
        """Store every chapter attempt (pass or fail) so we can pick the best on forced advance.
        Called after every Pass 1 evaluation in series mode, BEFORE the keep/discard decision."""
        ctx = scenario.get("_series_context", {})
        book_num = ctx.get("book_num", 1)
        chapter_num = ctx.get("chapter_num", 1)
        attempt = ctx.get("attempt", 1)
        sid = ctx.get("series_id", self.config.get("active_series"))

        attempts_dir = self._attempts_dir(book_num, chapter_num, sid)

        # Save the chapter text
        text_path = os.path.join(attempts_dir, f"attempt_{attempt:02d}.md")
        with open(text_path, "w") as f:
            f.write(chapter_text)

        # Save the scores and metadata
        from evaluate import compute_composite
        composite = compute_composite(scores) if scores else 0

        meta_path = os.path.join(attempts_dir, f"attempt_{attempt:02d}_meta.json")
        meta = {
            "attempt": attempt,
            "composite": composite,
            "scores": scores,
            "timestamp": datetime.datetime.now().isoformat(),
            "word_count": len(chapter_text.split()),
        }
        self._save_json(meta_path, meta)

        print(f"[Series] Stored attempt {attempt} for Book {book_num}, Ch {chapter_num} (composite={composite:.1f})")

    def _load_best_attempt(self, book_num, chapter_num, series_id=None):
        """Load the best attempt (by composite score) for a chapter. Returns (text, meta, scenario_stub) or (None, None, None)."""
        sid = series_id or self.config.get("active_series")
        attempts_dir = self._attempts_dir(book_num, chapter_num, sid)

        best_meta = None
        best_text = None

        # Find all attempt meta files
        if not os.path.exists(attempts_dir):
            return None, None

        meta_files = [f for f in os.listdir(attempts_dir) if f.endswith("_meta.json")]
        for mf in meta_files:
            meta = self._load_json(os.path.join(attempts_dir, mf))
            if best_meta is None or meta.get("composite", 0) > best_meta.get("composite", 0):
                best_meta = meta
                # Load corresponding text
                attempt_num = meta.get("attempt", 0)
                text_path = os.path.join(attempts_dir, f"attempt_{attempt_num:02d}.md")
                if os.path.exists(text_path):
                    with open(text_path) as f:
                        best_text = f.read()

        return best_text, best_meta

    def accept_chapter(self, chapter_text, scores, scenario):
        """Called after ratchet KEEP. Saves chapter, generates summary, updates bible."""
        ctx = scenario.get("_series_context", {})
        book_num = ctx.get("book_num", 1)
        chapter_num = ctx.get("chapter_num", 1)
        sid = ctx.get("series_id", self.config.get("active_series"))

        # Save the chapter text as the canonical version
        chapter_path = self._chapter_path(book_num, chapter_num, sid)
        with open(chapter_path, "w") as f:
            f.write(chapter_text)

        # Save chapter metadata
        from evaluate import compute_composite
        meta = {
            "scores": scores,
            "composite": compute_composite(scores) if scores else 0,
            "attempt": ctx.get("attempt", 1),
            "timestamp": datetime.datetime.now().isoformat(),
            "word_count": len(chapter_text.split()),
            "forced_advance": False,
        }
        self._save_json(self._chapter_meta_path(book_num, chapter_num, sid), meta)

        # Generate chapter summary
        print(f"[Series] Summarizing Book {book_num}, Chapter {chapter_num}...")
        summary = self._summarize_chapter(chapter_text, scenario)
        state_delta = self._extract_state_delta(chapter_text, scenario, summary)
        summary["state_delta"] = state_delta
        self._save_json(self._summary_path(book_num, chapter_num, sid), summary)

        # Update bible
        print(f"[Series] Updating bible...")
        self._update_bible(chapter_text, scenario, summary, state_delta)

        # Advance to next chapter
        progress = self._load_json(self._progress_path(book_num, sid))
        progress["current_chapter"] = chapter_num + 1
        progress["chapters_completed"] = chapter_num
        progress["chapter_attempts"].pop(str(chapter_num), None)
        self._save_json(self._progress_path(book_num, sid), progress)

        print(f"[Series] Chapter {chapter_num} accepted. Next: Chapter {chapter_num + 1}")

    def reject_chapter(self, scenario):
        """Called after ratchet REVERT. If max attempts reached, force advance with the BEST attempt."""
        ctx = scenario.get("_series_context", {})
        book_num = ctx.get("book_num", 1)
        chapter_num = ctx.get("chapter_num", 1)
        attempt = ctx.get("attempt", 1)
        sid = ctx.get("series_id", self.config.get("active_series"))

        if attempt >= MAX_CHAPTER_ATTEMPTS:
            print(f"[Series] Chapter {chapter_num} failed {MAX_CHAPTER_ATTEMPTS} times. Forcing advance with best attempt...")

            # Find the best attempt we stored
            best_text, best_meta = self._load_best_attempt(book_num, chapter_num, sid)

            if best_text and best_meta:
                best_attempt_num = best_meta.get("attempt", "?")
                best_composite = best_meta.get("composite", 0)
                print(f"[Series] Best attempt was #{best_attempt_num} (composite={best_composite:.1f})")

                # Save the best attempt as the canonical chapter
                chapter_path = self._chapter_path(book_num, chapter_num, sid)
                with open(chapter_path, "w") as f:
                    f.write(best_text)

                # Save metadata marking this as a forced advance
                meta = {
                    "scores": best_meta.get("scores", {}),
                    "composite": best_composite,
                    "attempt": best_attempt_num,
                    "timestamp": datetime.datetime.now().isoformat(),
                    "word_count": len(best_text.split()),
                    "forced_advance": True,
                    "total_attempts": attempt,
                }
                self._save_json(self._chapter_meta_path(book_num, chapter_num, sid), meta)

                # Generate summary and update bible from the best attempt
                # (even imperfect chapters advance the story and establish facts)
                print(f"[Series] Summarizing forced-advance chapter...")
                summary = self._summarize_chapter(best_text, scenario)
                state_delta = self._extract_state_delta(best_text, scenario, summary)
                summary["state_delta"] = state_delta
                self._save_json(self._summary_path(book_num, chapter_num, sid), summary)

                print(f"[Series] Updating bible with forced-advance facts...")
                self._update_bible(best_text, scenario, summary, state_delta)

                # Note in bible that this was a forced advance
                bible = self._load_json(self._bible_path(sid))
                bible.setdefault("forced_advances", []).append({
                    "book": book_num, "chapter": chapter_num,
                    "best_attempt": best_attempt_num,
                    "composite": best_composite,
                    "total_attempts": attempt,
                    "timestamp": datetime.datetime.now().isoformat(),
                })
                self._save_json(self._bible_path(sid), bible)
            else:
                # No stored attempts at all (shouldn't happen, but handle gracefully)
                print(f"[Series] WARNING: No stored attempts found. Skipping chapter entirely.")
                bible = self._load_json(self._bible_path(sid))
                bible.setdefault("skipped_chapters", []).append({
                    "book": book_num, "chapter": chapter_num,
                    "reason": f"No stored attempts after {attempt} tries",
                    "timestamp": datetime.datetime.now().isoformat(),
                })
                self._save_json(self._bible_path(sid), bible)

            # Advance to next chapter
            progress = self._load_json(self._progress_path(book_num, sid))
            progress["current_chapter"] = chapter_num + 1
            progress["chapters_completed"] = chapter_num
            progress["chapter_attempts"].pop(str(chapter_num), None)
            self._save_json(self._progress_path(book_num, sid), progress)

    # --- Summarization ---

    def _summarize_chapter(self, chapter_text, scenario):
        """Use Qwen to generate a chapter summary for context compression."""
        client = _get_ollama_client()
        ctx = scenario.get("_series_context", {})

        prompt = f"""Summarize this chapter for use as context in writing future chapters.
The summary must capture:
1. KEY EVENTS: What happened (plot-advancing actions only)
2. CHARACTER DEVELOPMENT: How did the POV character change? What did they learn/feel/decide?
3. NEW INFORMATION: What facts were revealed about the world, other characters, or the mystery?
4. EMOTIONAL STATE: Where is the POV character emotionally at chapter's end?
5. THREADS: What plot threads were advanced, planted, or resolved?
6. FORESHADOWING: Any hints or setups that need payoff later?

POV Character: {scenario.get('pov_character', 'unknown')}
Chapter Position: {scenario.get('chapter_position', '')}

<chapter>
{_truncate_words(chapter_text, 5000)}
</chapter>

Output ONLY valid JSON:
{{
  "summary": "<200-300 word summary of key events and developments>",
  "character_changes": "<how the POV character changed this chapter>",
  "emotional_state": "<the POV character's emotional state at chapter end>",
  "new_facts": ["<fact 1>", "<fact 2>"],
  "threads_advanced": ["<thread>"],
  "threads_planted": ["<new thread or foreshadowing>"],
  "threads_resolved": ["<resolved thread>"]
}}"""

        try:
            raw = _qwen_generate(client, "You are a precise story analyst. Output ONLY valid JSON.", prompt)
            return _extract_json(raw)
        except Exception as e:
            print(f"[Series] Summary generation failed: {e}")
            # Fallback: basic summary
            return {
                "summary": f"Chapter {ctx.get('chapter_num', '?')} of Book {ctx.get('book_num', '?')}. [Auto-summary failed]",
                "character_changes": "",
                "emotional_state": "unknown",
                "new_facts": [],
                "threads_advanced": [],
                "threads_planted": [],
                "threads_resolved": [],
            }

    def _extract_state_delta(self, chapter_text, scenario, summary):
        """Extract structured canon updates from an accepted chapter."""
        client = _get_ollama_client()
        prompt = f"""Extract the CANON STATE DELTA introduced by this accepted chapter.

Focus only on durable story state, not prose commentary.

POV Character: {scenario.get('pov_character', 'unknown')}
Chapter Position: {scenario.get('chapter_position', '')}

SUMMARY JSON:
{json.dumps(summary, indent=2)}

CHAPTER EXCERPT:
<chapter>
{_truncate_words(chapter_text, 3500)}
</chapter>

Output ONLY valid JSON:
{{
  "world_facts": ["<new durable fact>"],
  "magic_tech_rules": ["<new rule or constraint>"],
  "timeline_events": ["<event that happened>"],
  "locations": [
    {{
      "name": "<location>",
      "status": "<new status or empty>",
      "facts": ["<fact>"]
    }}
  ],
  "character_updates": [
    {{
      "name": "<character>",
      "status": "alive|dead|missing|changed",
      "current_state": "<1-2 sentence update>",
      "emotional_state": "<current emotional register>",
      "new_facts": ["<fact>"]
    }}
  ],
  "relationships": [
    {{
      "between": ["<name 1>", "<name 2>"],
      "status": "<ally|enemy|strained|romantic|unknown>",
      "notes": "<what changed>"
    }}
  ],
  "threads_opened": ["<new active thread>"],
  "threads_advanced": ["<thread advanced>"],
  "threads_resolved": ["<thread resolved>"]
}}"""

        try:
            raw = _qwen_generate(client, "You are a precise continuity archivist. Output ONLY valid JSON.", prompt)
            delta = _extract_json(raw)
        except Exception as e:
            print(f"[Series] State delta extraction failed: {e}")
            delta = {
                "world_facts": summary.get("new_facts", []),
                "magic_tech_rules": [],
                "timeline_events": [summary.get("summary", "")[:240]] if summary.get("summary") else [],
                "locations": [],
                "character_updates": [],
                "relationships": [],
                "threads_opened": summary.get("threads_planted", []),
                "threads_advanced": summary.get("threads_advanced", []),
                "threads_resolved": summary.get("threads_resolved", []),
            }

        delta.setdefault("world_facts", [])
        delta.setdefault("magic_tech_rules", [])
        delta.setdefault("timeline_events", [])
        delta.setdefault("locations", [])
        delta.setdefault("character_updates", [])
        delta.setdefault("relationships", [])
        delta.setdefault("threads_opened", [])
        delta.setdefault("threads_advanced", [])
        delta.setdefault("threads_resolved", [])
        return delta

    def _append_unique(self, items, value):
        if value and value not in items:
            items.append(value)

    def _update_bible(self, chapter_text, scenario, summary, state_delta=None):
        """Update the series bible with new facts from an accepted chapter."""
        bible = self._ensure_bible_shape(self._load_json(self._bible_path()))
        ctx = scenario.get("_series_context", {})
        book_num = ctx.get("book_num", 1)
        chapter_num = ctx.get("chapter_num", 1)
        state_delta = state_delta or summary.get("state_delta", {})

        # Add new facts
        for fact in summary.get("new_facts", []):
            self._append_unique(bible["world_facts"], fact)
        for fact in state_delta.get("world_facts", []):
            self._append_unique(bible["world_facts"], fact)
        for rule in state_delta.get("magic_tech_rules", []):
            self._append_unique(bible["magic_tech_rules"], rule)

        # Update character state
        pov_name = scenario.get("pov_character", "").split(",")[0].strip()
        if pov_name and pov_name in bible.get("characters", {}):
            char = bible["characters"][pov_name]
            if summary.get("character_changes"):
                char["current_state"] = summary["character_changes"]
            if summary.get("emotional_state"):
                char["last_emotional_state"] = summary["emotional_state"]
        for update in state_delta.get("character_updates", []):
            name = update.get("name")
            if not name:
                continue
            char = bible["characters"].setdefault(name, {
                "role": "",
                "wound": "",
                "arc": "",
                "voice": "",
                "status": "alive",
                "current_state": "",
                "known_facts": [],
                "relationships": [],
            })
            if update.get("status"):
                char["status"] = update["status"]
            if update.get("current_state"):
                char["current_state"] = update["current_state"]
            if update.get("emotional_state"):
                char["last_emotional_state"] = update["emotional_state"]
            for fact in update.get("new_facts", []):
                self._append_unique(char.setdefault("known_facts", []), fact)
            if update.get("status") == "dead":
                self._append_unique(bible["killed_characters"], name)

        for location in state_delta.get("locations", []):
            name = location.get("name")
            if not name:
                continue
            entry = bible["locations"].setdefault(name, {
                "status": "introduced",
                "facts": [],
                "last_seen": None,
            })
            if location.get("status"):
                entry["status"] = location["status"]
            for fact in location.get("facts", []):
                self._append_unique(entry["facts"], fact)
            entry["last_seen"] = {"book": book_num, "chapter": chapter_num}

        for rel in state_delta.get("relationships", []):
            between = rel.get("between", [])
            if len(between) < 2:
                continue
            record = {
                "between": between[:2],
                "status": rel.get("status", ""),
                "notes": rel.get("notes", ""),
                "book": book_num,
                "chapter": chapter_num,
            }
            if record not in bible["relationships"]:
                bible["relationships"].append(record)

        # Track foreshadowing
        opened_threads = list(summary.get("threads_planted", [])) + list(state_delta.get("threads_opened", []))
        for thread in opened_threads:
            if thread:
                self._append_unique(bible["active_threads"], thread)
                bible.setdefault("foreshadowing", []).append({
                    "planted_book": book_num,
                    "planted_chapter": chapter_num,
                    "description": thread,
                    "resolved": False,
                })

        # Mark resolved threads
        resolved_threads = list(summary.get("threads_resolved", [])) + list(state_delta.get("threads_resolved", []))
        for thread in resolved_threads:
            if thread:
                if thread in bible["active_threads"]:
                    bible["active_threads"].remove(thread)
                self._append_unique(bible["resolved_threads"], thread)
                for fs in bible.get("foreshadowing", []):
                    if not fs.get("resolved") and thread.lower() in fs.get("description", "").lower():
                        fs["resolved"] = True
                        fs["resolved_book"] = book_num
                        fs["resolved_chapter"] = chapter_num

        for thread in state_delta.get("threads_advanced", []):
            self._append_unique(bible["active_threads"], thread)

        # Add timeline entry
        bible.setdefault("timeline", []).append({
            "book": book_num,
            "chapter": chapter_num,
            "summary": summary.get("summary", "")[:200],
            "events": state_delta.get("timeline_events", [])[:5],
        })

        bible["last_updated"] = datetime.datetime.now().isoformat()
        self._save_json(self._bible_path(), bible)

    # --- Book/series completion ---

    def _complete_book(self, book_num):
        """Generate book summary and mark as complete."""
        client = _get_ollama_client()
        progress = self._load_json(self._progress_path(book_num))

        # Gather all chapter summaries
        all_summaries = []
        for ch in range(1, progress.get("total_chapters", 25) + 1):
            s = self._load_json(self._summary_path(book_num, ch))
            if s:
                all_summaries.append(f"Ch {ch}: {s.get('summary', '')}")

        if all_summaries:
            prompt = f"""Summarize this entire book in 500-800 words for series continuity.
Capture: main plot arc, character transformations, key revelations, unresolved threads.

CHAPTER SUMMARIES:
{chr(10).join(all_summaries)}

Output ONLY the summary text (no JSON, no formatting)."""

            try:
                book_summary = _qwen_generate(client, "You are a precise story analyst.", prompt, max_tokens=2048)
            except Exception:
                book_summary = f"Book {book_num} completed. [Auto-summary failed]"
        else:
            book_summary = f"Book {book_num} completed."

        progress["book_summary"] = book_summary
        progress["completed"] = datetime.datetime.now().isoformat()
        self._save_json(self._progress_path(book_num), progress)
        print(f"[Series] Book {book_num} COMPLETE. Summary generated.")

    def _rotate_series(self):
        """Start a new series to broaden the writing system's skills."""
        old_series = self.config.get("active_series")
        print(f"[Series] Rotating from '{old_series}' to new series concept...")
        self.config["active_series"] = None
        self._save_config()
        # initialize_series will be called by get_next_scenario

    # --- Status ---

    def get_status(self):
        """Return current series status for display."""
        sid = self.config.get("active_series")
        if not sid:
            return {"status": "no active series"}

        outline = self._load_json(self._outline_path())
        current_book = self._find_current_book()
        progress = self._load_json(self._progress_path(current_book))
        bible = self._load_json(self._bible_path())

        return {
            "series": outline.get("series_title", sid),
            "series_id": sid,
            "current_book": current_book,
            "current_chapter": progress.get("current_chapter", 1),
            "total_chapters": progress.get("total_chapters", 25),
            "chapters_completed_total": sum(
                self._load_json(self._progress_path(b)).get("chapters_completed", 0)
                for b in range(1, current_book + 1)
            ),
            "characters_tracked": len(bible.get("characters", {})),
            "world_facts": len(bible.get("world_facts", [])),
            "foreshadowing_active": len(bible.get("active_threads", [])),
            "foreshadowing_resolved": len(bible.get("resolved_threads", [])),
        }


# ---------------------------------------------------------------------------
# CLI for testing/status
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Series Engine for autoresearch-fantasy")
    parser.add_argument("--status", action="store_true", help="Show series status")
    parser.add_argument("--init", action="store_true", help="Initialize a new series")
    parser.add_argument("--next", action="store_true", help="Show next scenario (dry run)")
    args = parser.parse_args()

    engine = SeriesEngine()

    if args.status:
        status = engine.get_status()
        print(json.dumps(status, indent=2))
    elif args.init:
        engine.initialize_series()
    elif args.next:
        scenario = engine.get_next_scenario()
        print(f"Next scenario: {scenario['id']}")
        print(f"POV: {scenario.get('pov_character', 'unknown')}")
        print(f"Brief: {scenario['chapter_brief'][:200]}...")
        ctx = scenario.get("_series_context", {})
        print(f"Book {ctx.get('book_num')}, Chapter {ctx.get('chapter_num')}, Attempt {ctx.get('attempt')}")
    else:
        parser.print_help()
