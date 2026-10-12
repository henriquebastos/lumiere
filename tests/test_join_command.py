"""`lumiere join` - parts back into one audio file and one word-timing file.

Synthetic parts prove the arithmetic: a part starts exactly where the
samples and pause before it end, and its words move by that many samples'
worth of seconds.

Skipped without ffmpeg.
"""

from __future__ import annotations

import io
import json
import shutil
import wave
from pathlib import Path

import numpy as np
import pytest

from conftest import speech
from lumiere.cli.main import main
from lumiere.core.join import Part, parse_sequence
from lumiere.core.timeline import Entry, SourceTimeline

pytestmark = pytest.mark.skipif(
    shutil.which("ffmpeg") is None, reason="ffmpeg not installed"
)

RATE = 8000


def write_part(path: Path, samples: np.ndarray, timeline: SourceTimeline, rate: int = RATE) -> Path:
    """A 16-bit mono WAV with its `a.words.json` companion beside it."""
    with wave.open(str(path), "wb") as out:
        out.setparams((1, 2, rate, 0, "NONE", "not compressed"))
        out.writeframes(samples.astype("<i2").tobytes())
    timeline.write(path.with_name(path.stem + ".words.json"))
    return path


def read_wav(path: Path) -> tuple[np.ndarray, int]:
    with wave.open(str(path), "rb") as audio:
        assert (audio.getnchannels(), audio.getsampwidth()) == (1, 2)
        return np.frombuffer(audio.readframes(audio.getnframes()), dtype="<i2"), audio.getframerate()


def ramp(count: int, first: int) -> np.ndarray:
    """Distinct non-zero samples, so a shifted or dropped sample shows."""
    return np.arange(first, first + count, dtype=np.int64).astype("<i2")


@pytest.fixture
def two_parts(tmp_path: Path, monkeypatch) -> tuple[Path, Path]:
    """`a.wav` is 1.0 s (8000 samples) saying 'hello world'; `b.wav` is
    0.5 s saying 'again'."""
    monkeypatch.chdir(tmp_path)
    a = write_part(tmp_path / "a.wav", ramp(8000, 1), speech(["hello", "world"], 0.4, 0.2))
    b = write_part(
        tmp_path / "b.wav",
        ramp(4000, 9000),
        SourceTimeline(
            entries=(Entry("word", "again", 0.1, 0.45, "speaker_0"),),
            media="b.wav", duration=0.5, language="eng",
        ),
    )
    return a, b


# --- the arithmetic ---------------------------------------------------------


def test_join_puts_the_gap_between_parts_and_shifts_the_later_words(two_parts, tmp_path, capsys):
    """--gap 0.32 at 8 kHz is 2560 zero samples between the parts and none
    after the last, so 'again' moves from 0.1 s to 1.0 + 0.32 + 0.1 = 1.42 s."""
    assert main(["join", "a.wav", "b.wav", "--gap", "0.32", "-o", "out.wav", "--words", "out.words.json"]) == 0

    assert capsys.readouterr().out == "out.wav\n"
    samples, rate = read_wav(tmp_path / "out.wav")
    assert rate == RATE
    assert len(samples) == 8000 + 2560 + 4000
    assert np.array_equal(samples[:8000], ramp(8000, 1))
    assert not samples[8000:10560].any()
    assert np.array_equal(samples[10560:], ramp(4000, 9000))

    joined = SourceTimeline.read(tmp_path / "out.words.json")
    assert [(e.kind, e.text, e.start, e.end) for e in joined.entries] == [
        ("word", "hello", 0.0, 0.4),
        ("spacing", " ", 0.4, 0.6),
        ("word", "world", 0.6, 1.0),
        ("word", "again", 1.42, 1.77),
    ]
    assert joined.entries[-1].speaker == "speaker_0"
    assert joined.duration == 1.82
    assert joined.media == "out.wav"


def test_words_default_to_the_companion_beside_the_output(two_parts, tmp_path):
    assert main(["join", "a.wav", "b.wav", "-o", "out.wav"]) == 0

    joined = SourceTimeline.read(tmp_path / "out.words.json")
    assert joined.duration == 1.5
    assert joined.entries[-1].start == 1.1


def test_words_dash_prints_the_timings_instead_of_the_path(two_parts, tmp_path, capsys):
    assert main(["join", "a.wav", "b.wav", "-o", "out.wav", "--words", "-"]) == 0

    out = capsys.readouterr().out
    printed = SourceTimeline.from_json(out)
    assert printed.entries[-1].start == 1.1
    assert (tmp_path / "out.wav").exists()
    assert not (tmp_path / "out.words.json").exists()
    # Every stdout result is one JSON line, as `verify --report -` prints.
    assert out.endswith("\n") and out.count("\n") == 1


def test_the_words_file_on_disk_stays_indented(two_parts, tmp_path):
    assert main(["join", "a.wav", "b.wav", "-o", "out.wav"]) == 0

    written = (tmp_path / "out.words.json").read_text()
    assert written.startswith('{\n  "schema_version": 1,')


def test_a_sequence_file_gives_each_pause_with_paths_relative_to_itself(two_parts, tmp_path, monkeypatch, capsys):
    """Run from another directory: the paths still resolve beside the
    sequence file. The pause after the last part is written too."""
    (tmp_path / "sequence.txt").write_text("a.wav      0.5\n\nb.wav      0.25\n")
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)

    assert main(["join", "-l", str(tmp_path / "sequence.txt"), "-o", "out.wav"]) == 0

    samples, _ = read_wav(elsewhere / "out.wav")
    assert len(samples) == 8000 + 4000 + 4000 + 2000
    assert np.array_equal(samples[12000:16000], ramp(4000, 9000))
    assert not samples[16000:].any()
    joined = SourceTimeline.read(elsewhere / "out.words.json")
    assert joined.entries[-1].start == 1.6
    assert joined.duration == 2.25


def test_a_dash_reads_the_sequence_from_stdin_relative_to_the_working_directory(two_parts, tmp_path, monkeypatch):
    monkeypatch.setattr("sys.stdin", io.StringIO("b.wav 0.1\na.wav\n"))

    assert main(["join", "-l", "-", "-o", "out.wav"]) == 0

    samples, _ = read_wav(tmp_path / "out.wav")
    assert len(samples) == 4000 + 800 + 8000
    assert np.array_equal(samples[4800:], ramp(8000, 1))
    joined = SourceTimeline.read(tmp_path / "out.words.json")
    assert [(e.text, e.start) for _, e in joined.words] == [
        ("again", 0.1), ("hello", 0.6), ("world", 1.2),
    ]


def test_parse_sequence_reads_paths_with_spaces_and_an_optional_pause(tmp_path):
    assert parse_sequence(["my part.wav 0.32", "last.wav"], tmp_path) == [
        Part(tmp_path / "my part.wav", 0.32),
        Part(tmp_path / "last.wav", 0.0),
    ]


# --- bad input exits 2 --------------------------------------------------------


@pytest.mark.parametrize(
    "arguments, message",
    [
        (["join", "-o", "out.wav"], "either as arguments or as -l SEQUENCE"),
        (["join", "a.wav", "-l", "sequence.txt", "-o", "out.wav"], "either as arguments or as -l SEQUENCE"),
        (["join", "-l", "sequence.txt", "--gap", "0.2", "-o", "out.wav"], "--gap goes with parts given as arguments"),
        (["join", "a.wav", "b.wav", "--gap", "-1", "-o", "out.wav"], "seconds cannot be negative"),
        (["join", "a.wav", "b.wav", "-o", "out.mp3"], "name the output .wav"),
        (["join", "a.wav", "absent.wav", "-o", "out.wav"], "absent.wav: no such audio file"),
        (["join", "-l", "absent.txt", "-o", "out.wav"], "absent.txt: no such sequence file"),
    ],
)
def test_bad_usage_exits_2_before_writing(two_parts, tmp_path, capsys, arguments, message):
    (tmp_path / "sequence.txt").write_text("a.wav 0.1\n")

    with pytest.raises(SystemExit) as exit_info:
        main(arguments)

    assert exit_info.value.code == 2
    assert message in capsys.readouterr().err
    assert not (tmp_path / "out.wav").exists()


def test_a_negative_pause_in_the_sequence_is_bad_input(two_parts, tmp_path, capsys):
    (tmp_path / "sequence.txt").write_text("a.wav 0.1\nb.wav -0.2\n")

    with pytest.raises(SystemExit) as exit_info:
        main(["join", "-l", "sequence.txt", "-o", "out.wav"])

    assert exit_info.value.code == 2
    assert "line 2: the pause after 'b.wav' is not a duration" in capsys.readouterr().err


def test_a_part_without_word_timings_is_refused_not_transcribed(two_parts, tmp_path, capsys):
    (tmp_path / "b.words.json").unlink()

    with pytest.raises(SystemExit) as exit_info:
        main(["join", "a.wav", "b.wav", "-o", "out.wav"])

    assert exit_info.value.code == 2
    assert "b.words.json: no word timings for b.wav" in capsys.readouterr().err
    assert not (tmp_path / "out.wav").exists()


def test_a_part_that_is_not_audio_is_bad_input_in_one_line(two_parts, tmp_path, capsys):
    (tmp_path / "notes.wav").write_text("not audio\n")
    speech(["hello"]).write(tmp_path / "notes.words.json")

    with pytest.raises(SystemExit) as exit_info:
        main(["join", "a.wav", "notes.wav", "-o", "out.wav"])

    assert exit_info.value.code == 2
    out, err = capsys.readouterr()
    assert out == ""
    assert "notes.wav: not audio ffmpeg can read" in err
    assert "Traceback" not in err and "CalledProcessError" not in err
    assert not (tmp_path / "out.wav").exists()


@pytest.mark.parametrize("content", ["[]", "null", "{", '{"schema_version": 1}'])
def test_a_words_file_that_is_not_a_timeline_is_bad_input_in_one_line(two_parts, tmp_path, capsys, content):
    (tmp_path / "b.words.json").write_text(content)

    with pytest.raises(SystemExit) as exit_info:
        main(["join", "a.wav", "b.wav", "-o", "out.wav"])

    assert exit_info.value.code == 2
    out, err = capsys.readouterr()
    assert out == ""
    assert "b.words.json: not a word-timing file" in err
    assert "Traceback" not in err
    assert not (tmp_path / "out.wav").exists()


@pytest.mark.parametrize(
    "destination",
    [
        ["-o", "missing/out.wav"],
        ["-o", "out.wav", "--words", "missing/out.words.json"],
    ],
)
def test_a_destination_in_a_missing_directory_is_bad_input_before_writing(two_parts, tmp_path, capsys, destination):
    with pytest.raises(SystemExit) as exit_info:
        main(["join", "a.wav", "b.wav", *destination])

    assert exit_info.value.code == 2
    out, err = capsys.readouterr()
    assert out == ""
    assert "no such directory missing" in err
    assert not (tmp_path / "out.wav").exists()
    assert not (tmp_path / "missing").exists()
