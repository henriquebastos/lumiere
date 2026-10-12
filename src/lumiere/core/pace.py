"""Speaking pace, and how far a transcript is from the text it should be.

Pace here is articulation rate: syllables per second of actual speech. The
denominator is the audio's duration minus its quiet stretches, so a long
pause between sentences does not make a brisk reading look slow. Every video
reads the same number from the same function.

Syllables are counted, not heard. The CMU Pronouncing Dictionary gives a
count for ordinary English; names and acronyms it does not know get an
explicit count in a JSON file the caller names with `--syllables`, the way
`speak --lexicon` names respellings. An unknown word is an error rather than
a guess, because a guessed
syllable would make the pace look more exact than it is.
"""

from __future__ import annotations

import difflib
import json
from dataclasses import dataclass
from functools import cache
from pathlib import Path

import numpy as np

from lumiere.core.timeline import normalize

RATE = 44100
# Samples per 10 ms RMS frame.
FRAME = RATE // 100
# -40 dBFS: below this a frame counts as quiet, not speech.
QUIET_RMS = 0.01
# A quiet run shorter than 200 ms is a stop inside speech, not a pause.
QUIET_FRAMES = 20


@cache
def _dictionary() -> dict[str, list[list[str]]]:
    import cmudict

    return cmudict.dict()


def load_syllable_overrides(*paths: Path) -> dict[str, int]:
    """Merge syllable counts for words the dictionary does not know; later paths win.

    Mirrors `load_lexicon`: the caller names the file(s) with `--syllables`;
    nothing is read that was not named.
    """
    merged: dict[str, int] = {}
    for path in paths:
        if not path.exists():
            continue
        entries = json.loads(path.read_text())
        if not isinstance(entries, dict) or not all(
            isinstance(count, int) for count in entries.values()
        ):
            raise ValueError(f"{path}: syllable overrides are a JSON object of word -> count")
        merged.update(entries)
    return merged


def syllables(text: str, overrides: dict[str, int]) -> int:
    """Count the syllables in `text`: the dictionary, then the overrides."""
    total = 0
    for word in text.lower().split():
        word = word.strip('.,!?;:"').replace("’", "'")
        if not word:
            continue
        if word in overrides:
            total += overrides[word]
        elif word in _dictionary():
            total += min(
                sum(phone[-1].isdigit() for phone in pronunciation)
                for pronunciation in _dictionary()[word]
            )
        elif "-" in word:
            total += syllables(word.replace("-", " "), overrides)
        else:
            raise ValueError(f"no syllable count for {word!r}: add it to the file given as --syllables")
    return total


@dataclass(frozen=True)
class Pace:
    duration: float
    quiet: float
    syllables: int
    # Syllables per second of speech; None when the audio holds no speech at all.
    articulation_sps: float | None


def pace(pcm: np.ndarray, count: int) -> Pace:
    """Articulation rate of mono samples at `RATE`, given their syllable count.

    Quiet is measured on 10 ms RMS frames. A run below -40 dBFS counts when it
    lasts 200 ms or more, or when it touches either end of the file: leading
    and trailing silence is never speech, however short.
    """
    frames = len(pcm) // FRAME
    rms = np.sqrt(np.mean(pcm[: frames * FRAME].reshape(-1, FRAME) ** 2, axis=1))
    edges = np.diff(np.r_[False, rms < QUIET_RMS, False].astype(int))
    runs = [
        (start, end)
        for start, end in zip(np.where(edges == 1)[0], np.where(edges == -1)[0])
        if end - start >= QUIET_FRAMES or start == 0 or end == frames
    ]
    duration = len(pcm) / RATE
    quiet = sum((end - start) * 0.01 for start, end in runs)
    speech = duration - quiet
    return Pace(
        duration=duration,
        quiet=quiet,
        syllables=count,
        articulation_sps=count / speech if speech > 0 else None,
    )


def transcript_match(text: str, recognized: list[str]) -> float:
    """How much of `text` a transcript recognised, 0 to 1, by letters alone.

    Case, punctuation, and word boundaries are ignored so that `PRs` and
    `P.R.s` agree; spelling is not, so a misheard name still shows.
    """
    return difflib.SequenceMatcher(
        None, normalize(text), normalize(" ".join(recognized)), autojunk=False
    ).ratio()
