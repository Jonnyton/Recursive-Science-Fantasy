"""
Benchmark Lane -Chapter Splitter

Parses a Gutenberg-style source text into individual chapter files.
Each chapter is saved as a separate text file in spike_inputs/.

Usage:
    python benchmark/chapter_splitter.py <source_file> [--output-dir benchmark/spike_inputs] [--chapters 5]
"""

import argparse
import os
import re
import sys


def split_chapters(text: str) -> list[dict]:
    """Split a Gutenberg-style text into chapters.

    Returns a list of dicts with keys: number, numeral, title, body, word_count.
    Handles Roman numeral chapter headings with optional italic title lines.
    """
    # Strip BOM if present
    text = text.lstrip("\ufeff")

    # Match centered chapter headings like "CHAPTER I" or "CHAPTER XXIV"
    chapter_pattern = re.compile(
        r"^\s+CHAPTER\s+([IVXLCDM]+)\s*$", re.MULTILINE
    )

    matches = list(chapter_pattern.finditer(text))
    if not matches:
        raise ValueError("No chapters found in source text.")

    chapters = []
    for i, match in enumerate(matches):
        numeral = match.group(1).strip()
        number = roman_to_int(numeral)
        start = match.end()

        # Find chapter end (next chapter heading or end of text)
        if i + 1 < len(matches):
            end = matches[i + 1].start()
        else:
            end = len(text)

        raw_body = text[start:end].strip()

        # Extract italic title line if present (e.g., "_The Plan of ..._")
        title = ""
        lines = raw_body.split("\n")
        body_start = 0
        for j, line in enumerate(lines):
            stripped = line.strip()
            if not stripped:
                continue
            # Check for italic title: _Title Text_
            title_match = re.match(r"^_(.+)_$", stripped)
            if title_match:
                title = title_match.group(1).strip()
                body_start = j + 1
            else:
                body_start = j
            break

        body = "\n".join(lines[body_start:]).strip()
        word_count = len(body.split())

        chapters.append({
            "number": number,
            "numeral": numeral,
            "title": title,
            "body": body,
            "word_count": word_count,
        })

    return chapters


def roman_to_int(s: str) -> int:
    """Convert a Roman numeral string to integer."""
    values = {"I": 1, "V": 5, "X": 10, "L": 50, "C": 100, "D": 500, "M": 1000}
    result = 0
    prev = 0
    for char in reversed(s.upper()):
        val = values.get(char, 0)
        if val < prev:
            result -= val
        else:
            result += val
        prev = val
    return result


def write_chapter_files(
    chapters: list[dict],
    output_dir: str,
    max_chapters: int | None = None,
) -> list[str]:
    """Write chapter files and return list of written paths."""
    os.makedirs(output_dir, exist_ok=True)
    paths = []

    for ch in chapters[:max_chapters]:
        filename = f"chapter_{ch['number']:02d}.txt"
        path = os.path.join(output_dir, filename)
        with open(path, "w", encoding="utf-8") as f:
            header = f"CHAPTER {ch['numeral']}"
            if ch["title"]:
                header += f"\n{ch['title']}"
            f.write(f"{header}\n\n{ch['body']}\n")
        paths.append(path)

    return paths


def main():
    parser = argparse.ArgumentParser(description="Split source text into chapter files.")
    parser.add_argument("source_file", help="Path to the source text file")
    parser.add_argument(
        "--output-dir",
        default="benchmark/spike_inputs",
        help="Output directory for chapter files (default: benchmark/spike_inputs)",
    )
    parser.add_argument(
        "--chapters",
        type=int,
        default=None,
        help="Maximum number of chapters to extract (default: all)",
    )
    args = parser.parse_args()

    with open(args.source_file, "r", encoding="utf-8") as f:
        text = f.read()

    chapters = split_chapters(text)
    print(f"Found {len(chapters)} chapters in source text.")

    paths = write_chapter_files(chapters, args.output_dir, args.chapters)
    for path in paths:
        ch = chapters[paths.index(path)]
        print(f"  {path} -- Chapter {ch['numeral']}: {ch['title'] or '(untitled)'} ({ch['word_count']} words)")

    print(f"\nWrote {len(paths)} chapter files to {args.output_dir}/")


if __name__ == "__main__":
    main()
