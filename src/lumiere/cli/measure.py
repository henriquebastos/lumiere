"""`lumiere measure` - what an audio file sounds like, as numbers.

One JSON line per file: duration, integrated loudness, true peak, pace, and
how well its transcript matches its text. `verify` turns these numbers into
checks; `measure` only reports them, so a video's scripts can look before
deciding what to require.

Pace needs the spoken text for its syllable count. It comes from the `text`
that `speak` recorded in the `a.wav.json` companion, or from `--text-file`
for a single file. The transcript match compares that text with the words
in `a.words.json`. Either companion may be absent; the number is then null
rather than guessed.
"""

from __future__ import annotations

import statistics
import sys
from pathlib import Path
from typing import Any, Iterable

import numpy as np

from lumiere.adapters.audio import load_mono, loudness
from lumiere.core.pace import (
    RATE,
    load_syllable_overrides,
    pace,
    syllables,
    transcript_match,
)
from lumiere.cli.conventions import (
    STREAM,
    read_lines,
    read_recipe,
    read_text,
    read_words_json,
    recipe_path,
    words_path,
)

METRICS = ("duration", "lufs", "true_peak", "pace", "match")


def audio_paths(arguments: Iterable[Path]) -> list[Path]:
    """The files to measure; `-` stands for one path per line on stdin."""
    paths: list[Path] = []
    for argument in arguments:
        if str(argument) == STREAM:
            paths.extend(Path(line) for line in read_lines([STREAM]))
        else:
            paths.append(argument)
    return paths


def text_for(audio: Path, text_file: Path | None) -> str | None:
    """The text spoken in `audio`: `--text-file` if given, else the companion's."""
    if text_file is not None:
        return read_text(text_file)
    text = read_recipe(audio).get("text")
    return text if isinstance(text, str) else None


def recognized_words(words: Path) -> list[str] | None:
    """The words in a word-timing file, or None when there is none."""
    if not words.is_file():
        return None
    return [entry.text for _, entry in read_words_json(words).words]


def articulation(pcm: np.ndarray, text: str, overrides: dict[str, int]) -> float | None:
    """Syllables per second of speech in `pcm`, decoded at `RATE`.

    `overrides` are syllable counts for words the dictionary lacks, from the
    file the caller named with `--syllables`.
    """
    return pace(pcm, syllables(text, overrides)).articulation_sps


def overrides_from(syllables_file: Path | None) -> dict[str, int]:
    """The syllable overrides a command was given, or none."""
    return load_syllable_overrides(syllables_file) if syllables_file else {}


def measure(audio: Path, text: str | None, overrides: dict[str, int] | None = None) -> dict[str, Any]:
    """Measure one file."""
    lufs, true_peak = loudness(audio)
    pcm = load_mono(audio, rate=RATE)
    record: dict[str, Any] = {
        "file": str(audio),
        "duration": len(pcm) / RATE,
        "lufs": lufs,
        "true_peak": true_peak,
        "pace": None,
        "match": None,
    }
    if text is None:
        print(
            f"{audio}: no text - give --text-file or a 'text' in {recipe_path(audio).name}; "
            "pace is null",
            file=sys.stderr,
        )
        return record
    record["pace"] = articulation(pcm, text, overrides or {})
    words = recognized_words(words_path(audio))
    if words is not None:
        record["match"] = transcript_match(text, words)
    return record


def summarize(records: list[dict[str, Any]]) -> dict[str, Any]:
    """Median, min, and max of every metric over the files that have it."""
    summary: dict[str, Any] = {"files": len(records)}
    for metric in METRICS:
        values = [record[metric] for record in records if record[metric] is not None]
        summary[metric] = (
            {"median": statistics.median(values), "min": min(values), "max": max(values)}
            if values
            else None
        )
    return {"summary": summary}
