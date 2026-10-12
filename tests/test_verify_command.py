"""`lumiere verify` - `measure`'s numbers held against what a video requires.

Synthetic files prove each check from first principles: a tone of known
amplitude has a known loudness and peak, a tone with a known gap has a known
pace, and one changed sample changes the file's hash.

Skipped without ffmpeg.
"""

from __future__ import annotations

import hashlib
import io
import json
import shutil
import wave
from pathlib import Path

import numpy as np
import pytest

from conftest import speech
from lumiere.cli.main import main
from lumiere.core.pace import RATE
from lumiere.core.timeline import Entry, SourceTimeline

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


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def records(out: str) -> list[dict]:
    return [json.loads(line) for line in out.splitlines()]


def checks(record: dict) -> dict[str, dict]:
    return {check["check"]: check for check in record["checks"]}


def failed(record: dict) -> set[str]:
    return {check["check"] for check in record["checks"] if not check["passed"]}


@pytest.fixture
def spoken(tmp_path: Path, monkeypatch) -> Path:
    """'hello world again' - five syllables over two seconds of half-scale
    1 kHz tone with a 0.5 s pause: pace 2.5, peak -6 dBTP.
    Its companion records the text and the file's hash; its words companion
    says exactly the text."""
    monkeypatch.chdir(tmp_path)
    audio = write_wav(tmp_path / "a.wav", np.concatenate([tone(1), silence(0.5), tone(1)]))
    (tmp_path / "a.wav.json").write_text(
        json.dumps({"text": "hello world again", "audio_sha256": sha256(audio)})
    )
    speech(["hello", "world", "again"]).write(tmp_path / "a.words.json")
    return audio


# --- each check passes and fails on its number ---------------------------------


def test_every_check_passes_on_audio_that_meets_it(spoken, capsys):
    assert main([
        "verify", "a.wav", "--pace", "2.4:2.6", "--loudness", "-10:-8",
        "--peak", "-5", "--match", "exact",
    ]) == 0

    out, err = capsys.readouterr()
    [record] = records(out)
    assert err == ""
    assert record["file"] == "a.wav" and record["passed"] is True
    measured = checks(record)
    assert set(measured) == {"hash", "loudness", "true_peak", "pace", "match"}
    assert measured["pace"]["value"] == pytest.approx(2.5)
    # A steady half-scale tone is -9 LUFS; the 400 ms gating blocks that
    # straddle the pause are quieter and pull the integrated value down.
    assert measured["loudness"]["value"] == pytest.approx(-9.7, abs=0.2)
    assert measured["true_peak"]["value"] == pytest.approx(-6.0, abs=0.15)
    assert measured["match"]["value"] == 1.0
    assert measured["hash"]["value"] == measured["hash"]["required"] == sha256(spoken)


@pytest.mark.parametrize(
    "option, check, message",
    [
        (["--pace", "5.0:5.6"], "pace", "a.wav: pace 2.500 syllables/s is outside 5:5.6"),
        (["--loudness", "-24:-21.7"], "loudness", "LUFS is outside -24:-21.7"),
        (["--peak", "-7"], "true_peak", "dBTP is above -7"),
    ],
)
def test_a_number_outside_its_requirement_fails_with_exit_1(spoken, capsys, option, check, message):
    assert main(["verify", "a.wav", *option]) == 1

    out, err = capsys.readouterr()
    [record] = records(out)
    assert record["passed"] is False
    assert failed(record) == {check}
    assert message in err
    assert len(err.splitlines()) == 1


def test_match_takes_exact_or_a_ratio(spoken, tmp_path, capsys):
    """'word' for 'world' is one letter short of the text: below exact, above 0.9."""
    speech(["hello", "word", "again"]).write(tmp_path / "a.words.json")

    assert main(["verify", "a.wav", "--match", "exact"]) == 1
    out, err = capsys.readouterr()
    ratio = checks(records(out)[0])["match"]["value"]
    assert 0.9 < ratio < 1.0
    assert f"a.wav: match {ratio:.4f} is not exact" in err

    assert main(["verify", "a.wav", "--match", "0.9"]) == 0


def test_words_option_replaces_the_words_companion_for_one_file(spoken, tmp_path, capsys):
    speech(["goodbye"]).write(tmp_path / "other.words.json")

    assert main(["verify", "a.wav", "--match", "exact", "--words", "other.words.json"]) == 1
    assert main(["verify", "a.wav", "--match", "exact"]) == 0


def test_text_file_replaces_the_companion_text_for_one_file(spoken, tmp_path, capsys):
    """Six syllables in the same two seconds of sound: pace 3.0, not 2.5."""
    (tmp_path / "other.txt").write_text("beautiful hello world\n")

    assert main(["verify", "a.wav", "--pace", "2.9:3.1", "--text-file", "other.txt"]) == 0
    assert checks(records(capsys.readouterr().out)[0])["pace"]["value"] == pytest.approx(3.0)


# --- the recorded hash ------------------------------------------------------------


def test_one_changed_sample_fails_the_recorded_hash(spoken, tmp_path, capsys):
    recorded = sha256(spoken)
    with wave.open(str(spoken)) as audio:
        samples = np.frombuffer(audio.readframes(audio.getnframes()), dtype="<i2").copy()
    samples[RATE // 2] += 1
    with wave.open(str(spoken), "wb") as out:
        out.setparams((1, 2, RATE, 0, "NONE", "not compressed"))
        out.writeframes(samples.tobytes())

    assert main(["verify", "a.wav"]) == 1

    out, err = capsys.readouterr()
    [record] = records(out)
    assert failed(record) == {"hash"}
    assert checks(record)["hash"]["required"] == recorded
    assert checks(record)["hash"]["value"] == sha256(spoken) != recorded
    assert f"is not the audio_sha256 {recorded} recorded in a.wav.json" in err


def test_without_a_recorded_hash_there_is_no_hash_check(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    write_wav(tmp_path / "a.wav", tone(1))

    assert main(["verify", "a.wav"]) == 0

    assert records(capsys.readouterr().out) == [{"file": "a.wav", "checks": [], "passed": True}]


# --- a check that cannot be made fails ---------------------------------------------


def test_pace_without_text_fails_rather_than_passes(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    write_wav(tmp_path / "a.wav", tone(1))

    assert main(["verify", "a.wav", "--pace", "0:100"]) == 1

    out, err = capsys.readouterr()
    pace = checks(records(out)[0])["pace"]
    assert pace["passed"] is False and pace["value"] is None
    assert "a.wav: pace: no text - give --text-file or a 'text' in a.wav.json" in err


def test_match_without_word_timings_fails_rather_than_passes(spoken, tmp_path, capsys):
    (tmp_path / "a.words.json").unlink()

    assert main(["verify", "a.wav", "--match", "0"]) == 1

    out, err = capsys.readouterr()
    assert checks(records(out)[0])["match"]["value"] is None
    assert "a.wav: match: no word timings - give --words or a.words.json" in err


# --- every file, streams, and the report -------------------------------------------


def test_every_file_is_checked_before_exiting_1(spoken, tmp_path, monkeypatch, capsys):
    """The first file fails; the second is still checked and reported. The
    list comes from stdin."""
    write_wav(tmp_path / "loud.wav", tone(1, amplitude=0.9))
    write_wav(tmp_path / "quiet.wav", tone(1, amplitude=0.1))
    monkeypatch.setattr("sys.stdin", io.StringIO("loud.wav\nquiet.wav\n"))

    assert main(["verify", "-", "--peak", "-6"]) == 1

    out, err = capsys.readouterr()
    loud, quiet = records(out)
    assert (loud["file"], loud["passed"]) == ("loud.wav", False)
    assert (quiet["file"], quiet["passed"]) == ("quiet.wav", True)
    assert checks(quiet)["true_peak"]["value"] == pytest.approx(-20.0, abs=0.15)
    assert err.splitlines() == [line for line in err.splitlines() if line.startswith("loud.wav: ")]
    assert len(err.splitlines()) == 1


def test_a_dash_with_no_paths_on_stdin_is_a_usage_error(spoken, monkeypatch, capsys):
    """Nothing checked is not everything passing: exit 2, as `join` refuses
    an empty sequence, never exit 0."""
    monkeypatch.setattr("sys.stdin", io.StringIO(""))

    with pytest.raises(SystemExit) as exit_info:
        main(["verify", "-", "--peak", "-1", "--report", "-"])

    assert exit_info.value.code == 2
    out, err = capsys.readouterr()
    assert out == ""
    assert "no audio files given" in err


def test_report_writes_every_files_checks_to_one_json_file(spoken, tmp_path, capsys):
    write_wav(tmp_path / "b.wav", tone(1))

    assert main(["verify", "a.wav", "b.wav", "--pace", "2.4:2.6", "--report", "report.json"]) == 1

    out, _ = capsys.readouterr()
    report = json.loads((tmp_path / "report.json").read_text())
    assert report["passed"] is False
    assert report["files"] == records(out)
    assert [record["passed"] for record in report["files"]] == [True, False]


def test_report_to_stdout_keeps_stdout_json_lines(spoken, tmp_path, capsys):
    write_wav(tmp_path / "b.wav", tone(1))

    assert main(["verify", "a.wav", "b.wav", "--pace", "2.4:2.6", "--report", "-"]) == 1

    out, _ = capsys.readouterr()
    *files, report = records(out)
    assert [record["passed"] for record in files] == [True, False]
    assert report == {"files": files, "passed": False}


# --- bad input exits 2 --------------------------------------------------------------


@pytest.mark.parametrize(
    "arguments, message",
    [
        (["verify", "a.wav", "--pace", "5.6:5.0"], "the low end is above the high end"),
        (["verify", "a.wav", "--loudness", "-24"], "is not a range like 5.0:5.6"),
        (["verify", "a.wav", "--peak", "loud"], "is not a number of dBTP"),
        (["verify", "a.wav", "--match", "close"], "is not a number of match ratio"),
        (["verify", "a.wav", "--match", "1.5"], "a ratio from 0 to 1"),
        (["verify", "a.wav", "a.wav", "--text-file", "t.txt"], "--text-file goes with exactly one audio file"),
        (["verify", "a.wav", "a.wav", "--words", "a.words.json"], "--words goes with exactly one audio file"),
        (["verify", "a.wav", "--words", "absent.json", "--match", "0.9"], "absent.json: no such file"),
        (["verify", "absent.wav"], "absent.wav: no such file"),
        (["verify", "a.wav", "--report", "missing/r.json"], "no such directory missing"),
    ],
)
def test_bad_usage_exits_2(spoken, capsys, arguments, message):
    with pytest.raises(SystemExit) as exit_info:
        main(arguments)

    assert exit_info.value.code == 2
    out, err = capsys.readouterr()
    assert out == ""
    assert message in err


def test_a_file_that_is_not_audio_is_bad_input_in_one_line(tmp_path, monkeypatch, capsys):
    """Even with no check that decodes audio: a text file never passes verify."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / "notes.wav").write_text("not audio\n")

    with pytest.raises(SystemExit) as exit_info:
        main(["verify", "notes.wav"])

    assert exit_info.value.code == 2
    out, err = capsys.readouterr()
    assert out == ""
    assert "notes.wav: not audio ffmpeg can read" in err
    assert "Traceback" not in err and "CalledProcessError" not in err


@pytest.mark.parametrize(
    "companion, content, message",
    [
        ("a.wav.json", "[]", "a.wav.json: not a JSON object"),
        ("a.wav.json", "{", "a.wav.json: not JSON"),
        ("a.wav.json", '{"audio_sha256": 7}', "audio_sha256 is not a hex digest"),
        ("a.words.json", "null", "a.words.json: not a word-timing file"),
    ],
)
def test_a_malformed_companion_is_bad_input(spoken, tmp_path, capsys, companion, content, message):
    (tmp_path / companion).write_text(content)

    with pytest.raises(SystemExit) as exit_info:
        main(["verify", "a.wav", "--match", "exact"])

    assert exit_info.value.code == 2
    assert message in capsys.readouterr().err
