"""Anchors: authored positions that survive a change of narration.

Two kinds, because a timed element answers one of two questions:

    word:Harbor#2.end+0.15   when in the speech does this happen
    film:end              where does the narration end

Authored timing is expressed here and nowhere else. Seconds are derived at
build time, so a re-recorded narration moves the second without touching the
anchor.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

from lumiere.core.timeline import SourceTimeline

Edge = Literal["start", "end", "mid"]
FilmEdge = Literal["start", "end"]
EDGES: tuple[Edge, ...] = ("start", "end", "mid")
FILM_EDGES: tuple[FilmEdge, ...] = ("start", "end")

# word:<text>[#<occurrence>][.<edge>][<signed offset>] - e.g. word:Harbor#2.end+0.15
#
# The edge alternatives are spelled out rather than matched as a generic
# suffix, because punctuation travels with words from the provider: `word:
# revenue.` must keep its full stop as part of the word instead of losing it
# to an edge that does not exist.
GRAMMAR = re.compile(
    r"^word:(?P<word>.+?)"
    r"(?:#(?P<occurrence>\d+))?"
    r"(?:\.(?P<edge>start|end|mid))?"
    r"(?P<offset>[+-]\d*\.?\d+)?$"
)


@dataclass(frozen=True)
class Anchor:
    """A position in source time, named by a word.

    `occurrence` counts from one, because it is authored by hand and read far
    more often than it is parsed: `#2` is the second such word. The timeline
    counts from zero, and the translation happens here, once.
    """

    word: str
    occurrence: int = 1
    edge: Edge = "start"
    offset: float = 0.0

    def __post_init__(self) -> None:
        if self.occurrence < 1:
            raise ValueError(
                f"occurrence counts from one, got {self.occurrence}"
            )
        if self.edge not in EDGES:
            raise ValueError(
                f"edge must be one of {', '.join(EDGES)}, got {self.edge!r}"
            )

    @classmethod
    def parse(cls, spec: str) -> Anchor:
        """Read the written form an author types into a composition."""
        match = GRAMMAR.match(spec.strip())
        if match is None:
            raise ValueError(f"not an anchor: {spec!r}")
        occurrence = match.group("occurrence")
        edge = match.group("edge")
        offset = match.group("offset")
        return cls(
            word=match.group("word"),
            occurrence=int(occurrence) if occurrence else 1,
            edge=edge or "start",
            offset=float(offset) if offset else 0.0,
        )

    def spec(self) -> str:
        """The written form, as an author would type it: the inverse of `parse`.
        A `#1` and a `.start` are the defaults and are left out; the offset
        is printed to the millisecond only when there is one."""
        text = f"word:{self.word}"
        if self.occurrence != 1:
            text += f"#{self.occurrence}"
        if self.edge != "start":
            text += f".{self.edge}"
        return text + _offset(self.offset)

    def shifted(self, by: float) -> Anchor:
        """The same anchor with `by` seconds more offset."""
        return Anchor(self.word, self.occurrence, self.edge, round(self.offset + by, 3))

    def resolve(
        self,
        timeline: SourceTimeline,
        within: tuple[float, float] | None = None,
    ) -> float:
        """The source time this anchor names, searched inside `within`."""
        index = timeline.find_word(
            self.word, occurrence=self.occurrence - 1, within=within
        )
        entry = timeline[index]
        if self.edge == "end":
            at = entry.end
        elif self.edge == "mid":
            at = entry.start + entry.duration / 2
        else:
            at = entry.start
        return at + self.offset

    def at(
        self,
        timeline: SourceTimeline,
        within: tuple[float, float] | None = None,
    ) -> float:
        """Where this lands in the narration: the word's edge plus the offset."""
        return self.resolve(timeline, within)


@dataclass(frozen=True)
class FilmAnchor:
    """A position in the narration as a whole rather than at a word.

    Answers "how long is the film", not "when was this said": `film:end` is
    where the narration this element belongs to ends.

    It names the timeline every element shares, not the element's own material:
    an audio track anchored to `film:end` runs to the end of the film, exactly
    as a frame anchored there does.

    An offset extends past the material: `film:end+2.0` is two seconds of held
    picture after the last word — the breath a close needs, which no recording
    can supply.
    """

    edge: FilmEdge = "start"
    offset: float = 0.0

    def __post_init__(self) -> None:
        if self.edge not in FILM_EDGES:
            raise ValueError(
                f"film edge must be one of {', '.join(FILM_EDGES)}, "
                f"got {self.edge!r}"
            )

    def spec(self) -> str:
        """The written form: `film:end+2.000`, `film:start`."""
        return f"film:{self.edge}{_offset(self.offset)}"

    def shifted(self, by: float) -> FilmAnchor:
        return FilmAnchor(self.edge, round(self.offset + by, 3))

    def at(
        self,
        timeline: SourceTimeline,
        within: tuple[float, float] | None = None,
    ) -> float:
        base = timeline.duration if self.edge == "end" else 0.0
        return base + self.offset


@dataclass(frozen=True)
class FrameAnchor:
    """A position in the composition's own span: `frame:start`, `frame:end-0.5`.

    A composition that inherits its narration still has to say how long it
    is - as long as the host that mounts it. `frame:end` is that end, exactly
    as it is for the exits cued inside the frame.
    """

    edge: FilmEdge = "start"
    offset: float = 0.0

    def __post_init__(self) -> None:
        if self.edge not in FILM_EDGES:
            raise ValueError(
                f"frame edge must be one of {', '.join(FILM_EDGES)}, got {self.edge!r}"
            )

    def spec(self) -> str:
        return f"frame:{self.edge}{_offset(self.offset)}"

    def shifted(self, by: float) -> FrameAnchor:
        return FrameAnchor(self.edge, round(self.offset + by, 3))

    def at_frame(self, start: float, duration: float) -> float:
        """Where this lands in the narration, given the frame's span in it."""
        return start + (duration if self.edge == "end" else 0.0) + self.offset

    def at(
        self,
        timeline: SourceTimeline,
        within: tuple[float, float] | None = None,
    ) -> float:
        raise ValueError("a frame anchor needs the frame's span; the plan supplies it")


def _offset(offset: float) -> str:
    return f"{offset:+.3f}" if round(offset, 3) else ""


#: Either kind of authored position. Both answer `at()`, so nothing downstream
#: needs to know which one an element carries.
AnyAnchor = Anchor | FilmAnchor | FrameAnchor


def parse_anchor(spec: str) -> AnyAnchor:
    """Read an authored `data-lumiere-start` value, whichever kind it names."""
    text = spec.strip()
    if text.startswith("frame:"):
        match = re.match(r"^(?P<edge>start|end)(?P<offset>[+-]\d*\.?\d+)?$", text[len("frame:") :])
        if match is None:
            raise ValueError(
                f"frame anchors are {' or '.join(FILM_EDGES)} with an optional "
                f"signed offset, got {spec!r}"
            )
        return FrameAnchor(match.group("edge"), float(match.group("offset") or 0.0))
    if text.startswith("film:"):
        body = text[len("film:") :]
        match = re.match(
            r"^(?P<edge>start|end)(?P<offset>[+-]\d*\.?\d+)?$", body
        )
        if match is None:
            raise ValueError(
                f"film anchors are {' or '.join(FILM_EDGES)} "
                f"with an optional signed offset, got {spec!r}"
            )
        offset = match.group("offset")
        return FilmAnchor(
            match.group("edge"), float(offset) if offset else 0.0
        )
    return Anchor.parse(text)
