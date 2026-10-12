"""From anchors to the seconds a composition carries.

The plan is the only place seconds are produced. It is pure: it reads a
timeline and returns numbers. Writing those numbers into a file is somebody
else's job, so the interesting behaviour can be tested without a filesystem.
"""

from __future__ import annotations

from dataclasses import dataclass

from lumiere.core.anchor import AnyAnchor, FrameAnchor
from lumiere.core.timeline import SourceTimeline


@dataclass(frozen=True)
class AnchoredElement:
    """A timed element whose position is authored as a word, not a second."""

    id: str
    #: None for an element timed by its own narration (`words`): it starts
    #: where the previous such element ends and lasts as long as its words.
    start: AnyAnchor | None
    end: AnyAnchor | None = None
    #: The source window this element's anchors are searched in - normally the
    #: frame it belongs to, so `word:Harbor` means the Harbor in *this* scene.
    within: tuple[float, float] | None = None
    #: Project-relative path of the word timings this element's composition
    #: is resolved against, when it carries its own narration.
    words: str | None = None


@dataclass(frozen=True)
class Timing:
    """One element's place in the finished video, in output seconds."""

    start: float
    duration: float = 0.0


@dataclass(frozen=True)
class TimingPlan:
    """Where every element belongs in the finished video."""

    times: dict[str, Timing]


def plan(
    elements: list[AnchoredElement],
    timeline: SourceTimeline,
    frame: tuple[float, float] = (0.0, 0.0),
) -> TimingPlan:
    """Resolve each element's anchors into seconds of its narration.

    `frame` is the span, in that narration, of the composition the elements
    belong to: what `frame:start` and `frame:end` mean here.
    """

    def at(anchor: AnyAnchor, within: tuple[float, float] | None) -> float:
        if isinstance(anchor, FrameAnchor):
            return anchor.at_frame(*frame)
        return anchor.at(timeline, within)

    times: dict[str, Timing] = {}
    for element in elements:
        if element.start is None:
            continue  # timed by its narration: see `sequence`
        start = at(element.start, element.within)
        duration = 0.0
        if element.end is not None:
            # Duration is the distance between two resolved positions.
            duration = at(element.end, element.within) - start
        times[element.id] = Timing(start=start, duration=duration)
    return TimingPlan(times=times)


def frames(seconds: float, fps: int) -> float:
    """`seconds` as a whole number of frames at `fps`, at least one.

    A renderer cannot emit a fraction of a frame, so a narration's length is
    what the renderer will realise, not what the file says.
    """
    return max(round(seconds * fps), 1) / fps


def sequence(elements: list[AnchoredElement], lengths: dict[str, float]) -> TimingPlan:
    """Place the elements that carry their own narration back to back.

    `lengths` is each such element's narration length in seconds. The first
    starts at zero and every next one where the previous ends: the air
    between scenes is the pause at the end of a scene's own narration.
    """
    times: dict[str, Timing] = {}
    cursor = 0.0
    for element in elements:
        if element.words is None:
            continue
        duration = lengths[element.id]
        times[element.id] = Timing(start=cursor, duration=duration)
        cursor += duration
    return TimingPlan(times=times)
