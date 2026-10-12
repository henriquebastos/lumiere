"""`lumiere absorb` - a timing edit made in Studio becomes the anchor's offset.

Studio writes seconds; the build derives them. Without absorb, dragging a
keyframe in Studio is undone by the next build. With it, the drag is read as
"this much earlier or later than the word", which is what the editor meant.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from conftest import speech
from lumiere.cli.absorb import absorb
from lumiere.cli.build import build, resolve
from lumiere.cli.check import check
from lumiere.cli.main import main
from lumiere.core.absorb import absorb_frame, shift_spec

# "alpha bravo charlie delta echo", 1s each, 0.5s apart: word i starts at 1.5*i.
TIMELINE = speech(["alpha", "bravo", "charlie", "delta", "echo"])


@pytest.mark.parametrize("spec, by, expected", [
    ("word:with#1+0.150", 0.48, "word:with+0.630"),
    ("word:harbor", -0.1, "word:harbor-0.100"),
    ("word:Harbor#2.end+0.15", -0.15, "word:Harbor#2.end"),
    ("film:end-0.5", 0.5, "film:end"),
    ("frame:start+0.001", 0.3, "frame:start+0.301"),
    ("frame:end-0.593", -0.2, "frame:end-0.793"),
])
def test_an_anchor_shifted_keeps_its_word_and_moves_its_offset(spec, by, expected):
    assert shift_spec(spec, by) == expected


def test_a_moved_position_becomes_offset_on_its_cue():
    disk = (
        'tl.to("#a",{opacity:1},1.980); // @lumiere word:bravo#1\n'
        'tl.to("#b",{opacity:1},3.000); // @lumiere word:charlie\n'
    )
    derived = (
        'tl.to("#a",{opacity:1},1.500); // @lumiere word:bravo#1\n'
        'tl.to("#b",{opacity:1},3.000); // @lumiere word:charlie\n'
    )

    text, changes = absorb_frame(disk, derived)

    assert text == (
        'tl.to("#a",{opacity:1},1.980); // @lumiere word:bravo+0.480\n'
        'tl.to("#b",{opacity:1},3.000); // @lumiere word:charlie\n'
    )
    assert [str(c) for c in changes] == ["#a: word:bravo#1 -> word:bravo+0.480"]


def test_cues_that_do_not_line_up_are_refused():
    with pytest.raises(ValueError, match="do not line up"):
        absorb_frame('tl.to("#a",{},1); // @lumiere word:bravo\n', 'tl.to("#a",{},1); // @lumiere word:charlie\n')


def write_project(tmp_path: Path) -> Path:
    TIMELINE.write(tmp_path / "timeline.json")
    (tmp_path / "index.html").write_text(
        '<div id="stage" data-composition-id="main" data-lumiere-words="timeline.json" data-lumiere-start="film:start" data-lumiere-end="film:end">\n'
        '  <div class="clip" id="f1" data-composition-src="frames/f1.html"\n'
        '       data-lumiere-start="word:bravo" data-lumiere-end="word:echo.end"></div>\n'
        '  <div class="clip" id="f2" data-composition-src="frames/f2.html"\n'
        '       data-lumiere-voiceover="delta echo"></div>\n'
        "</div>\n"
    )
    (tmp_path / "frames").mkdir()
    (tmp_path / "frames/f1.html").write_text(
        '<script>\n'
        'tl.to("#a",{opacity:1},9.999); // @lumiere word:charlie\n'
        'tl.to("#b",{opacity:0},9.999); // @lumiere frame:end-0.500\n'
        '</script>\n'
    )
    (tmp_path / "frames/f2.html").write_text('<script>tl.to("#c",{opacity:1},9.999); // @lumiere word:echo\n</script>\n')
    build(tmp_path)
    return tmp_path


def test_a_keyframe_moved_in_a_frame_is_kept_and_the_build_then_agrees(tmp_path):
    project = write_project(tmp_path)
    frame = project / "frames/f1.html"
    # f1 starts at bravo (1.5s); charlie is at 3.0s -> position 1.500. Studio drags it to 1.800.
    assert 'tl.to("#a",{opacity:1},1.500); // @lumiere word:charlie' in frame.read_text()
    frame.write_text(frame.read_text().replace("1.500); // @lumiere word:charlie", "1.800); // @lumiere word:charlie"))
    assert not check(project).ok  # stale until absorbed

    report = absorb(project)

    assert [f"{p.name}: {c}" for p, c in report.changes] == ["f1.html: #a: word:charlie -> word:charlie+0.300"]
    assert 'tl.to("#a",{opacity:1},1.800); // @lumiere word:charlie+0.300' in frame.read_text()
    assert check(project).ok
    assert build(project).patched == ()


def test_a_clip_dragged_in_index_moves_its_anchors_and_its_frames_cues_follow(tmp_path):
    """The numbers on disk are what the editor saw. Dragging the clip half a
    second later carried its motion along (the frame's own positions did not
    change), so each cue inside gets half a second more offset from its
    word, and an exit cued to the frame's end stays at the new end."""
    project = write_project(tmp_path)
    index = project / "index.html"
    # f1: start 1.500, end 7.000 (echo.end) -> duration 5.500. Studio drags the clip to 2.000, same end.
    assert 'data-start="1.500" data-duration="5.500"' in index.read_text()
    index.write_text(index.read_text().replace('data-start="1.500" data-duration="5.500"', 'data-start="2.000" data-duration="5.000"'))

    report = absorb(project)

    assert [f"{p.name}: {c}" for p, c in report.changes] == [
        "index.html: f1: data-lumiere-start=word:bravo -> data-lumiere-start=word:bravo+0.500",
        "f1.html: #a: word:charlie -> word:charlie+0.500",
        "f1.html: #b: frame:end-0.500 -> frame:end",
    ]
    assert 'data-lumiere-start="word:bravo+0.500" data-lumiere-end="word:echo.end"' in index.read_text()
    assert check(project).ok
    assert build(project).patched == ()


def test_a_clip_timed_by_its_voiceover_alone_gets_an_explicit_anchor_when_moved(tmp_path):
    project = write_project(tmp_path)
    index = project / "index.html"
    # f2: delta at 4.5 -> film:end 7.0. Studio makes it start at 4.2 and end at 7.0.
    assert 'data-lumiere-voiceover="delta echo" data-start="4.500" data-duration="2.500"' in index.read_text()
    index.write_text(index.read_text().replace('data-start="4.500" data-duration="2.500"', 'data-start="4.200" data-duration="2.800"'))

    absorb(project)

    assert 'data-lumiere-voiceover="delta echo" data-start="4.200" data-duration="2.800" data-lumiere-start="word:delta-0.300"' in index.read_text()
    assert check(project).ok
    assert build(project).patched == ()


def test_nothing_to_absorb_says_so(tmp_path, capsys):
    project = write_project(tmp_path)

    assert main(["absorb", str(project)]) == 0

    assert capsys.readouterr().out == "nothing to absorb: the seconds already are what the anchors say\n"
