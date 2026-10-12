"""`lumiere build` - the command a producer actually runs.

This is the one place the pieces meet a filesystem: a recorded timeline, an
edit, and a composition full of anchors go in; a composition carrying resolved
seconds comes out. The tests drive it through the same entry point the CLI
uses, so they exercise the real path rather than a convenient shortcut.
"""

from __future__ import annotations

import pytest

from conftest import speech
from lumiere.cli.build import build


ROOT = '<div id="narration" data-composition-id="narration" data-lumiere-words="timeline.json" data-start="0.000" data-duration="7.000"></div>\n'


def write_project(tmp_path, markup: str):
    """A project directory with a recorded timeline and one composition."""
    timeline = speech(["alpha", "bravo", "charlie", "delta", "echo"])
    timeline.write(tmp_path / "timeline.json")
    # The root names its narration; nothing is read that the markup does not name.
    (tmp_path / "index.html").write_text(ROOT + markup)
    return tmp_path


def test_build_resolves_every_anchor_in_the_composition(tmp_path):
    project = write_project(
        tmp_path,
        '<div id="card" data-lumiere-start="word:charlie" '
        'data-lumiere-end="word:echo">Harbor</div>\n',
    )

    report = build(project)

    patched = (project / "index.html").read_text()
    assert 'data-start="3.000"' in patched
    assert 'data-duration="3.000"' in patched
    assert report.patched == (project / "index.html",)




def test_build_places_the_motion_inside_every_frame_it_references(tmp_path):
    """A frame's cues resolve against that frame's own resolved start.

    The clip in `index.html` says where the frame begins; the frame says what
    happens inside it. Neither knows a second until the build derives both from
    the same narration.
    """
    project = write_project(
        tmp_path,
        '<div id="stage" data-composition-id="main" data-fps="30" data-lumiere-words="timeline.json"\n'
        '     data-lumiere-start="film:start" data-lumiere-end="film:end">\n'
        '  <div class="clip" data-composition-id="f1"\n'
        '       data-composition-src="frames/f1.html"\n'
        '       data-lumiere-start="word:bravo" data-lumiere-end="word:echo"></div>\n'
        "</div>\n",
    )
    frame = project / "frames" / "f1.html"
    frame.parent.mkdir()
    frame.write_text(
        '<script>\n'
        '  tl.fromTo("#t1",{opacity:0},{opacity:1,duration:0.5},9.999);'
        "  // @lumiere word:charlie\n"
        "</script>\n"
    )

    build(project)

    # The clip opens on "bravo" (1.5s); "charlie" is at 3.0s, so 1.5s in.
    assert ",1.500);" in frame.read_text()


def test_a_longer_narration_moves_every_element_with_nothing_hand_edited(tmp_path):
    """The claim this project is built on, end to end.

    The narration is re-recorded with a word more and the composition is
    rebuilt. Nobody touches the markup: the anchors are the same words they
    always were, and only the derived seconds change. If this test ever needs
    the HTML edited to pass, the editing model has failed.
    """
    markup = (
        '<div id="card" data-lumiere-start="word:charlie" '
        'data-lumiere-end="word:echo">Harbor</div>\n'
    )
    project = write_project(tmp_path, markup)
    build(project)
    assert 'data-start="3.000"' in (project / "index.html").read_text()

    speech(["alpha", "bravo", "um", "charlie", "delta", "echo"]).write(project / "timeline.json")
    build(project)

    rebuilt = (project / "index.html").read_text()
    assert 'data-start="4.500"' in rebuilt  # later by exactly the new word
    assert 'data-duration="3.000"' in rebuilt
    assert 'data-lumiere-start="word:charlie"' in rebuilt  # the anchor never changed


def test_a_cue_whose_word_is_gone_names_the_frame_that_has_to_change(tmp_path):
    """Knowing the word is not enough to act on: the producer needs back
    which frame's motion depended on it."""
    project = write_project(
        tmp_path,
        '<div id="stage" data-composition-id="main" data-fps="30" data-lumiere-words="timeline.json"\n'
        '     data-lumiere-start="film:start" data-lumiere-end="film:end">\n'
        '  <div class="clip" data-composition-id="f1"\n'
        '       data-composition-src="frames/f1.html"\n'
        '       data-lumiere-start="word:alpha" data-lumiere-end="word:echo"></div>\n'
        "</div>\n",
    )
    frame = project / "frames" / "f1.html"
    frame.parent.mkdir()
    frame.write_text('<script>tl.to("#t",{opacity:1},1.0);  // @lumiere word:zulu</script>\n')

    with pytest.raises(ValueError, match=r"frames/f1\.html.*zulu"):
        build(project)
