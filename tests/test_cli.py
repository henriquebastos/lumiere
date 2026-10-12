"""The `lumiere` command itself.

Thin by design: it parses arguments, calls the same functions the other tests
drive, and turns their answers into an exit code. The exit code is the part
that matters - it is what a build script or CI reads.
"""

from __future__ import annotations

from conftest import speech
from lumiere.cli.main import main


ROOT = '<div id="narration" data-composition-id="narration" data-lumiere-words="timeline.json" data-start="0.000" data-duration="4.000"></div>\n'


def write_project(tmp_path, markup: str):
    speech(["alpha", "bravo", "charlie"]).write(tmp_path / "timeline.json")
    # The root names its narration; nothing is read that the markup does not name.
    (tmp_path / "index.html").write_text(ROOT + markup)
    return tmp_path


def test_check_warns_about_a_hand_typed_second_and_still_succeeds(tmp_path, capsys):
    """A typed second is valid HyperFrames. Lumiere says it will not move with
    the audio, and leaves the exit code alone."""
    project = write_project(
        tmp_path,
        '<div data-hf-id="hf-stray" data-start="4.200" data-duration="1.000">x</div>',
    )

    assert main(["check", str(project)]) == 0
    assert capsys.readouterr().out.startswith("warning: <element with no id>")


def test_check_fails_the_command_when_the_seconds_are_not_what_the_anchors_say(tmp_path, capsys):
    project = write_project(
        tmp_path,
        '<div id="card" data-hf-id="hf-card" data-lumiere-start="word:bravo" '
        'data-start="9.000" data-duration="0.000">x</div>',
    )

    assert main(["check", str(project)]) == 1
    assert capsys.readouterr().out.startswith("error: index.html")


def test_check_succeeds_when_every_timed_element_is_anchored_and_built(tmp_path):
    project = write_project(
        tmp_path,
        '<div id="card" data-hf-id="hf-card" data-lumiere-start="word:bravo" '
        'data-start="1.500" data-duration="0.000">x</div>',
    )

    assert main(["check", str(project)]) == 0


def test_adopt_acts_on_a_project_directory_like_every_other_command(tmp_path, capsys):
    """Adoption is not creation, so it takes a path like the rest of them.

    An earlier `new` took a slug and scaffolded, which put Lumiere in the
    business of choosing which kind of video the project was - a choice that
    belongs to whoever picks the HyperFrames workflow.
    """
    (tmp_path / "hyperframes.json").write_text("{}\n")
    (tmp_path / "index.html").write_text("<div id='stage'></div>")

    (tmp_path / "AGENTS.md").write_text("# Project\n")

    assert main(["adopt", str(tmp_path)]) == 0
    assert "Lumiere" in (tmp_path / "AGENTS.md").read_text()


def test_a_refusal_reads_as_a_message_not_a_traceback(tmp_path, capsys):
    """These commands are run by people who do not read Python.

    Every guard in the system - an anchor whose word is gone, a stale film -
    reports by raising. Letting that reach the terminal as a stack trace
    turns a clear explanation into something that looks like the tool broke.
    """
    (tmp_path / "index.html").write_text('<div id="card" data-lumiere-start="word:zulu">x</div>\n')

    exit_code = main(["build", str(tmp_path)])

    assert exit_code == 1
    output = capsys.readouterr()
    assert "Traceback" not in output.err
    assert "card" in output.err


def test_words_prints_tokens_the_way_the_resolver_counts_them(tmp_path):
    """The vocabulary an author anchors against is the resolver's, not the
    script's: case-insensitive, punctuation stripped, globally numbered."""
    from conftest import speech
    from lumiere.cli.words import words

    speech(["And", "then", "and,", "again."]).write(tmp_path / "a.words.json")

    lines = list(words(tmp_path / "a.words.json"))

    assert lines[0].startswith("And#1")
    assert lines[2].startswith("and,#2")
    assert lines[3].startswith("again.#1")
