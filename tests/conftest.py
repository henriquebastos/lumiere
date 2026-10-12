from __future__ import annotations

import pytest

from lumiere.core.timeline import Entry, SourceTimeline


def build(spec: list[tuple[str, str, float, float]]) -> SourceTimeline:
    """Build a timeline from (kind, text, start, end) tuples."""
    entries = tuple(Entry(kind=k, text=t, start=s, end=e) for k, t, s, e in spec)
    return SourceTimeline(
        entries=entries, media="synthetic", duration=entries[-1].end
    )


def speech(words: list[str], word_dur: float = 1.0, gap: float = 0.5) -> SourceTimeline:
    """A timeline of evenly spaced words separated by silences.

    Word i occupies [i*(word_dur+gap), i*(word_dur+gap)+word_dur]; the silence
    after it fills the gap. Regular enough that expected projections can be
    computed by hand in a test.
    """
    spec: list[tuple[str, str, float, float]] = []
    t = 0.0
    for i, w in enumerate(words):
        spec.append(("word", w, t, t + word_dur))
        t += word_dur
        if i < len(words) - 1:
            spec.append(("spacing", " ", t, t + gap))
            t += gap
    return build(spec)


@pytest.fixture
def simple() -> SourceTimeline:
    return speech(["alpha", "bravo", "charlie", "delta", "echo"])
