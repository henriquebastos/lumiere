"""Binding a written script to what was actually said.

A storyboard is written against a script; timing exists only in the recording.
This maps one onto the other, so a note written as "zoom into the Harbor icon"
acquires a real source time without anyone estimating it.

This alignment is tolerant by design. A speaker
paraphrases, stumbles, contracts, and reads written numerals aloud, so
insertions and substitutions are expected. They are reported rather than
rejected - the divergence list is useful in itself, since it shows where
delivery left the plan.
"""

from __future__ import annotations

from dataclasses import dataclass
from difflib import SequenceMatcher

from lumiere.core.timeline import SourceTimeline, normalize


@dataclass(frozen=True)
class Divergence:
    kind: str  # "replace" | "insert" | "delete"
    script: str
    spoken: str


@dataclass(frozen=True)
class ScriptAlignment:
    """Where each script word ended up in the recording.

    `spoken_index_of` maps a script word position to a timeline entry index.
    Positions the speaker skipped or replaced have no entry.
    """

    spoken_index_of: dict[int, int]
    divergences: tuple[Divergence, ...]
    matched: int
    script_length: int
    spoken_length: int

    @property
    def match_rate(self) -> float:
        return self.matched / max(self.script_length, self.spoken_length, 1)

    def source_time_at(self, script_index: int, timeline: SourceTimeline) -> float | None:
        """Source time of a script word, or of the nearest matched word after it.

        Falls forward rather than failing: a note attached to a paraphrased word
        should still land somewhere sensible, and the nearest following match is
        the closest honest answer.
        """
        for i in range(script_index, self.script_length):
            entry = self.spoken_index_of.get(i)
            if entry is not None:
                return timeline[entry].start
        return None


def align_script(
    timeline: SourceTimeline, script_words: list[str]
) -> ScriptAlignment:
    """Match a written script against the spoken timeline."""
    words = timeline.words
    spoken = [normalize(e.text) for _, e in words]
    script = [normalize(w) for w in script_words]

    matcher = SequenceMatcher(a=script, b=spoken, autojunk=False)
    mapping: dict[int, int] = {}
    divergences: list[Divergence] = []
    matched = 0

    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            matched += i2 - i1
            for offset in range(i2 - i1):
                mapping[i1 + offset] = words[j1 + offset][0]
        else:
            divergences.append(
                Divergence(
                    kind=tag,
                    script=" ".join(script_words[i1:i2]),
                    spoken=" ".join(str(words[j][1].text).strip() for j in range(j1, j2)),
                )
            )

    return ScriptAlignment(
        spoken_index_of=mapping,
        divergences=tuple(divergences),
        matched=matched,
        script_length=len(script),
        spoken_length=len(spoken),
    )
