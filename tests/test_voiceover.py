"""`data-lumiere-voiceover` - a frame says what is spoken over it, and its
anchors follow.

Most scene hosts in a narrated film start on the first word of their sentence
and end where the next one begins. Writing that as explicit anchors repeats
the script, and loses it: the sentence itself was only kept in a storyboard
that nothing read. With the voiceover on the host, the start and end default
from it and the sentence is where the agent and the producer look for it.
"""

from __future__ import annotations

import pytest

from conftest import speech
from lumiere.cli.build import build
from lumiere.cli.check import check
from lumiere.core.anchor import Anchor, FilmAnchor
from lumiere.core.composition import read_anchors
from lumiere.core.voiceover import voiceover_anchors, voiceover_coverage

# "alpha bravo charlie delta echo", 1s each, 0.5s apart: word i starts at 1.5*i.
TIMELINE = speech(["alpha", "bravo", "charlie", "delta", "echo"])


def test_each_voiceover_starts_on_its_first_spoken_word_and_ends_on_the_next():
    anchors = voiceover_anchors(["Alpha bravo.", "Charlie delta", "Echo!"], TIMELINE)

    assert anchors == [
        (Anchor("alpha", 1), Anchor("charlie", 1)),
        (Anchor("charlie", 1), Anchor("echo", 1)),
        (Anchor("echo", 1), FilmAnchor("end")),
    ]


def test_a_word_the_speaker_changed_falls_forward_to_the_next_one_that_matched():
    """The voiceover is the script. 'Lumiere' was said as 'Lumière':
    the frame still starts where its sentence did, on the next matched word."""
    anchors = voiceover_anchors(["alpha bravo", "chaarlie delta echo"], TIMELINE)

    assert anchors[1][0] == Anchor("delta", 1)


def test_a_repeated_word_is_named_by_its_occurrence_from_the_top():
    timeline = speech(["go", "stop", "go", "stop"])

    anchors = voiceover_anchors(["go stop", "go stop"], timeline)

    assert anchors[1][0] == Anchor("go", 2)
    assert anchors[1][0].resolve(timeline) == 3.0


def test_a_voiceover_no_word_of_which_was_spoken_is_refused_with_its_number():
    with pytest.raises(ValueError, match="voiceover 2 .* data-lumiere-start"):
        voiceover_anchors(["alpha", "zulu yankee"], TIMELINE)


def test_an_empty_voiceover_is_refused():
    with pytest.raises(ValueError, match="voiceover 1 is empty"):
        voiceover_anchors(["  ", "alpha"], TIMELINE)


def test_the_markup_defaults_missing_anchors_from_the_voiceover_and_keeps_explicit_ones():
    html = (
        '<div id="one" data-lumiere-voiceover="alpha bravo"></div>\n'
        '<div id="two" data-lumiere-voiceover="charlie delta" '
        'data-lumiere-start="word:charlie-0.1"></div>\n'
        '<div id="three" data-lumiere-voiceover="echo" '
        'data-lumiere-end="film:end+2"></div>\n'
    )

    one, two, three = read_anchors(html, TIMELINE)

    assert (one.start, one.end) == (Anchor("alpha", 1), Anchor("charlie", 1))
    assert (two.start, two.end) == (Anchor("charlie", 1, offset=-0.1), Anchor("echo", 1))
    assert (three.start, three.end) == (Anchor("echo", 1), FilmAnchor("end", 2.0))


def test_defaulting_needs_the_timeline_but_explicit_anchors_do_not():
    explicit = (
        '<div id="one" data-lumiere-voiceover="alpha" '
        'data-lumiere-start="word:alpha" data-lumiere-end="word:bravo"></div>\n'
    )
    [one] = read_anchors(explicit)
    assert one.start == Anchor("alpha", 1)

    with pytest.raises(ValueError, match="needs the timeline"):
        read_anchors('<div id="one" data-lumiere-voiceover="alpha"></div>\n')


def test_build_writes_the_hyperframes_seconds_from_the_voiceovers(tmp_path):
    TIMELINE.write(tmp_path / "timeline.json")
    (tmp_path / "index.html").write_text(
        '<div id="narration" data-composition-id="narration" data-lumiere-words="timeline.json"></div>\n'
        '<div id="one" data-lumiere-voiceover="alpha bravo"></div>\n'
        '<div id="two" data-lumiere-voiceover="charlie delta echo"></div>\n'
    )

    build(tmp_path)

    built = (tmp_path / "index.html").read_text()
    assert '<div id="one" data-lumiere-voiceover="alpha bravo" data-start="0.000" data-duration="3.000">' in built
    assert '<div id="two" data-lumiere-voiceover="charlie delta echo" data-start="3.000" data-duration="4.000">' in built


def test_check_counts_a_voiceover_as_the_elements_anchor(tmp_path):
    TIMELINE.write(tmp_path / "timeline.json")
    (tmp_path / "index.html").write_text(
        '<div id="narration" data-composition-id="narration" data-lumiere-words="timeline.json" data-start="0.000" data-duration="7.000"></div>\n'
        '<div id="one" data-lumiere-voiceover="alpha" data-start="0.000" data-duration="7.000"></div>\n'
    )

    report = check(tmp_path)

    assert report.ok and report.warnings == ()


def test_coverage_is_the_share_of_each_voiceovers_words_that_were_spoken():
    assert voiceover_coverage(["alpha bravo", "charlie zulu", "yankee"], TIMELINE) == [1.0, 0.5, 0.0]


def test_check_warns_about_a_voiceover_that_is_not_what_was_said(tmp_path):
    """The narration changed and the host's sentence did not: the host still
    builds (its first word is there) but the text on it is stale."""
    TIMELINE.write(tmp_path / "timeline.json")
    (tmp_path / "index.html").write_text(
        '<div id="narration" data-composition-id="narration" data-lumiere-words="timeline.json" data-start="0.000" data-duration="7.000"></div>\n'
        '<div id="one" data-lumiere-voiceover="alpha bravo" data-start="0.000" data-duration="3.000"></div>\n'
        '<div id="two" data-lumiere-voiceover="charlie x y z" data-start="3.000" data-duration="4.000"></div>\n'
    )

    report = check(tmp_path)

    assert report.errors == ()
    [warning] = report.warnings
    assert warning.startswith("two: only 25%")


def test_the_voiceover_is_read_as_text_not_as_html():
    """Attribute values are HTML: `Let&#x27;s go` on the host is the sentence
    "Let's go", and that is what has to be found in the recording."""
    timeline = speech(["let's", "go"])
    html = '<div id="one" data-lumiere-voiceover="Let&#x27;s go &quot;now&quot;"></div>\n'

    [one] = read_anchors(html, timeline)

    assert one.start == Anchor("lets", 1)
    assert voiceover_coverage(["Let's go"], timeline) == [1.0]
