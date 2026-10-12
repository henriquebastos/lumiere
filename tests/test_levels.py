"""One rule at every level.

An element with `data-lumiere-words` owns a narration for everything below
it; a host without one resolves against the nearest owner above, scoped to
its span; child words win. Three levels - main, chapters, scenes - with the
narration attached at different places, all through the same walk.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from conftest import speech
from lumiere.cli.build import build
from lumiere.cli.check import check


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


def project(tmp_path: Path) -> Path:
    """
    main (owns words/main: "alpha bravo charlie delta echo", 1s words, 0.5 apart)
    ├── chapter-1  host anchored into main: word:alpha .. word:charlie.end     (1.5s .. 4.0s)
    │   ├── scene-a  host anchored into main (inherited): word:bravo            -> relative to chapter-1
    │   └── scene-b  host with its own words/b: "x y" (2.5s), placed first in the chapter's sequence
    └── chapter-2  host with its own words/ch2: "one two three" (4.0s)
        └── scene-c  host anchored into ch2: word:two .. word:three.end
    """
    speech(["alpha", "bravo", "charlie", "delta", "echo"]).write(tmp_path / "words/main.json")
    speech(["x", "y"]).write(tmp_path / "words/b.json")
    speech(["one", "two", "three"]).write(tmp_path / "words/ch2.json")
    write(tmp_path / "index.html",
        '<div id="main" data-composition-id="main" data-lumiere-words="words/main.json"\n'
        '     data-lumiere-start="film:start" data-lumiere-end="film:end">\n'
        '  <audio id="voice" src="assets/main.wav" data-lumiere-start="film:start" data-lumiere-end="film:end"></audio>\n'
        '  <div class="clip" id="chapter-1" data-composition-src="chapters/one.html"\n'
        '       data-lumiere-start="word:alpha" data-lumiere-end="word:charlie.end"></div>\n'
        '  <div class="clip" id="chapter-2" data-composition-src="chapters/two.html"\n'
        '       data-lumiere-words="words/ch2.json"></div>\n'
        "</div>\n")
    write(tmp_path / "chapters/one.html",
        '<div id="one" data-composition-id="one" data-lumiere-start="frame:start" data-lumiere-end="frame:end">\n'
        '  <div class="clip" id="scene-b" data-composition-src="scenes/b.html" data-lumiere-words="words/b.json"></div>\n'
        '  <div class="clip" id="scene-a" data-composition-src="scenes/a.html" data-lumiere-start="word:bravo" data-lumiere-end="word:charlie.end"></div>\n'
        "</div>\n"
        '<script>tl.to("#t",{opacity:1},9.999); // @lumiere word:charlie\n</script>\n')
    write(tmp_path / "chapters/two.html",
        '<div id="two" data-composition-id="two">\n'
        '  <div class="clip" id="scene-c" data-composition-src="scenes/c.html" data-lumiere-start="word:two" data-lumiere-end="word:three.end"></div>\n'
        "</div>\n"
        '<script>tl.to("#t",{opacity:1},9.999); // @lumiere word:three\n</script>\n')
    write(tmp_path / "scenes/a.html", '<div id="a" data-composition-id="a"></div>\n<script>tl.to("#t",{opacity:1},9.999); // @lumiere word:charlie\n</script>\n')
    write(tmp_path / "scenes/b.html", '<div id="b" data-composition-id="b"></div>\n<script>tl.to("#t",{opacity:1},9.999); // @lumiere word:y\n</script>\n')
    write(tmp_path / "scenes/c.html", '<div id="c" data-composition-id="c"></div>\n<script>tl.to("#t",{opacity:1},9.999); // @lumiere word:three\n</script>\n')
    return tmp_path


def test_the_root_owns_its_narration_by_saying_so(tmp_path):
    p = project(tmp_path)

    build(p)

    index = (p / "index.html").read_text()
    assert 'id="main"' in index and 'data-start="0.000" data-duration="7.000"' in index
    assert 'id="voice"' in index and 'data-start="0.000" data-duration="7.000"' in index
    assert 'id="chapter-1"' in index and 'data-start="0.000" data-duration="4.000"' in index  # alpha .. charlie.end


def test_a_host_inside_a_chapter_resolves_against_the_inherited_narration_relative_to_the_chapter(tmp_path):
    p = project(tmp_path)

    build(p)

    one = (p / "chapters/one.html").read_text()
    # scene-a: bravo (1.5) .. charlie.end (4.0) in main's words; the chapter starts at 0.0.
    assert 'id="scene-a"' in one and 'data-start="1.500" data-duration="2.500"' in one
    # the chapter's own cue: charlie at 3.0 in main's words, 3.0 into the chapter.
    assert 'tl.to("#t",{opacity:1},3.000); // @lumiere word:charlie' in one
    # scene-a's cue: the same word, now relative to scene-a's start (1.5).
    assert 'tl.to("#t",{opacity:1},1.500); // @lumiere word:charlie' in (p / "scenes/a.html").read_text()


def test_a_scene_with_its_own_words_inside_a_chapter_counts_from_zero(tmp_path):
    p = project(tmp_path)

    build(p)

    one = (p / "chapters/one.html").read_text()
    assert 'id="scene-b"' in one and 'data-start="0.000" data-duration="2.500"' in one  # placed first, lasts its words
    assert 'tl.to("#t",{opacity:1},1.500); // @lumiere word:y' in (p / "scenes/b.html").read_text()


def test_a_chapter_with_its_own_words_follows_the_anchored_hosts_before_it_and_its_scenes_use_them(tmp_path):
    p = project(tmp_path)

    build(p)

    index = (p / "index.html").read_text()
    assert 'id="chapter-2"' in index and 'data-start="0.000" data-duration="4.000"' in index  # first in main's sequence
    two = (p / "chapters/two.html").read_text()
    assert 'id="scene-c"' in two and 'data-start="1.500" data-duration="2.500"' in two  # two .. three.end in ch2's words
    assert 'tl.to("#t",{opacity:1},3.000); // @lumiere word:three' in two
    assert 'tl.to("#t",{opacity:1},1.500); // @lumiere word:three' in (p / "scenes/c.html").read_text()


def test_the_whole_tree_is_at_rest_after_one_build_and_check_is_clean(tmp_path):
    p = project(tmp_path)
    build(p)

    assert build(p).patched == ()
    report = check(p)
    assert report.errors == () and report.warnings == ()


def test_a_missing_word_three_levels_down_names_the_file(tmp_path):
    p = project(tmp_path)
    (p / "scenes/c.html").write_text('<div id="c" data-composition-id="c"></div>\n<script>tl.to("#t",{opacity:1},9.999); // @lumiere word:zulu\n</script>\n')

    with pytest.raises(ValueError, match=r"^scenes/c\.html: .*zulu"):
        build(p)


def test_a_chapter_that_inherits_its_narration_spans_its_host(tmp_path):
    p = project(tmp_path)

    build(p)

    one = (p / "chapters/one.html").read_text()
    assert 'id="one" data-composition-id="one" data-lumiere-start="frame:start" data-lumiere-end="frame:end" data-start="0.000" data-duration="4.000"' in one
