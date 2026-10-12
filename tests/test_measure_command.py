"""`lumiere measure` - the numbers a video reads before deciding what to require.

Synthetic files prove each number from first principles: a tone of known
amplitude has a known loudness and peak, a tone with a known gap has a known
pace.

Skipped without ffmpeg.
"""

from __future__ import annotations

import io
import json
import shutil
import statistics
import wave
from pathlib import Path

import numpy as np
import pytest

from conftest import speech
from lumiere.cli.main import main
from lumiere.core.pace import RATE, syllables, transcript_match

pytestmark = pytest.mark.skipif(
    shutil.which("ffmpeg") is None, reason="ffmpeg not installed"
)



def write_wav(path: Path, pcm: np.ndarray) -> Path:
    with wave.open(str(path), "wb") as out:
        out.setparams((1, 2, RATE, 0, "NONE", "not compressed"))
        out.writeframes(np.round(np.clip(pcm, -1, 1) * 32767).astype("<i2").tobytes())
    return path


def tone(seconds: float, amplitude: float = 0.5) -> np.ndarray:
    t = np.arange(round(seconds * RATE)) / RATE
    return amplitude * np.sin(2 * np.pi * 1000 * t)


def silence(seconds: float) -> np.ndarray:
    return np.zeros(round(seconds * RATE))


def records(capsys) -> list[dict]:
    return [json.loads(line) for line in capsys.readouterr().out.splitlines()]


@pytest.fixture
def spoken(tmp_path: Path, monkeypatch) -> Path:
    """One second of 'speech', half a second of pause, one second more.

    'hello world again' is five dictionary syllables over two seconds of
    sound, so the pace is 2.5 syllables per second by hand.
    """
    monkeypatch.chdir(tmp_path)
    audio = write_wav(tmp_path / "a.wav", np.concatenate([tone(1), silence(0.5), tone(1)]))
    (tmp_path / "a.wav.json").write_text(json.dumps({"text": "hello world again"}))
    return audio


# --- the numbers -----------------------------------------------------------


def test_measure_reports_duration_loudness_and_true_peak(tmp_path, monkeypatch, capsys):
    """A 1 kHz sine at half scale: peak is -6.02 dBFS, and EBU R128 weighting is
    flat at 1 kHz, so its loudness is the sine's -3.01 dB RMS below that."""
    monkeypatch.chdir(tmp_path)
    write_wav(tmp_path / "tone.wav", tone(2.0, amplitude=0.5))

    assert main(["measure", "tone.wav"]) == 0

    [record] = records(capsys)
    assert record["file"] == "tone.wav"
    assert record["duration"] == 2.0
    assert record["true_peak"] == pytest.approx(-6.0, abs=0.15)
    assert record["lufs"] == pytest.approx(-9.0, abs=0.2)


def test_pace_is_syllables_over_the_seconds_that_are_not_quiet(spoken, capsys):
    assert main(["measure", str(spoken)]) == 0

    [record] = records(capsys)
    assert record["pace"] == pytest.approx(5 / 2.0)


def test_a_pause_shorter_than_200ms_still_counts_as_speech(tmp_path, monkeypatch, capsys):
    """Stops and breaths inside a sentence are part of talking; only a real
    pause is taken out of the denominator."""
    monkeypatch.chdir(tmp_path)
    write_wav(tmp_path / "a.wav", np.concatenate([tone(1), silence(0.19), tone(1)]))
    (tmp_path / "a.wav.json").write_text(json.dumps({"text": "hello world again"}))

    assert main(["measure", "a.wav"]) == 0

    [record] = records(capsys)
    assert record["pace"] == pytest.approx(5 / 2.19)


def test_match_compares_the_text_with_the_words_companion(spoken, tmp_path, capsys):
    speech(["hello", "world", "again"]).write(tmp_path / "a.words.json")
    assert main(["measure", str(spoken)]) == 0
    [exact] = records(capsys)

    speech(["hello", "word", "again"]).write(tmp_path / "a.words.json")
    assert main(["measure", str(spoken)]) == 0
    [misheard] = records(capsys)

    assert exact["match"] == 1.0
    assert 0.9 < misheard["match"] < 1.0


def test_match_ignores_case_punctuation_and_word_boundaries():
    assert transcript_match("It merges PRs quickly.", ["it", "merges", "P.R.s", "quickly"]) == 1.0
    assert transcript_match("Lumiere", ["Lumière"]) < 1.0


# --- where the text comes from ----------------------------------------------


def test_without_text_pace_and_match_are_null_and_stderr_says_why(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    write_wav(tmp_path / "mute.wav", tone(1))

    assert main(["measure", "mute.wav"]) == 0

    out, err = capsys.readouterr()
    record = json.loads(out)
    assert record["pace"] is None and record["match"] is None
    assert "mute.wav: no text" in err


def test_text_file_overrides_the_companion_for_a_single_file(spoken, tmp_path, capsys):
    """Six syllables in the same two seconds of sound: the override, not the
    companion, decides the count."""
    (tmp_path / "other.txt").write_text("beautiful hello world\n")

    assert main(["measure", str(spoken), "--text-file", str(tmp_path / "other.txt")]) == 0

    [record] = records(capsys)
    assert record["pace"] == pytest.approx(6 / 2.0)


def test_text_file_with_several_files_is_a_usage_error(spoken, capsys):
    with pytest.raises(SystemExit) as exit_info:
        main(["measure", str(spoken), str(spoken), "--text-file", "t.txt"])

    assert exit_info.value.code == 2
    assert "exactly one audio file" in capsys.readouterr().err


def test_a_missing_audio_file_is_a_usage_error(tmp_path, capsys):
    with pytest.raises(SystemExit) as exit_info:
        main(["measure", str(tmp_path / "absent.wav")])

    assert exit_info.value.code == 2
    assert "absent.wav: no such audio file" in capsys.readouterr().err


def test_a_file_that_is_not_audio_is_bad_input_in_one_line(tmp_path, capsys):
    """The file exists, so the guard before measuring passes; ffmpeg then
    refuses it, and that becomes one readable line and exit 2, not a trace."""
    (tmp_path / "notes.wav").write_text("not audio\n")

    with pytest.raises(SystemExit) as exit_info:
        main(["measure", str(tmp_path / "notes.wav")])

    assert exit_info.value.code == 2
    out, err = capsys.readouterr()
    assert out == ""
    assert "notes.wav: not audio ffmpeg can read" in err
    assert "Traceback" not in err and "CalledProcessError" not in err


def test_a_missing_text_file_is_bad_input_not_a_failed_check(spoken, tmp_path, capsys):
    """Exit 2 is bad input; exit 1 belongs to `verify` for a check that failed."""
    with pytest.raises(SystemExit) as exit_info:
        main(["measure", str(spoken), "--text-file", str(tmp_path / "absent.txt")])

    assert exit_info.value.code == 2
    assert "absent.txt: no such file" in capsys.readouterr().err


def test_a_word_the_dictionary_does_not_know_is_refused_not_guessed(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    write_wav(tmp_path / "a.wav", tone(1))
    (tmp_path / "a.wav.json").write_text(json.dumps({"text": "hello Zxqvbn"}))

    with pytest.raises(SystemExit) as exit_info:
        main(["measure", "a.wav"])

    assert exit_info.value.code == 2
    assert "no syllable count for 'zxqvbn'" in capsys.readouterr().err


def test_a_malformed_syllables_file_is_bad_input(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "counts.json").write_text(json.dumps({"zxqvbn": "two"}))
    write_wav(tmp_path / "a.wav", tone(1))
    (tmp_path / "a.wav.json").write_text(json.dumps({"text": "zxqvbn"}))

    with pytest.raises(SystemExit) as exit_info:
        main(["measure", "a.wav", "--syllables", "counts.json"])

    assert exit_info.value.code == 2
    assert "counts.json: syllable overrides are a JSON object" in capsys.readouterr().err


def test_syllable_overrides_come_only_from_the_file_named_on_the_command_line(tmp_path, monkeypatch, capsys):
    """One second of tone with one made-up word. A `syllables.json` in the
    working directory or beside the audio is not consulted: Lumiere reads
    nothing it was not given. Named with --syllables, the count applies."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / "syllables.json").write_text(json.dumps({"zxqvbn": 2}))
    (tmp_path / "parts").mkdir()
    (tmp_path / "parts" / "syllables.json").write_text(json.dumps({"zxqvbn": 2}))
    (tmp_path / "counts.json").write_text(json.dumps({"zxqvbn": 3}))
    write_wav(tmp_path / "parts" / "a.wav", tone(1))
    (tmp_path / "parts" / "a.wav.json").write_text(json.dumps({"text": "zxqvbn"}))

    with pytest.raises(SystemExit) as exit_info:
        main(["measure", "parts/a.wav"])
    assert exit_info.value.code == 2
    assert "zxqvbn" in capsys.readouterr().err  # an unknown word, with no counts given

    assert main(["measure", "parts/a.wav", "--syllables", "counts.json"]) == 0

    [record] = records(capsys)
    assert record["pace"] == pytest.approx(3.0)


@pytest.mark.parametrize(
    "companion, content, message",
    [
        ("a.wav.json", "[]", "a.wav.json: not a JSON object"),
        ("a.wav.json", "{", "a.wav.json: not JSON"),
        ("a.words.json", "[]", "a.words.json: not a word-timing file"),
        ("a.words.json", '{"schema_version": 1}', "a.words.json: not a word-timing file"),
    ],
)
def test_a_malformed_companion_is_bad_input_in_one_line(spoken, tmp_path, capsys, companion, content, message):
    """The companions are read as `verify`, `join`, and `build` read them:
    a malformed one is exit 2 naming the file, not exit 1 or a KeyError."""
    if companion == "a.words.json":
        speech(["hello", "world", "again"]).write(tmp_path / "a.words.json")
    (tmp_path / companion).write_text(content)

    with pytest.raises(SystemExit) as exit_info:
        main(["measure", "a.wav"])

    assert exit_info.value.code == 2
    out, err = capsys.readouterr()
    assert out == ""
    assert message in err
    assert "Traceback" not in err


def test_syllables_fall_back_to_the_dictionary_and_split_hyphens():
    assert syllables("hello world again", {}) == 5
    assert syllables("well-known", {}) == 2
    assert syllables("PRs", {"prs": 2}) == 2


# --- streams and the summary -----------------------------------------------


def test_a_dash_reads_the_file_list_from_stdin(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    write_wav(tmp_path / "a.wav", tone(1))
    write_wav(tmp_path / "b.wav", tone(2))
    monkeypatch.setattr("sys.stdin", io.StringIO("a.wav\nb.wav\n"))

    assert main(["measure", "-"]) == 0

    assert [r["file"] for r in records(capsys)] == ["a.wav", "b.wav"]


def test_a_dash_with_no_paths_on_stdin_is_a_usage_error(tmp_path, monkeypatch, capsys):
    """Nothing to measure is bad usage, as `join` refuses an empty sequence."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("sys.stdin", io.StringIO("\n"))

    with pytest.raises(SystemExit) as exit_info:
        main(["measure", "-", "--summary"])

    assert exit_info.value.code == 2
    out, err = capsys.readouterr()
    assert out == ""
    assert "no audio files given" in err


def test_summary_adds_median_min_and_max_over_the_files_that_have_a_value(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    write_wav(tmp_path / "a.wav", tone(1))
    write_wav(tmp_path / "b.wav", tone(2))
    write_wav(tmp_path / "c.wav", tone(4))
    (tmp_path / "c.wav.json").write_text(json.dumps({"text": "hello world again"}))

    assert main(["measure", "a.wav", "b.wav", "c.wav", "--summary"]) == 0

    *_, last = records(capsys)
    summary = last["summary"]
    assert summary["files"] == 3
    assert summary["duration"] == {"median": 2.0, "min": 1.0, "max": 4.0}
    assert summary["pace"] == {"median": 1.25, "min": 1.25, "max": 1.25}
    assert summary["match"] is None
