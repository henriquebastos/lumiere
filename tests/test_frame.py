"""Anchoring the motion *inside* a frame.

A frame's GSAP positions are relative to the frame's own start. The anchor is
written next to the tween it moves, the same way an element declares its own
timing. Positions stay numeric literals in the file so the composition
remains something Studio's GSAP editor can still read.
"""

from __future__ import annotations

import pytest

from conftest import speech
from lumiere.core.frame import patch_cues

TWEEN = (
    '          tl.fromTo("#t1",{scale:0.6,opacity:0},'
    '{scale:1,opacity:1,duration:0.5,ease:E},0.960);  // @lumiere word:charlie\n'
)


def test_a_marked_tween_is_placed_relative_to_its_own_frame(simple):
    """The frame's timeline starts at zero, so the cue is an offset into it.

    "charlie" is at 3.0s in the narration; a frame that starts on "bravo"
    (1.5s) must place the tween at 1.5s into its own timeline, not at 3.0s.
    """
    patched = patch_cues(TWEEN, simple, frame_start=1.5)

    assert ",1.500);" in patched
    assert "// @lumiere word:charlie" in patched  # the anchor is never consumed


def test_a_longer_narration_before_the_word_moves_the_motion_with_it():
    """Re-record the scene so "charlie" comes a second later: the tween
    follows the word, and nothing in the file is re-authored."""
    before = speech(["alpha", "bravo", "charlie"])
    after = speech(["alpha", "bravo", "um", "charlie"])

    assert ",3.000);" in patch_cues(TWEEN, before, frame_start=0.0)
    assert ",4.500);" in patch_cues(TWEEN, after, frame_start=0.0)


def test_a_space_before_the_position_still_carries_the_cue(simple):
    """Formatters put a space after a comma. The cue must not depend on it:
    a skipped cue leaves a stale number in the file and no error anywhere."""
    tween = '  tl.add(K.rise("#t1"), 9.999);  // @lumiere word:charlie\n'

    patched = patch_cues(tween, simple, frame_start=1.5)

    assert patched == '  tl.add(K.rise("#t1"), 1.500);  // @lumiere word:charlie\n'


def test_an_exit_can_be_cued_to_the_frames_own_end(simple):
    """Not every position is a sync point.

    An exit is not "when he says X" - it is "just before this frame gives way
    to the next". The frame's duration is derived, so the exit has to be
    derived with it or it drifts every time the narration changes length.
    """
    tween = (
        '          tl.to("#eb",{opacity:0,duration:0.533},9.999);'
        "  // @lumiere frame:end-0.533\n"
    )

    patched = patch_cues(tween, simple, frame_start=1.5, frame_duration=4.5)

    assert ",3.967);" in patched  # 4.5 - 0.533, relative to the frame


def test_motion_cued_to_a_word_the_narration_lacks_stops_the_build():
    """There is no honest place to put it. The author decides."""
    with pytest.raises(ValueError, match="charlie"):
        patch_cues(TWEEN, speech(["alpha", "bravo"]), frame_start=0.0)


def test_a_word_cue_counts_occurrences_inside_its_own_scene():
    """`word:and#1` in a frame is that scene's first "and".

    Counted from the top of the narration, every cue's occurrence number
    silently rebinds when narration upstream changes. Scoping to the frame's
    span makes the cue mean what its author meant, and keeps it meaning that
    through a re-record.
    """
    timeline = speech(["and", "alpha", "and", "bravo", "and", "charlie"])
    tween = (
        'tl.fromTo("#t1",{opacity:0},{opacity:1,duration:0.5,ease:E},9.999);'
        "  // @lumiere word:and#1\n"
    )

    # the frame spans the middle of the narration: its first "and" is the
    # narration's second, at 3.0s - 0.5s into the frame.
    patched = patch_cues(tween, timeline, frame_start=2.5, within=(2.5, 5.5))

    assert ",0.500);" in patched


def test_a_word_cue_outside_its_scene_stops_the_build_with_the_window():
    timeline = speech(["and", "alpha", "bravo"])
    tween = (
        'tl.to("#t1",{opacity:0,duration:0.5,ease:E},9.999);'
        "  // @lumiere word:charlie\n"
    )

    with pytest.raises(ValueError, match="charlie"):
        patch_cues(tween, timeline, frame_start=1.5, within=(1.5, 4.0))
