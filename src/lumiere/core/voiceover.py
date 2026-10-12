"""`data-lumiere-voiceover` - a frame says what is spoken over it, and its
anchors follow.

A scene host that carries its sentences needs no explicit anchor: it starts
on the first of those words as the recording has them, and it ends where the
next voiceover begins, or at the end of the film for the last one. Explicit
`data-lumiere-start` / `data-lumiere-end` always win over these defaults.

The words are the script, not the transcript: the speaker may have said
"Lumière" where the script reads "Lumiere". So the voiceovers are
aligned, in document order, against the recording as one script, and each
frame's first word lands where it was actually spoken; a word the speaker
replaced falls forward to the next one that matched.

The result is ordinary word anchors (`word:lumière#1`), so everything
downstream - the plan, the report, `lumiere words` - sees nothing new.
"""

from __future__ import annotations

from lumiere.core.anchor import Anchor, AnyAnchor, FilmAnchor
from lumiere.core.script_align import align_script
from lumiere.core.timeline import SourceTimeline, normalize

VOICEOVER = "data-lumiere-voiceover"


def word_anchor(timeline: SourceTimeline, index: int) -> Anchor:
    """The anchor that names exactly this timeline word: its text and its
    occurrence counted from the top of the recording."""
    text = normalize(timeline[index].text)
    occurrence = sum(
        1 for i, entry in timeline.words if i <= index and normalize(entry.text) == text
    )
    return Anchor(word=text, occurrence=occurrence)


def voiceover_anchors(
    voiceovers: list[str], timeline: SourceTimeline
) -> list[tuple[Anchor, AnyAnchor]]:
    """Default (start, end) anchors for voiceovers given in document order."""
    script: list[str] = []
    firsts: list[int] = []
    for n, text in enumerate(voiceovers, start=1):
        words = text.split()
        if not words:
            raise ValueError(f"voiceover {n} is empty; say what is spoken or anchor it explicitly")
        firsts.append(len(script))
        script.extend(words)

    alignment = align_script(timeline, script)
    starts: list[Anchor] = []
    for n, first in enumerate(firsts):
        limit = firsts[n + 1] if n + 1 < len(firsts) else len(script)
        index = next(
            (alignment.spoken_index_of[i] for i in range(first, limit) if i in alignment.spoken_index_of),
            None,
        )
        if index is None:
            raise ValueError(
                f"voiceover {n + 1} ({voiceovers[n][:40]!r}): none of its words were "
                f"found in the recording; give it a data-lumiere-start"
            )
        starts.append(word_anchor(timeline, index))

    ends: list[AnyAnchor] = [*starts[1:], FilmAnchor("end")]
    return list(zip(starts, ends))


def voiceover_coverage(voiceovers: list[str], timeline: SourceTimeline) -> list[float]:
    """For each voiceover, the share of its words the recording has in place.

    1.0 means every word was spoken where the voiceover says; a low number
    means the sentence on the host is not what was said over it - a stale
    voiceover after a narration change, or a host whose text drifted.
    """
    script: list[str] = []
    spans: list[tuple[int, int]] = []
    for text in voiceovers:
        words = text.split()
        spans.append((len(script), len(script) + len(words)))
        script.extend(words)
    alignment = align_script(timeline, script)
    return [
        (sum(1 for i in range(first, last) if i in alignment.spoken_index_of) / (last - first))
        if last > first else 0.0
        for first, last in spans
    ]
