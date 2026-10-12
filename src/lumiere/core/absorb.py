"""Absorb a timing edit made in Studio into the anchors it came from.

Studio moves a clip or a keyframe by writing a new second. Lumiere's build
would write the derived second back, because the number is not the source;
the anchor is. Absorbing closes that loop the other way: the difference
between the number on disk and the number the anchors give becomes more
offset on the anchor, so the build then agrees with what the editor saw.

Both functions take the file as it is on disk and as `resolve` would write
it. The two differ only in the numbers, so their elements and cues line up
one to one.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from lumiere.core.anchor import AnyAnchor, parse_anchor
from lumiere.core.compile import AnchoredElement
from lumiere.core.composition import ANCHORED_TAG, END, START, set_attribute, attribute, identify
from lumiere.core.frame import CUED_CALL

#: Below this, a difference is rounding, not an edit.
TOLERANCE = 0.0005


@dataclass(frozen=True)
class Change:
    """One anchor moved to honour an edited second."""

    element: str
    before: str
    after: str

    def __str__(self) -> str:
        return f"{self.element}: {self.before} -> {self.after}"


def shift_spec(spec: str, by: float) -> str:
    """The written anchor with `by` seconds more offset, for every kind of
    anchor a cue can carry, including a frame's own edges."""
    return parse_anchor(spec).shifted(by).spec()


def absorb_frame(disk: str, resolved: str) -> tuple[str, list[Change]]:
    """Move each cue's offset so the position on disk is the derived one."""
    on_disk = list(CUED_CALL.finditer(disk))
    derived = list(CUED_CALL.finditer(resolved))
    if [m.group("anchor") for m in on_disk] != [m.group("anchor") for m in derived]:
        raise ValueError("the cues on disk and the derived cues do not line up; run `lumiere build` first")

    changes: list[Change] = []
    out: list[str] = []
    last = 0
    for here, there in zip(on_disk, derived):
        delta = float(here.group("position")) - float(there.group("position"))
        if abs(delta) < TOLERANCE:
            continue
        spec = here.group("anchor")
        moved = shift_spec(spec, delta)
        element = re.search(r'\(\s*"([^"]*)"', here.group("head"))
        changes.append(Change(element.group(1) if element else "?", spec, moved))
        out.append(disk[last : here.start("anchor")])
        out.append(moved)
        last = here.end("anchor")
    out.append(disk[last:])
    return "".join(out), changes


def _seconds(tag: str) -> tuple[float, float] | None:
    start, duration = attribute(tag, "data-start"), attribute(tag, "data-duration")
    if start is None:
        return None
    return float(start), float(duration or 0.0)


def absorb_hosts(
    disk: str, resolved: str, elements: list[AnchoredElement]
) -> tuple[str, list[Change]]:
    """Move each timed element's anchors so its seconds on disk are the
    derived ones. `elements` are the anchors as read from `disk`, defaults
    included, so an element timed by its voiceover alone gets an explicit
    anchor the moment it is moved."""
    on_disk = list(ANCHORED_TAG.finditer(disk))
    derived = list(ANCHORED_TAG.finditer(resolved))
    if len(on_disk) != len(derived) or len(on_disk) != len(elements):
        raise ValueError("the elements on disk and the derived ones do not line up; run `lumiere build` first")

    changes: list[Change] = []
    out: list[str] = []
    last = 0
    for here, there, element in zip(on_disk, derived, elements):
        tag = here.group(0)
        mine, theirs = _seconds(tag), _seconds(there.group(0))
        if mine is None or theirs is None or element.start is None:
            continue  # no anchor to move: a host timed by its narration
        delta_start = mine[0] - theirs[0]
        delta_end = (mine[0] + mine[1]) - (theirs[0] + theirs[1])
        name = identify(tag) or "?"
        new_tag = tag
        if abs(delta_start) >= TOLERANCE:
            moved: AnyAnchor = element.start.shifted(delta_start)
            changes.append(Change(name, f"{START}={element.start.spec()}", f"{START}={moved.spec()}"))
            new_tag = set_attribute(new_tag, START, moved.spec())
        if abs(delta_end) >= TOLERANCE:
            end = element.end if element.end is not None else element.start
            moved_end = end.shifted(delta_end)
            changes.append(Change(name, f"{END}={end.spec()}", f"{END}={moved_end.spec()}"))
            new_tag = set_attribute(new_tag, END, moved_end.spec())
        if new_tag != tag:
            out.append(disk[last : here.start()])
            out.append(new_tag)
            last = here.end()
    out.append(disk[last:])
    return "".join(out), changes
