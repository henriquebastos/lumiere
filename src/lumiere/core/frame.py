"""Anchors inside a frame's own timeline.

A frame is a sub-composition: its GSAP timeline starts at zero and everything
in it is an offset from the frame's own start. So an anchor here resolves the
same way as anywhere else - to a position in the finished film - and is then
expressed relative to the frame.

The position stays a numeric literal in the file. Studio's GSAP editor parses
these timelines to offer keyframe editing, and a computed expression would take
that away; the anchor rides alongside in a comment instead.
"""

from __future__ import annotations

import re

from lumiere.core.anchor import parse_anchor
from lumiere.core.timeline import SourceTimeline

#: The comment marker that hands a GSAP position to Lumiere.
CUE = "@lumiere"

# A GSAP call whose position argument carries an anchor: the trailing
# `// @lumiere <anchor>` is the authored truth, the number in front of it is
# regenerated from it.
CUED_CALL = re.compile(
    r"(?P<head>tl\.\w+\([^;\n]*,)"
    r"(?P<position>-?\d+(?:\.\d+)?)"
    rf"(?P<tail>\);\s*//\s*{CUE}\s+)"
    # Stops at markup: a cue is usually last on its line, but not always, and
    # an anchor may never contain `<`.
    r"(?P<anchor>[^\s<]+)"
)


# frame:start / frame:end, with an optional signed offset. Not every position
# is a sync point: an exit belongs just before the frame gives way to the next,
# and the frame's duration is itself derived.
FRAME_CUE = re.compile(r"^frame:(?P<edge>start|end)(?P<offset>[+-]\d*\.?\d+)?$")


def patch_cues(
    source: str,
    timeline: SourceTimeline,
    frame_start: float,
    frame_duration: float = 0.0,
    within: tuple[float, float] | None = None,
) -> str:
    """Rewrite every cued position as an offset into this frame's timeline.

    `within` is the frame's own span in the narration. Word cues resolve
    inside it, so `word:And#1` in a frame means the first "And" *of that
    scene* - counting from the top of the narration would rebind every cue
    the moment the narration upstream changes.
    """

    def place(match: re.Match[str]) -> str:
        spec = match.group("anchor")

        scoped = FRAME_CUE.match(spec)
        if scoped:
            base = frame_duration if scoped.group("edge") == "end" else 0.0
            at = frame_start + base + float(scoped.group("offset") or 0.0)
        else:
            try:
                at = parse_anchor(spec).at(timeline, within)
            except KeyError as missing:
                raise ValueError(f"{spec}: {missing.args[0]}") from None
        return f"{match.group('head')}{at - frame_start:.3f}{match.group('tail')}{spec}"

    return CUED_CALL.sub(place, source)
