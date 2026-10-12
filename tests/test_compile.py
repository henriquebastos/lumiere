"""Compiling anchors into the seconds a composition actually carries.

An anchor names a word in the narration; the plan says where the element
belongs. Every number a composition carries is produced here, so a mistake in
this module is a mistake nobody can see by reading the HTML.
"""

from __future__ import annotations

import pytest

from conftest import speech
from lumiere.core.anchor import Anchor, FilmAnchor
from lumiere.core.compile import AnchoredElement, Timing, frames, plan, sequence


def test_an_anchored_element_lands_on_its_word(simple):
    eyebrow = AnchoredElement(id="hf-eyebrow", start=Anchor("charlie"))

    result = plan([eyebrow], simple)

    assert result.times["hf-eyebrow"].start == pytest.approx(3.0)


def test_a_longer_narration_moves_the_element_and_the_element_is_never_re_authored():
    """The property the whole design exists for."""
    card = AnchoredElement(id="card", start=Anchor("charlie"), end=Anchor("echo"))

    before = plan([card], speech(["alpha", "bravo", "charlie", "delta", "echo"]))
    after = plan([card], speech(["alpha", "bravo", "um", "charlie", "delta", "echo"]))

    assert before.times["card"] == Timing(start=3.0, duration=3.0)
    assert after.times["card"] == Timing(start=4.5, duration=3.0)


def test_an_end_anchor_measures_the_distance_between_two_resolved_positions(simple):
    card = AnchoredElement(id="card", start=Anchor("bravo"), end=Anchor("delta", edge="end"))

    result = plan([card], simple)

    assert result.times["card"].start == pytest.approx(1.5)
    assert result.times["card"].duration == pytest.approx(4.0)  # 1.5 -> 5.5


def test_a_word_the_narration_lacks_stops_the_build(simple):
    card = AnchoredElement(id="card", start=Anchor("zulu"))

    with pytest.raises(KeyError, match="zulu"):
        plan([card], simple)


def test_an_anchor_resolves_inside_its_own_frame_not_the_whole_recording():
    timeline = speech(["and", "alpha", "and", "bravo"])
    inside = AnchoredElement(id="x", start=Anchor("and"), within=(2.5, 5.0))

    result = plan([inside], timeline)

    assert result.times["x"].start == pytest.approx(3.0)


def test_an_element_anchored_to_the_film_spans_the_narration(simple):
    root = AnchoredElement(id="main", start=FilmAnchor("start"), end=FilmAnchor("end"))

    result = plan([root], simple)

    assert result.times["main"] == Timing(start=0.0, duration=simple.duration)


def test_elements_with_their_own_narration_are_placed_back_to_back():
    hosts = [
        AnchoredElement(id="one", start=None, words="narration/one.words.json"),
        AnchoredElement(id="x", start=Anchor("alpha")),  # anchored: not part of the sequence
        AnchoredElement(id="two", start=None, words="narration/two.words.json"),
    ]

    placed = sequence(hosts, {"one": 4.0, "two": 16.5})

    assert placed.times == {"one": Timing(0.0, 4.0), "two": Timing(4.0, 16.5)}


def test_a_narration_lasts_a_whole_number_of_frames():
    assert frames(4.1497, 30) == pytest.approx(124 / 30)
    assert frames(4.151, 30) == pytest.approx(125 / 30)
    assert frames(0.001, 30) == pytest.approx(1 / 30)  # never zero
