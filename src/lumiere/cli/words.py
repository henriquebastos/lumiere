"""`lumiere words` - the anchor vocabulary of a words file.

Anchors address words the way `build` counts them: case-insensitive,
punctuation stripped, occurrences counted over the narration the file holds
(frame cues re-count within their own scene). This prints every token with
that occurrence number and its time, so an author picks anchors from what the
resolver will actually see - not from the script or memory of the take.
"""

from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Iterator

from lumiere.core.timeline import SourceTimeline, normalize

def words(words_file: Path) -> Iterator[str]:
    """Each word as `token#occurrence  start-end`, in spoken order."""
    timeline = SourceTimeline.read(words_file)
    seen: Counter[str] = Counter()
    for _, entry in timeline.words:
        key = normalize(entry.text)
        seen[key] += 1
        yield f"{entry.text}#{seen[key]}  {entry.start:.2f}-{entry.end:.2f}"
