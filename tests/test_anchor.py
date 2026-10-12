"""Anchors: positions expressed in words rather than seconds.

An anchor is the authored truth about *when* something happens. It survives a
re-recorded narration because it names a word, and words keep their identity
when the audio around them changes. Every second that reaches a composition is
derived from one of these; none is typed by hand.

These tests exist to keep two properties honest: an anchor means exactly one
word, and an anchor that cannot be resolved is an error rather than a guess.
"""

from __future__ import annotations

import pytest

from conftest import speech
from lumiere.core.anchor import Anchor, FilmAnchor, parse_anchor


def test_an_anchor_resolves_to_the_start_of_its_word(simple):
    # speech() lays "alpha bravo charlie delta echo" on a 1.0s word / 0.5s gap
    # grid, so word i starts at i * 1.5.
    assert Anchor(word="charlie").resolve(simple) == pytest.approx(3.0)


def test_occurrence_counts_from_one_so_the_written_form_reads_correctly():
    """`word:and#2` must mean the second 'and', not the third.

    The grammar is written by hand next to the element it moves, so it is read
    far more often than it is parsed. An off-by-one here is silent: the anchor
    still resolves, just to the wrong word.
    """
    timeline = speech(["and", "then", "and", "again", "and"])

    assert Anchor(word="and").resolve(timeline) == pytest.approx(0.0)
    assert Anchor(word="and", occurrence=2).resolve(timeline) == pytest.approx(3.0)
    assert Anchor(word="and", occurrence=3).resolve(timeline) == pytest.approx(6.0)


def test_an_offset_shifts_the_position_without_changing_which_word_it_names():
    """Motion often wants to lead or trail the word it belongs to.

    The offset is deliberately part of the anchor rather than a separate
    authored number: it travels with the word through a re-recording, so a
    gesture that starts 200ms before "Harbor" keeps starting 200ms before "Harbor".
    """
    timeline = speech(["alpha", "bravo", "charlie"])

    assert Anchor(word="bravo", offset=-0.2).resolve(timeline) == pytest.approx(1.3)
    assert Anchor(word="bravo", offset=0.25).resolve(timeline) == pytest.approx(1.75)



def test_an_anchor_that_cannot_be_resolved_exactly_is_an_error_not_a_guess():
    """The failure mode this whole design exists to prevent.

    The prior build script clamped a missing occurrence to the last match
    (`hits[min(occ, len(hits) - 1)]`), so an anchor whose word had been cut
    silently moved to a different word and the video was wrong in a way nobody
    could see. Resolution either names the intended word or stops the build.
    """
    timeline = speech(["alpha", "bravo"])

    with pytest.raises(KeyError):
        Anchor(word="charlie").resolve(timeline)

    with pytest.raises(KeyError):
        Anchor(word="alpha", occurrence=2).resolve(timeline)


def test_an_edge_chooses_where_in_the_word_the_position_falls():
    """A word occupies a span, so "at Harbor" is ambiguous until you say where.

    The end matters as much as the start: "let it breathe until after he says
    Harbor" cannot be expressed as an offset from the start, because word
    durations differ and the offset would mean something different for every
    word it was applied to.
    """
    # word_dur=1.0, gap=0.5: "bravo" runs 1.5 -> 2.5.
    timeline = speech(["alpha", "bravo", "charlie"])

    assert Anchor(word="bravo").resolve(timeline) == pytest.approx(1.5)
    assert Anchor(word="bravo", edge="end").resolve(timeline) == pytest.approx(2.5)
    assert Anchor(word="bravo", edge="mid").resolve(timeline) == pytest.approx(2.0)

    # The offset composes with whichever edge was chosen.
    breathing = Anchor(word="bravo", edge="end", offset=0.2)
    assert breathing.resolve(timeline) == pytest.approx(2.7)


def test_the_written_form_parses_to_the_anchor_it_describes():
    """`data-lumiere-start="word:Harbor#2+0.15"` is what an author actually types.

    The grammar is the interface, and it reads left to right as *which word*,
    *where in it*, *shifted by*: word, optional 1-based occurrence, optional
    edge, optional signed offset in seconds.
    """
    assert Anchor.parse("word:Harbor") == Anchor(word="Harbor")
    assert Anchor.parse("word:Harbor#2") == Anchor(word="Harbor", occurrence=2)
    assert Anchor.parse("word:Harbor#2+0.15") == Anchor("Harbor", occurrence=2, offset=0.15)
    assert Anchor.parse("word:Harbor-0.2") == Anchor(word="Harbor", offset=-0.2)

    assert Anchor.parse("word:Harbor.end") == Anchor(word="Harbor", edge="end")
    assert Anchor.parse("word:Harbor.mid") == Anchor(word="Harbor", edge="mid")
    assert Anchor.parse("word:Harbor.end+0.2") == Anchor("Harbor", edge="end", offset=0.2)
    assert Anchor.parse("word:Harbor#2.end+0.15") == Anchor(
        "Harbor", occurrence=2, edge="end", offset=0.15
    )


def test_a_malformed_anchor_stops_the_build_rather_than_being_ignored():
    """A typo must not degrade into "no anchor here".

    Silently ignoring an unparseable anchor would leave the element on whatever
    literal seconds it already carried - which is exactly the hand-typed timing
    the anchor was written to replace.
    """
    for spec in ("Harbor", "word:", "time:12.5", ""):
        with pytest.raises(ValueError):
            Anchor.parse(spec)


def test_the_prefix_chooses_which_kind_of_position_is_meant():
    """One attribute carries both kinds, so the prefix has to disambiguate.

    `word:` asks a question about the recording; `film:` asks one about the
    finished piece. An element writes whichever it means into the same
    `data-lumiere-start`, and the reader must not have to know which elements are
    which.
    """
    assert parse_anchor("word:Harbor#2.end") == Anchor("Harbor", occurrence=2, edge="end")
    assert parse_anchor("film:start") == FilmAnchor("start")
    assert parse_anchor("film:end") == FilmAnchor("end")

    # The film has two edges and no middle: there is nothing to interpolate.
    with pytest.raises(ValueError):
        parse_anchor("film:mid")


def test_a_film_edge_offset_extends_past_the_material():
    """`film:end+2.0` is the breath a close needs.

    The last word ends and the picture holds; no recording can supply that
    air, so it is expressed on the film itself rather than on a word.
    """
    timeline = speech(["alpha", "bravo"])

    tail = parse_anchor("film:end+2.0")
    assert tail.at(timeline) == pytest.approx(timeline.duration + 2.0)
    assert parse_anchor("film:start").at(timeline) == 0.0
