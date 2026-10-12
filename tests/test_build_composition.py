"""`lumiere build compositions/intro.html --words intro.words.json`.

One composition resolved alone against its own word timings: the composition
is its own film, starting at zero and lasting as long as its narration. Its
`data-lumiere-start` elements and `// @lumiere` tweens are authored exactly as in a
project; only where the words come from changes. `lumiere build .` keeps the
project behaviour tested in `test_build.py`.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from conftest import speech
from lumiere.cli.build import build_composition
from lumiere.cli.main import main

# so 0.00-0.40, the 0.55-0.95, graph 1.10-1.50, the 1.65-2.05, end 2.20-2.60.
WORDS = ["so", "the", "graph", "the", "end"]

COMPOSITION = (
    '<div id="intro" data-composition-id="intro" data-fps="30">\n'
    '  <div id="title" data-lumiere-start="word:graph" data-lumiere-end="word:end.end">'
    "Graph</div>\n"
    "  <script>\n"
    '    tl.set("#intro",{opacity:1},9.999); // @lumiere frame:start\n'
    '    tl.to("#a",{opacity:1},9.999); // @lumiere word:the#2\n'
    '    tl.to("#b",{opacity:1},9.999); // @lumiere word:graph.end+0.1\n'
    '    tl.to("#c",{opacity:0},9.999); // @lumiere frame:end-0.5\n'
    "  </script>\n"
    "</div>\n"
)

CUE = re.compile(r",(-?\d+(?:\.\d+)?)\);\s*//\s*@lumiere\s+(\S+)")


def cue_times(markup: str) -> dict[str, float]:
    """Every cued position in the markup, by its anchor."""
    return {anchor: float(at) for at, anchor in CUE.findall(markup)}


def element_timing(markup: str, identifier: str) -> tuple[float, float]:
    tag = re.search(rf'<[^>]*\bid="{identifier}"[^>]*>', markup).group(0)
    start = re.search(r'\sdata-start="([^"]+)"', tag).group(1)
    duration = re.search(r'\sdata-duration="([^"]+)"', tag).group(1)
    return float(start), float(duration)


@pytest.fixture
def scene(tmp_path: Path, monkeypatch) -> Path:
    """A project-shaped directory holding one composition and its words."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / "compositions").mkdir()
    (tmp_path / "compositions" / "intro.html").write_text(COMPOSITION)
    speech(WORDS, 0.4, 0.15).write(tmp_path / "intro.words.json")
    return tmp_path


def test_a_composition_resolves_its_cues_against_its_own_word_timings(scene, capsys):
    """The cue times are the words file's times, not the film's: the
    composition starts at zero, `#2` counts inside these words, and
    `frame:end` is where this narration ends (2.6 s, 78 frames at 30 fps)."""
    composition = Path("compositions/intro.html")

    assert main(["build", str(composition), "--words", "intro.words.json"]) == 0

    captured = capsys.readouterr()
    assert captured.out == f"{composition}\n"
    assert captured.err == ""
    built = composition.read_text()
    assert cue_times(built) == pytest.approx({
        "frame:start": 0.0,
        "word:the#2": 1.65,
        "word:graph.end+0.1": 1.6,
        "frame:end-0.5": 2.1,
    }, abs=1e-9)
    assert element_timing(built, "title") == pytest.approx((1.1, 1.5), abs=1e-9)
    # The authored anchors are never consumed.
    assert "// @lumiere word:the#2\n" in built
    assert 'data-lumiere-start="word:graph" data-lumiere-end="word:end.end"' in built


def test_the_same_composition_follows_whichever_words_it_is_given(scene):
    """Re-narrating the scene moves its motion with nothing hand-edited: the
    same markup against slower words resolves to the slower times."""
    composition = scene / "compositions" / "intro.html"
    build_composition(composition, scene / "intro.words.json")
    speech(WORDS, 0.5, 0.25).write(scene / "slower.words.json")

    report = build_composition(composition, scene / "slower.words.json")

    assert report.patched == (composition,)
    built = composition.read_text()
    # so 0-0.5, the 0.75, graph 1.5-2.0, the 2.25, end 3.0-3.5.
    assert cue_times(built) == pytest.approx({
        "frame:start": 0.0,
        "word:the#2": 2.25,
        "word:graph.end+0.1": 2.1,
        "frame:end-0.5": 3.0,
    }, abs=1e-9)
    assert element_timing(built, "title") == pytest.approx((1.5, 2.0), abs=1e-9)


def test_rebuilding_against_the_same_words_writes_nothing(scene):
    composition = scene / "compositions" / "intro.html"
    build_composition(composition, scene / "intro.words.json")

    report = build_composition(composition, scene / "intro.words.json")

    assert report.patched == ()


def test_a_cue_naming_a_word_the_narration_lacks_is_bad_input(scene, capsys):
    """Exit 2 with the composition named, and the file left as authored."""
    composition = scene / "compositions" / "intro.html"
    composition.write_text(COMPOSITION.replace("word:the#2", "word:the#3"))

    with pytest.raises(SystemExit) as exit:
        main(["build", "compositions/intro.html", "--words", "intro.words.json"])

    assert exit.value.code == 2
    error = capsys.readouterr().err
    assert "compositions/intro.html: word:the#3:" in error
    assert composition.read_text() == COMPOSITION.replace("word:the#2", "word:the#3")


@pytest.mark.parametrize(
    ("argv", "message"),
    [
        (["build", "compositions/intro.html"], "give --words"),
        (["build", "compositions/intro.html", "--words", "absent.words.json"],
         "absent.words.json: no such word-timing file"),
        (["build", "compositions/intro.html", "--words", "compositions/intro.html"],
         "compositions/intro.html: not a word-timing file"),
        (["build", ".", "--words", "intro.words.json"],
         "--words goes with a composition, not a project directory"),
        (["build", "absent.html", "--words", "intro.words.json"],
         "absent.html: no such composition"),
    ],
)
def test_build_refuses_bad_composition_arguments_with_exit_2(scene, capsys, argv, message):
    with pytest.raises(SystemExit) as exit:
        main(argv)

    assert exit.value.code == 2
    assert message in capsys.readouterr().err
    assert (scene / "compositions" / "intro.html").read_text() == COMPOSITION


@pytest.mark.parametrize("duration", [None, "2.6", -1.0])
def test_a_words_file_with_a_malformed_duration_is_bad_input(scene, capsys, duration):
    """A duration that is missing, not a number, or negative is a malformed
    words file: exit 2 naming it, not a traceback, and nothing written."""
    (scene / "bad.words.json").write_text(json.dumps(
        {"schema_version": 1, "media": "n.wav", "duration": duration, "entries": []}
    ))

    with pytest.raises(SystemExit) as exit:
        main(["build", "compositions/intro.html", "--words", "bad.words.json"])

    assert exit.value.code == 2
    assert "bad.words.json: not a word-timing file" in capsys.readouterr().err
    assert (scene / "compositions" / "intro.html").read_text() == COMPOSITION


def test_build_of_a_project_directory_is_unchanged(scene, capsys):
    """A directory builds the film from index.html and the words its root names."""
    speech(["alpha", "bravo", "charlie"]).write(scene / "timeline.json")
    (scene / "index.html").write_text(
        '<div id="main" data-composition-id="main" data-lumiere-words="timeline.json">\n'
        '<div id="card" data-lumiere-start="word:charlie">Harbor</div></div>\n'
    )

    assert main(["build", "."]) == 0

    assert capsys.readouterr().out == "patched index.html\n"
    assert element_timing((scene / "index.html").read_text(), "card") == (3.0, 0.0)
