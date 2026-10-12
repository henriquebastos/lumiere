"""`lumiere adjust` - tempo, trim, fade, and gain, each recorded in the companion.

Synthetic files prove each step from first principles: a tone with a known
gap has a known pace, so the tempo it needs is known; silence around a tone
has known frame boundaries, so the trim is known to the sample; a constant
signal shows the fade's shape.

Skipped without ffmpeg.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import wave
from pathlib import Path

import numpy as np
import pytest

from lumiere.adapters.audio import loudness
from lumiere.cli.main import main
from lumiere.core.pace import RATE

pytestmark = pytest.mark.skipif(
    shutil.which("ffmpeg") is None, reason="ffmpeg not installed"
)

FRAME = RATE // 100


def write_wav(path: Path, pcm: np.ndarray) -> Path:
    with wave.open(str(path), "wb") as out:
        out.setparams((1, 2, RATE, 0, "NONE", "not compressed"))
        out.writeframes(np.round(np.clip(pcm, -1, 1) * 32767).astype("<i2").tobytes())
    return path


def read_wav(path: Path) -> np.ndarray:
    with wave.open(str(path), "rb") as audio:
        assert (audio.getframerate(), audio.getnchannels(), audio.getsampwidth()) == (RATE, 1, 2)
        return np.frombuffer(audio.readframes(audio.getnframes()), dtype="<i2")


def tone(seconds: float, amplitude: float = 0.5) -> np.ndarray:
    t = np.arange(round(seconds * RATE)) / RATE
    return amplitude * np.sin(2 * np.pi * 1000 * t)


def silence(seconds: float) -> np.ndarray:
    return np.zeros(round(seconds * RATE))


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def steps(path: Path) -> dict[str, dict]:
    recipe = json.loads(path.with_name(path.name + ".json").read_text())
    return {step["step"]: step for step in recipe["adjustments"]}


@pytest.fixture
def spoken(tmp_path: Path, monkeypatch) -> Path:
    """'hello world again': five syllables over two seconds of half-scale tone
    with a 0.5 s pause, so its pace is 2.5 syllables per second by hand."""
    monkeypatch.chdir(tmp_path)
    audio = write_wav(tmp_path / "a.wav", np.concatenate([tone(1), silence(0.5), tone(1)]))
    (tmp_path / "a.wav.json").write_text(json.dumps({"text": "hello world again"}))
    return audio


# --- tempo -------------------------------------------------------------------


def test_a_bare_pace_retempos_to_it_and_records_why(spoken, capsys):
    """2.5 -> 2.6 syllables/s is tempo 1.04: 2.5 s of audio becomes 2.5/1.04 s."""
    assert main(["adjust", "a.wav", "-o", "b.wav", "--pace", "2.6"]) == 0

    out, err = capsys.readouterr()
    assert (out, err) == ("b.wav\n", "")
    tempo = steps(Path("b.wav"))["tempo"]
    assert tempo["pace"] == 2.6
    assert tempo["measured_pace"] == pytest.approx(2.5)
    assert tempo["tempo"] == pytest.approx(1.04)
    assert len(read_wav(Path("b.wav"))) / RATE == pytest.approx(2.5 / 1.04, abs=0.005)


def test_a_pace_inside_the_span_is_left_alone_even_off_its_middle(spoken, capsys):
    """2.4:2.8 has the same middle, 2.6, as the bare target above, but 2.5 is
    inside it, so the tempo stays 1 and every sample stays."""
    assert main(["adjust", "a.wav", "-o", "b.wav", "--pace", "2.4:2.8"]) == 0

    tempo = steps(Path("b.wav"))["tempo"]
    assert (tempo["pace"], tempo["tempo"]) == ("2.4:2.8", 1)
    before, after = read_wav(spoken).astype(int), read_wav(Path("b.wav")).astype(int)
    assert len(after) == len(before) == round(2.5 * RATE)
    # Decoded as x/32768 and written as x*32767.
    assert np.max(np.abs(after - before)) <= 1


def test_a_pace_outside_the_span_moves_to_its_middle(spoken, capsys):
    assert main(["adjust", "a.wav", "-o", "b.wav", "--pace", "2.8:3.0"]) == 0

    assert steps(Path("b.wav"))["tempo"]["tempo"] == pytest.approx(2.9 / 2.5)


def test_a_tempo_outside_the_bounds_is_refused_with_exit_1_and_nothing_written(spoken, capsys):
    """3.2 / 2.5 = 1.28, past the 1.25 a voice survives."""
    assert main(["adjust", "a.wav", "-o", "b.wav", "--pace", "3.2", "--loudness", "-20"]) == 1

    out, err = capsys.readouterr()
    assert out == ""
    assert err == (
        "a.wav: pace 2.500 syllables/s needs tempo 1.280, outside 0.85-1.25; "
        "regenerate rather than stretch\n"
    )
    assert not Path("b.wav").exists() and not Path("b.wav.json").exists()


def test_pace_without_text_is_bad_usage(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    write_wav(tmp_path / "a.wav", tone(1))

    with pytest.raises(SystemExit) as exit_info:
        main(["adjust", "a.wav", "-o", "b.wav", "--pace", "5.4"])

    assert exit_info.value.code == 2
    assert "--pace needs the spoken text" in capsys.readouterr().err
    assert not Path("b.wav").exists()


@pytest.mark.parametrize("text", ["", "... !?"])
def test_pace_with_text_of_no_syllables_is_bad_input(tmp_path, monkeypatch, capsys, text):
    """A second of tone is speech, but empty text gives it no syllables:
    a pace of 0, which no tempo can fix."""
    monkeypatch.chdir(tmp_path)
    write_wav(tmp_path / "a.wav", tone(1))
    (tmp_path / "a.wav.json").write_text(json.dumps({"text": text}))

    with pytest.raises(SystemExit) as exit_info:
        main(["adjust", "a.wav", "-o", "b.wav", "--pace", "5.4"])

    assert exit_info.value.code == 2
    assert "--pace needs spoken text with syllables" in capsys.readouterr().err
    assert not Path("b.wav").exists() and not Path("b.wav.json").exists()


def test_text_file_supplies_the_pace_text_and_becomes_the_output_text(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    write_wav(tmp_path / "a.wav", np.concatenate([tone(1), silence(0.5), tone(1)]))
    (tmp_path / "a.txt").write_text("hello world again")

    assert main(["adjust", "a.wav", "-o", "b.wav", "--pace", "2.6", "--text-file", "a.txt"]) == 0

    recipe = json.loads(Path("b.wav.json").read_text())
    assert recipe["text"] == "hello world again"
    assert recipe["adjustments"][0]["measured_pace"] == pytest.approx(2.5)


@pytest.mark.parametrize("bad", ["fast", "0", "-5", "5.6:5.2"])
def test_a_bad_pace_exits_2_at_parse_time(spoken, capsys, bad):
    with pytest.raises(SystemExit) as exit_info:
        main(["adjust", "a.wav", "-o", "b.wav", f"--pace={bad}"])

    assert exit_info.value.code == 2
    assert not Path("b.wav").exists()


# --- trim and fade -------------------------------------------------------------


def test_trim_keeps_the_audible_frames_and_six_before_seven_after(tmp_path, monkeypatch, capsys):
    """One second of tone between seconds of silence: frames 100-199 are
    audible, so samples from frame 94 to frame 206 are kept - 1.12 s."""
    monkeypatch.chdir(tmp_path)
    write_wav(tmp_path / "a.wav", np.concatenate([silence(1), tone(1), silence(1)]))

    assert main(["adjust", "a.wav", "-o", "b.wav", "--trim"]) == 0

    trim = steps(Path("b.wav"))["trim"]
    assert (trim["start"], trim["end"]) == (94 * FRAME / RATE, 206 * FRAME / RATE)
    assert len(read_wav(Path("b.wav"))) == (206 - 94) * FRAME


def test_fade_ramps_8_ms_in_and_12_ms_out(tmp_path, monkeypatch, capsys):
    """A constant 16384 (0.5 decoded) is written back as round(0.5 * 32767)
    = 16384; the fade-in's middle sample, 176 of 353, is half that, 8192."""
    monkeypatch.chdir(tmp_path)
    write_wav(tmp_path / "a.wav", np.full(RATE, 0.5))

    assert main(["adjust", "a.wav", "-o", "b.wav", "--fade"]) == 0

    after = read_wav(Path("b.wav"))
    assert steps(Path("b.wav"))["fade"] == {"step": "fade", "in_samples": 353, "out_samples": 529}
    assert (after[0], after[-1]) == (0, 0)
    assert after[176] == 8192
    assert after[353] == after[RATE - 530] == 16384
    assert after[351] < after[352] == 16384 == after[RATE - 529] > after[RATE - 528]


def test_trim_with_nothing_audible_is_refused(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    write_wav(tmp_path / "a.wav", silence(1))

    assert main(["adjust", "a.wav", "-o", "b.wav", "--trim"]) == 1

    assert "nothing louder than" in capsys.readouterr().err
    assert not Path("b.wav").exists()


# --- loudness ------------------------------------------------------------------


def test_loudness_applies_the_gain_that_reaches_the_target(spoken, capsys):
    assert main(["adjust", "a.wav", "-o", "b.wav", "--loudness", "-20"]) == 0

    level = steps(Path("b.wav"))["loudness"]
    before, _ = loudness(spoken)
    after, _ = loudness(Path("b.wav"))
    assert level["measured_lufs"] == before
    assert level["gain_db"] == pytest.approx(-20 - before)
    assert after == pytest.approx(-20, abs=0.1)


def test_without_loudness_the_level_is_left_alone(spoken, capsys):
    """No step normalises unless --loudness asks."""
    assert main(["adjust", "a.wav", "-o", "b.wav", "--trim", "--fade"]) == 0

    assert set(steps(Path("b.wav"))) == {"trim", "fade"}
    assert loudness(Path("b.wav"))[0] == loudness(spoken)[0]


def test_a_gain_past_the_peak_ceiling_is_refused_with_exit_1(spoken, capsys):
    """The tone peaks at -6 dBTP near -9.7 LUFS: reaching -3 LUFS needs
    about +6.7 dB, which puts the peak above -1 dBTP."""
    assert main(["adjust", "a.wav", "-o", "b.wav", "--loudness", "-3"]) == 1

    out, err = capsys.readouterr()
    assert out == ""
    assert err.startswith("a.wav: loudness: ") and err.endswith("above -1\n")
    assert not Path("b.wav").exists() and not Path("b.wav.json").exists()


# --- the companion -------------------------------------------------------------


def test_the_companion_carries_over_appends_steps_and_rehashes(spoken, capsys):
    (spoken.parent / "a.wav.json").write_text(json.dumps({
        "text": "hello world again", "voice": "v1",
        "audio_sha256": sha256(spoken), "adjustments": [{"step": "earlier"}],
    }))

    assert main(["adjust", "a.wav", "-o", "b.wav", "--fade"]) == 0
    assert main(["adjust", "b.wav", "-o", "c.wav", "--trim"]) == 0

    recipe = json.loads(Path("c.wav.json").read_text())
    assert (recipe["text"], recipe["voice"]) == ("hello world again", "v1")
    assert [step["step"] for step in recipe["adjustments"]] == ["earlier", "fade", "trim"]
    assert recipe["audio_sha256"] == sha256(Path("c.wav")) != sha256(spoken)
    capsys.readouterr()
    assert main(["verify", "c.wav"]) == 0


def test_a_file_that_is_not_audio_is_bad_input(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "notes.wav").write_text("not audio")

    with pytest.raises(SystemExit) as exit_info:
        main(["adjust", "notes.wav", "-o", "b.wav"])

    assert exit_info.value.code == 2
    assert capsys.readouterr().err.splitlines()[-1].endswith("notes.wav: not audio ffmpeg can read")


@pytest.mark.parametrize(
    "arguments, message",
    [
        (["missing.wav", "-o", "b.wav"], "missing.wav: no such audio file"),
        (["a.wav", "-o", "b.mp3"], "b.mp3: adjust writes WAV"),
        (["a.wav", "-o", "nowhere/b.wav"], "no such directory nowhere"),
    ],
)
def test_bad_paths_are_usage_errors(spoken, capsys, arguments, message):
    with pytest.raises(SystemExit) as exit_info:
        main(["adjust", *arguments])

    assert exit_info.value.code == 2
    assert message in capsys.readouterr().err
