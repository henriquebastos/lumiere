"""Joining parts: which files, in what order, with what pause after each.

A narration is made in parts so that one bad sentence can be redone alone.
Joining them back must not lose what each part already knows. Its word
timings were measured once, against that part's own audio; joining only
moves them by the part's offset in the joined audio. Nothing is
transcribed again, so a word keeps the time it was approved at.

Offsets are counted in samples, not seconds. A pause becomes a whole number
of samples, and a part starts exactly where the samples before it end, so
the shifted times describe the joined audio rather than a sum of rounded
seconds. Shifted times are rounded to the microsecond, so joining the same
parts always writes the same timing.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Iterable

from lumiere.core.timeline import Entry, SourceTimeline

# Microseconds: the precision a joined word timing is written to.
TIME_DECIMALS = 6


@dataclass(frozen=True)
class Part:
    """One audio file of a sequence and the seconds of silence after it."""

    audio: Path
    pause: float


def parse_sequence(lines: Iterable[str], base: Path) -> list[Part]:
    """A sequence file: one file per line, then the pause after it.

    Paths are relative to the sequence file, given here as `base`, so a
    sequence can be moved with its parts. The pause may be omitted and is
    then zero; a line ends with the pause, so a path may contain spaces.
    """
    parts: list[Part] = []
    for number, line in enumerate(lines, start=1):
        path, pause = line, "0"
        fields = line.rsplit(None, 1)
        if len(fields) == 2 and _is_number(fields[1]):
            path, pause = fields
        seconds = float(pause)
        if not 0 <= seconds < math.inf:
            raise ValueError(f"line {number}: the pause after {path!r} is not a duration")
        audio = Path(path)
        parts.append(Part(audio if audio.is_absolute() else base / audio, seconds))
    return parts


def _is_number(text: str) -> bool:
    try:
        float(text)
    except ValueError:
        return False
    return True


def pause_samples(pause: float, rate: int) -> int:
    return round(pause * rate)


def shifted(entry: Entry, seconds: float) -> Entry:
    return replace(
        entry,
        start=round(entry.start + seconds, TIME_DECIMALS),
        end=round(entry.end + seconds, TIME_DECIMALS),
    )


def joined_timeline(
    parts: Iterable[tuple[SourceTimeline, int]],
    rate: int,
    total_samples: int,
    media: str,
) -> SourceTimeline:
    """One timeline from each part's timeline and its offset in samples.

    The language is kept when every part agrees on it.
    """
    entries: list[Entry] = []
    languages: set[str | None] = set()
    for timeline, offset in parts:
        entries.extend(shifted(entry, offset / rate) for entry in timeline.entries)
        languages.add(timeline.language)
    return SourceTimeline(
        entries=tuple(entries),
        media=media,
        duration=total_samples / rate,
        language=languages.pop() if len(languages) == 1 else None,
    )
