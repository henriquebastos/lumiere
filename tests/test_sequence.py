"""Scenes that own their narration.

A host with `data-lumiere-words` carries the word timings of its own
narration: it starts where the previous such host ends, lasts as long as its
words, and its composition is resolved against those words from zero - the
first `word:x` in the scene is the first in the scene, with nothing to scope.
There is no film-wide timeline; the film is the scenes added up.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from conftest import speech
from lumiere.cli.absorb import absorb
from lumiere.cli.build import build, resolve
from lumiere.cli.check import check
from lumiere.core.composition import read_anchors


def write_project(tmp_path: Path) -> Path:
    # Scene one: "alpha bravo", 1s words, 0.5s apart -> 2.5s, plus a 0.5s pause at the end.
    one = speech(["alpha", "bravo"])
    one = type(one)(entries=one.entries, media="one.wav", duration=one.duration + 0.5)
    # Scene two: "charlie delta echo" -> 4.0s.
    two = speech(["charlie", "delta", "echo"])
    (tmp_path / "narration").mkdir()
    one.write(tmp_path / "narration/one.words.json")
    two.write(tmp_path / "narration/two.words.json")
    (tmp_path / "index.html").write_text(
        '<div id="main" data-composition-id="main" data-lumiere-start="film:start" data-lumiere-end="film:end">\n'
        '  <div class="clip" id="host-one" data-composition-src="scenes/one.html"\n'
        '       data-lumiere-words="narration/one.words.json" data-lumiere-voiceover="Alpha bravo."></div>\n'
        '  <div class="clip" id="host-two" data-composition-src="scenes/two.html"\n'
        '       data-lumiere-words="narration/two.words.json" data-lumiere-voiceover="Charlie delta echo."></div>\n'
        "</div>\n"
    )
    (tmp_path / "scenes").mkdir()
    (tmp_path / "scenes/one.html").write_text(
        '<div id="one" data-composition-id="one">\n'
        '  <audio id="one-voice" src="assets/one.wav" data-lumiere-start="film:start" data-lumiere-end="film:end"></audio>\n'
        '</div>\n'
        '<script>\n'
        'tl.to("#a",{opacity:1},9.999); // @lumiere word:bravo\n'
        'tl.to("#a",{opacity:0},9.999); // @lumiere frame:end-0.250\n'
        '</script>\n'
    )
    (tmp_path / "scenes/two.html").write_text(
        '<div id="two" data-composition-id="two"></div>\n'
        '<script>tl.to("#c",{opacity:1},9.999); // @lumiere word:echo\n</script>\n'
    )
    return tmp_path


def test_hosts_follow_each_other_and_the_film_is_their_sum(tmp_path):
    project = write_project(tmp_path)

    report = build(project)

    index = (project / "index.html").read_text()
    assert 'id="host-one"' in index and 'data-start="0.000" data-duration="3.000"' in index
    assert 'id="host-two"' in index and 'data-start="3.000" data-duration="4.000"' in index
    assert 'id="main" data-composition-id="main" data-lumiere-start="film:start" data-lumiere-end="film:end" data-start="0.000" data-duration="7.000"' in index


def test_each_scene_resolves_against_its_own_words_from_zero(tmp_path):
    project = write_project(tmp_path)

    build(project)

    one = (project / "scenes/one.html").read_text()
    assert 'data-start="0.000" data-duration="3.000"' in one  # the scene's audio spans its narration
    assert 'tl.to("#a",{opacity:1},1.500); // @lumiere word:bravo' in one
    assert 'tl.to("#a",{opacity:0},2.750); // @lumiere frame:end-0.250' in one
    two = (project / "scenes/two.html").read_text()
    assert 'tl.to("#c",{opacity:1},3.000); // @lumiere word:echo' in two  # 3.0 into the scene, not 6.0 into the film


def test_a_built_project_is_at_rest_and_check_is_clean(tmp_path):
    project = write_project(tmp_path)
    build(project)

    assert build(project).patched == ()
    report = check(project)
    assert report.errors == () and report.warnings == ()


def test_a_longer_narration_pushes_the_scenes_after_it(tmp_path):
    """Re-record scene one half a second longer: scene two moves, and no
    cue in either scene changes, because each counts from its own zero."""
    project = write_project(tmp_path)
    build(project)
    one = speech(["alpha", "bravo"])
    type(one)(entries=one.entries, media="one.wav", duration=one.duration + 1.0).write(project / "narration/one.words.json")

    build(project)

    index = (project / "index.html").read_text()
    assert 'id="host-two"' in index and 'data-start="3.500" data-duration="4.000"' in index
    assert 'tl.to("#c",{opacity:1},3.000); // @lumiere word:echo' in (project / "scenes/two.html").read_text()


def test_a_sequenced_host_refuses_an_explicit_anchor():
    html = '<div id="h" data-composition-src="scenes/one.html" data-lumiere-words="narration/one.words.json" data-lumiere-start="film:start"></div>\n'

    with pytest.raises(ValueError, match="timed by its narration"):
        read_anchors(html)


def test_a_drifted_voiceover_is_checked_against_the_scenes_own_words(tmp_path):
    project = write_project(tmp_path)
    index = project / "index.html"
    index.write_text(index.read_text().replace('data-lumiere-voiceover="Charlie delta echo."', 'data-lumiere-voiceover="Charlie x y z."'))
    build(project)

    [warning] = check(project).warnings

    assert warning.startswith("host-two: only 25%")


def test_a_missing_words_file_is_an_error_naming_it(tmp_path):
    project = write_project(tmp_path)
    (project / "narration/two.words.json").unlink()

    [error] = check(project).errors

    assert "two.words.json" in error


def test_absorb_keeps_a_keyframe_moved_inside_a_scene_and_leaves_the_hosts_alone(tmp_path):
    project = write_project(tmp_path)
    build(project)
    two = project / "scenes/two.html"
    two.write_text(two.read_text().replace("3.000); // @lumiere word:echo", "3.200); // @lumiere word:echo"))
    index = project / "index.html"
    index.write_text(index.read_text().replace('data-start="3.000" data-duration="4.000"', 'data-start="3.300" data-duration="4.000"'))

    report = absorb(project)

    assert [f"{p.name}: {c}" for p, c in report.changes] == ["two.html: #c: word:echo -> word:echo+0.200"]
    assert check(project).errors == ("index.html: its seconds are not what the anchors resolve to. Run `lumiere build`.",)
    build(project)
    assert check(project).ok
