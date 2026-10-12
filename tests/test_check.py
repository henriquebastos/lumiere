"""`lumiere check` - is the project's timing what the audio says it is?

HyperFrames is the source of truth, and a composition with typed seconds is a
valid one. So a typed second is a warning: it renders today and will not move
with the audio. An error is something Lumiere owns and cannot honour - an
anchor whose word is gone, or seconds on disk that disagree with the anchors.
"""

from __future__ import annotations

from conftest import speech
from lumiere.cli.build import build
from lumiere.cli.check import check


ROOT = '<div id="narration" data-composition-id="narration" data-lumiere-words="timeline.json" data-start="0.000" data-duration="4.000"></div>\n'


def write_project(tmp_path, markup: str):
    speech(["alpha", "bravo", "charlie"]).write(tmp_path / "timeline.json")
    # The root names its narration; nothing is read that the markup does not name.
    (tmp_path / "index.html").write_text(ROOT + markup)
    return tmp_path


# --- warnings: seconds Lumiere does not own -----------------------------------


def test_a_timed_element_with_no_anchor_is_a_warning_not_an_error(tmp_path):
    project = write_project(
        tmp_path,
        '<div id="stray" data-start="4.200" data-duration="1.000">x</div>',
    )

    report = check(project)

    assert report.ok
    assert any("stray" in warning for warning in report.warnings)


def test_the_composition_root_is_warned_about_like_everything_else(tmp_path):
    """Its duration is the film's length, so every re-recording moves it. It
    needs a different *kind* of anchor, `film:start` / `film:end`, not a pass."""
    project = write_project(
        tmp_path,
        '<div id="stage" data-composition-id="main" '
        'data-start="0" data-duration="145.100"></div>',
    )

    [warning] = check(project).warnings
    assert "stage" in warning
    assert "film:" in warning


def test_a_clip_that_references_a_frame_is_warned_about_too(tmp_path):
    """`data-composition-id` marks the root *and* every sub-composition clip;
    exempting the attribute once excused every frame in a real project."""
    project = write_project(
        tmp_path,
        '<div class="clip" data-composition-id="03-harbor-named" '
        'data-composition-src="compositions/frames/03-harbor-named.html" '
        'data-start="16.160" data-duration="4.740"></div>',
    )

    assert any("03-harbor-named" in warning for warning in check(project).warnings)


def test_a_hand_written_position_inside_a_frame_is_a_warning(tmp_path):
    """The frame files hold most of the motion. A position of zero is exempt:
    it means "when this frame starts", which is derived by definition."""
    project = write_project(
        tmp_path,
        '<div id="stage" data-composition-id="main" data-lumiere-words="timeline.json" data-lumiere-start="film:start" data-lumiere-end="film:end">\n'
        '  <div class="clip" data-composition-id="f1"\n'
        '       data-composition-src="frames/f1.html"\n'
        '       data-lumiere-start="word:bravo" data-lumiere-end="word:charlie.end"></div>\n'
        "</div>\n",
    )
    frame = project / "frames" / "f1.html"
    frame.parent.mkdir()
    frame.write_text(
        '<script>\n'
        '  tl.fromTo("#bg",{x:0},{x:60,duration:9},0);\n'
        '  tl.fromTo("#t1",{opacity:0},{opacity:1,duration:0.5},4.147);\n'
        '  tl.to("#t2",{opacity:0,duration:0.5},9.999);  // @lumiere word:charlie\n'
        "</script>\n"
    )
    build(project)

    report = check(project)

    assert report.ok, report.errors
    assert any("4.147" in warning for warning in report.warnings)
    assert not any("1.500" in warning for warning in report.warnings)  # cued, now resolved
    assert not any(",0)" in warning for warning in report.warnings)  # the frame's start


def test_the_report_names_an_element_by_whatever_handle_it_actually_has(tmp_path):
    project = write_project(
        tmp_path,
        '<div class="clip" data-composition-id="03-harbor-named" '
        'data-composition-src="compositions/frames/03-harbor-named.html" '
        'data-start="16.160" data-duration="4.740"></div>',
    )

    [warning] = check(project).warnings

    assert "03-harbor-named" in warning


# --- errors: anchors Lumiere cannot honour ------------------------------------


def test_a_built_project_is_clean(tmp_path):
    project = write_project(
        tmp_path,
        '<div id="card" data-lumiere-start="word:bravo" data-lumiere-end="word:charlie">x</div>\n',
    )
    build(project)

    assert check(project) == check(project)
    assert check(project).errors == () and check(project).warnings == ()


def test_seconds_that_disagree_with_the_anchors_are_an_error(tmp_path):
    """The film is stale: the narration changed, or someone typed over a
    derived number. Either way `lumiere build` has to run."""
    project = write_project(
        tmp_path,
        '<div id="card" data-lumiere-start="word:bravo" data-start="9.000" data-duration="0.000">x</div>\n',
    )

    [error] = check(project).errors

    assert "index.html" in error and "lumiere build" in error


def test_an_anchor_whose_word_is_not_in_the_recording_is_an_error(tmp_path):
    project = write_project(
        tmp_path,
        '<div id="card" data-lumiere-start="word:zulu">x</div>\n',
    )

    [error] = check(project).errors

    assert "zulu" in error



def test_a_frame_cue_whose_word_is_gone_names_the_frame(tmp_path):
    project = write_project(
        tmp_path,
        '<div class="clip" id="f1" data-composition-src="frames/f1.html"\n'
        '     data-lumiere-start="word:alpha" data-lumiere-end="word:charlie"\n'
        '     data-start="0.000" data-duration="3.000"></div>\n',
    )
    frame = project / "frames" / "f1.html"
    frame.parent.mkdir()
    frame.write_text('<script>tl.to("#t",{opacity:1},1.0);  // @lumiere word:zulu</script>\n')

    [error] = check(project).errors

    assert error.startswith("frames/f1.html:") and "zulu" in error


def test_a_word_anchor_with_no_narration_above_it_is_an_error(tmp_path):
    (tmp_path / "index.html").write_text('<div id="card" data-lumiere-start="word:bravo">x</div>\n')

    [error] = check(tmp_path).errors

    assert error.startswith("card:") and "data-lumiere-words" in error
