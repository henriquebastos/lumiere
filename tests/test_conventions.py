"""The conventions every audio primitive shares.

A video's scripts pipe `measure`, `verify`, and `join` together, so the
primitives must agree on what `-` means on each side, how a range is spelled,
and what fails before any work starts. These tests pin those agreements down
before any primitive exists to depend on them.
"""

from __future__ import annotations

import argparse
import io
from pathlib import Path

import pytest

from lumiere.cli.conventions import (
    EXIT_CHECK_FAILED,
    EXIT_OK,
    EXIT_USAGE,
    Span,
    lufs,
    opened,
    pace_target,
    read_lines,
    read_text,
    recipe_path,
    seconds,
    span,
    words_path,
    write_json_line,
)


def primitive_parser() -> argparse.ArgumentParser:
    """The argument shapes a primitive like `verify` will declare."""
    parser = argparse.ArgumentParser(prog="lumiere verify")
    parser.add_argument("audio", type=Path, nargs="+")
    parser.add_argument("--pace", type=span)
    parser.add_argument("--loudness", type=span)
    parser.add_argument("--peak", type=lufs)
    parser.add_argument("--gap", type=seconds)
    parser.add_argument("-o", type=Path)
    return parser


# --- type= converters ------------------------------------------------------


def test_a_range_parses_into_a_span_with_both_ends():
    assert span("5.0:5.6") == Span(5.0, 5.6)
    assert 5.4 in Span(5.0, 5.6)
    assert 5.6 in Span(5.0, 5.6)
    assert 5.7 not in Span(5.0, 5.6)


def test_a_negative_range_parses_without_an_equals_sign():
    """LUFS ranges start with a minus sign. Python 3.14 argparse no longer
    takes `-24:-21.7` for an option name, so `--loudness -24:-21.7` works
    the way the plan writes it."""
    args = primitive_parser().parse_args(["a.wav", "--loudness", "-24:-21.7"])

    assert args.loudness == Span(-24.0, -21.7)
    assert -22.85 in args.loudness


@pytest.mark.parametrize("bad", ["5.0", "5.0:", ":5.6", "a:b", "5.0-5.6", "nan:1"])
def test_a_malformed_range_is_rejected_by_the_converter(bad):
    with pytest.raises(argparse.ArgumentTypeError):
        span(bad)


def test_an_inverted_range_is_rejected():
    with pytest.raises(argparse.ArgumentTypeError, match="low end is above"):
        span("5.6:5.0")


def test_a_bad_range_exits_2_through_the_parser(capsys):
    """Bad usage is argparse's exit code, not a check failure's."""
    with pytest.raises(SystemExit) as exit_info:
        primitive_parser().parse_args(["a.wav", "--pace", "fast"])

    assert exit_info.value.code == EXIT_USAGE
    assert "not a range like 5.0:5.6" in capsys.readouterr().err


def test_seconds_must_be_a_non_negative_number():
    assert seconds("0.32") == 0.32
    assert seconds("0") == 0.0
    with pytest.raises(argparse.ArgumentTypeError):
        seconds("-0.5")
    with pytest.raises(argparse.ArgumentTypeError):
        seconds("soon")


def test_a_pace_target_is_a_bare_number_or_a_range_and_positive():
    """`adjust --pace 5.4` always moves; `--pace 5.2:5.6` moves only a pace
    outside the range. A bare number is a range of zero width."""
    assert pace_target("5.4") == Span(5.4, 5.4)
    assert pace_target("5.2:5.6") == Span(5.2, 5.6)
    for bad in ("0", "-5.4", "0:5.6", "fast", "5.6:5.2"):
        with pytest.raises(argparse.ArgumentTypeError):
            pace_target(bad)


def test_lufs_is_a_finite_number_and_may_be_negative():
    assert lufs("-22.85") == -22.85
    with pytest.raises(argparse.ArgumentTypeError):
        lufs("inf")
    with pytest.raises(argparse.ArgumentTypeError):
        lufs("quiet")


def test_parsing_opens_no_file(tmp_path):
    """`type=` only shapes values. A missing input or an output in a missing
    directory is a problem for the command, discovered after parsing - the
    reason `argparse.FileType` is not used."""
    missing_in = tmp_path / "absent.wav"
    missing_out = tmp_path / "no-such-dir" / "out.wav"

    args = primitive_parser().parse_args([str(missing_in), "-o", str(missing_out)])

    assert args.audio == [missing_in]
    assert args.o == missing_out
    assert not missing_in.exists()
    assert not missing_out.parent.exists()


def test_a_dash_parses_as_a_path_on_both_sides():
    args = primitive_parser().parse_args(["-", "-o", "-"])

    assert args.audio == [Path("-")]
    assert args.o == Path("-")


# --- streams ---------------------------------------------------------------


def test_read_lines_treats_a_dash_as_stdin(monkeypatch):
    """`ls *.wav | lumiere measure -`: the path list arrives on stdin, with
    blank lines and surrounding whitespace ignored."""
    monkeypatch.setattr("sys.stdin", io.StringIO("a.wav\n\n  b.wav  \n"))

    assert list(read_lines([Path("-")])) == ["a.wav", "b.wav"]


def test_read_lines_concatenates_named_files_in_order(tmp_path):
    first = tmp_path / "first.txt"
    second = tmp_path / "second.txt"
    first.write_text("01.wav 0.50\n")
    second.write_text("\n02.wav 0.20\n")

    assert list(read_lines([first, second])) == ["01.wav 0.50", "02.wav 0.20"]


def test_read_lines_with_no_files_reads_nothing_not_argv():
    """fileinput falls back to sys.argv when given no files - the one place
    its defaults would be wrong for a command that already parsed them."""
    assert list(read_lines([])) == []


def test_read_text_keeps_the_text_whole(tmp_path, monkeypatch):
    """`speak -` wants the script as written, line breaks included."""
    script = tmp_path / "a.txt"
    script.write_text("First line.\n\nSecond paragraph.\n")
    monkeypatch.setattr("sys.stdin", io.StringIO("from stdin\n"))

    assert read_text(script) == "First line.\n\nSecond paragraph.\n"
    assert read_text("-") == "from stdin\n"


def test_opened_treats_a_dash_as_stdout_and_leaves_it_open(capsys):
    with opened(Path("-")) as out:
        out.write("one\n")
    with opened("-") as out:
        out.write("two\n")

    assert capsys.readouterr().out == "one\ntwo\n"


def test_opened_writes_a_named_file(tmp_path):
    target = tmp_path / "out.words.json"

    with opened(target) as out:
        out.write("{}\n")

    assert target.read_text() == "{}\n"


def test_a_path_list_can_flow_from_stdin_to_stdout(monkeypatch, capsys):
    """`-` on both sides at once, as in `… | lumiere verify - --report -`."""
    monkeypatch.setattr("sys.stdin", io.StringIO("a.wav\nb.wav\n"))

    with opened("-") as out:
        for path in read_lines(["-"]):
            write_json_line({"file": path, "passed": True}, out)

    assert capsys.readouterr().out == (
        '{"file": "a.wav", "passed": true}\n{"file": "b.wav", "passed": true}\n'
    )


def test_json_lines_are_one_record_per_line_and_unescaped(capsys):
    write_json_line({"text": "Café", "lufs": -22.85})
    write_json_line({"n": 2})

    out = capsys.readouterr().out
    assert out == '{"text": "Café", "lufs": -22.85}\n{"n": 2}\n'


# --- exit codes and companions ---------------------------------------------


def test_exit_codes_distinguish_success_a_failed_check_and_bad_usage():
    """1 is what `verify` returns after checking every file; 2 is what
    argparse returns before doing anything. A build script reads the
    difference."""
    assert (EXIT_OK, EXIT_CHECK_FAILED, EXIT_USAGE) == (0, 1, 2)


def test_companions_sit_beside_the_audio():
    audio = Path("narration/01-intro.wav")

    assert recipe_path(audio) == Path("narration/01-intro.wav.json")
    assert words_path(audio) == Path("narration/01-intro.words.json")


def test_the_recipe_keeps_the_audio_suffix_and_the_words_replace_it():
    """`a.mp3.json` says which file it describes; `a.words.json` is the same
    name whether the audio is a WAV or an MP3, so a join can find timings
    for either."""
    audio = Path("candidates/01-v2.mp3")

    assert recipe_path(audio) == Path("candidates/01-v2.mp3.json")
    assert words_path(audio) == Path("candidates/01-v2.words.json")
