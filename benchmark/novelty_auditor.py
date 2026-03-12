"""
Benchmark Lane -- Novelty Auditor

Checks that a generated benchmark chapter has sufficient distance from the
source chapter. Catches copying, close paraphrase, and structural mimicry.

Returns a novelty report with pass/fail verdict.
"""

from difflib import SequenceMatcher
import re


# Minimum word overlap ratio that triggers a copying flag
NGRAM_OVERLAP_THRESHOLD = 0.15  # 15% shared 4-grams is suspiciously close
LONG_PHRASE_THRESHOLD = 8  # Flag shared phrases of 8+ words
MAX_SHARED_PHRASES = 3  # More than 3 shared long phrases = fail
MAX_REPORTED_SHARED_PHRASES = 12


def extract_ngrams(text: str, n: int = 4) -> set[tuple[str, ...]]:
    """Extract word-level n-grams from text."""
    words = _normalize(text).split()
    if len(words) < n:
        return set()
    return {tuple(words[i:i + n]) for i in range(len(words) - n + 1)}


def find_shared_long_phrases(source: str, generated: str,
                             min_length: int = LONG_PHRASE_THRESHOLD) -> list[str]:
    """Find verbatim shared phrases of min_length or more words."""
    source_words = _normalize(source).split()
    generated_words = _normalize(generated).split()
    matcher = SequenceMatcher(None, source_words, generated_words, autojunk=False)

    shared = []
    seen = set()
    for block in matcher.get_matching_blocks():
        if block.size < min_length:
            continue
        phrase = " ".join(source_words[block.a:block.a + block.size]).strip()
        if not phrase or phrase in seen:
            continue
        shared.append(phrase)
        seen.add(phrase)
        if len(shared) >= MAX_REPORTED_SHARED_PHRASES:
            break

    return shared


def compute_ngram_overlap(source: str, generated: str, n: int = 4) -> float:
    """Compute the fraction of generated n-grams that appear in the source."""
    source_ngrams = extract_ngrams(source, n)
    generated_ngrams = extract_ngrams(generated, n)

    if not generated_ngrams:
        return 0.0

    overlap = source_ngrams & generated_ngrams
    return len(overlap) / len(generated_ngrams)


def audit_novelty(source_text: str, generated_text: str) -> dict:
    """Run the full novelty audit.

    Returns:
        {
            "pass": bool,
            "ngram_overlap": float,
            "shared_long_phrases": list[str],
            "shared_phrase_count": int,
            "fail_reasons": list[str],
        }
    """
    fail_reasons = []

    # Check n-gram overlap
    overlap = compute_ngram_overlap(source_text, generated_text)
    if overlap > NGRAM_OVERLAP_THRESHOLD:
        fail_reasons.append(
            f"4-gram overlap {overlap:.1%} exceeds threshold {NGRAM_OVERLAP_THRESHOLD:.0%}"
        )

    # Check shared long phrases
    shared = find_shared_long_phrases(source_text, generated_text)
    if len(shared) > MAX_SHARED_PHRASES:
        fail_reasons.append(
            f"{len(shared)} shared phrases of {LONG_PHRASE_THRESHOLD}+ words "
            f"(max allowed: {MAX_SHARED_PHRASES})"
        )

    return {
        "pass": len(fail_reasons) == 0,
        "ngram_overlap": round(overlap, 4),
        "shared_long_phrases": shared,
        "shared_phrase_count": len(shared),
        "fail_reasons": fail_reasons,
    }


def _normalize(text: str) -> str:
    """Lowercase, strip punctuation, collapse whitespace."""
    text = text.lower()
    text = re.sub(r"[^\w\s]", "", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()
