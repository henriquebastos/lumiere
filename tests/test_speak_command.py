"""`lumiere speak` - one text, one provider request, one audio file and its companion.

The provider is a fake that records each request and answers with a short
WAV, so the companion's whole claim - the same text and settings make no
second request - is a count of calls. No test reaches ElevenLabs or
resolves a credential: every path to the real provider is replaced.

Skipped without ffmpeg, which decodes the provider's audio.
"""

from __future__ import annotations

import hashlib
import io
import json
import shutil
import subprocess
import wave
from pathlib import Path
from typing import Any

import numpy as np
import pytest
import requests

from lumiere.adapters.audio import load_float32, sample_format
from lumiere.cli import speak as speak_module
from lumiere.cli.main import main
from lumiere.core.pace import RATE

pytestmark = pytest.mark.skipif(
    shutil.which("ffmpeg") is None, reason="ffmpeg not installed"
)

VOICE = "test-voice"


def wav_bytes(samples: int = RATE // 10) -> bytes:
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as out:
        out.setparams((1, 2, RATE, 0, "NONE", "not compressed"))
        out.writeframes(np.arange(samples, dtype="<i2").tobytes())
    return buffer.getvalue()


class FakeProvider:
    """Records each request; answers with the given bytes (a short WAV by default)."""

    def __init__(self, answer: bytes | None = None) -> None:
        self.answer = wav_bytes() if answer is None else answer
        self.requests: list[tuple[dict[str, Any], str]] = []

    def __call__(self, request: dict[str, Any], voice: str) -> bytes:
        self.requests.append((request, voice))
        return self.answer


@pytest.fixture
def provider(monkeypatch) -> FakeProvider:
    """Stands in for ElevenLabs wherever `main` would reach it."""
    fake = FakeProvider()
    monkeypatch.setattr(speak_module, "_default_synthesizer", fake)
    monkeypatch.delenv("ELEVENLABS_VOICE_ID", raising=False)
    return fake


@pytest.fixture
def here(tmp_path: Path, monkeypatch) -> Path:
    monkeypatch.chdir(tmp_path)
    return tmp_path


def companion(path: Path) -> dict[str, Any]:
    return json.loads(path.with_name(path.name + ".json").read_text())


def test_speaking_a_text_writes_the_audio_and_how_it_was_made(here, provider, capsys):
    """One request per call; stdout carries only the written path. The
    companion records the text, voice, settings, and the request sent, and
    the hash `verify` holds the audio to."""
    assert main(["speak", "Hello there. How are you?", "-o", "a.wav", "--voice", VOICE]) == 0

    assert capsys.readouterr().out == "a.wav\n"
    assert len(provider.requests) == 1
    request, voice = provider.requests[0]
    assert voice == VOICE
    assert request == {
        "text": 'Hello there. <break time="0.22s" /> How are you?',
        "model_id": "eleven_multilingual_v2",
        "voice_settings": {"stability": 0.5, "similarity_boost": 0.75, "style": 0},
        "previous_text": "",
        "next_text": "",
    }
    made = companion(here / "a.wav")
    assert made["text"] == "Hello there. How are you?"
    assert made["voice"] == VOICE
    assert made["request"] == request
    assert made["settings"] == {
        "model": "eleven_multilingual_v2",
        "voice_settings": {"stability": 0.5, "similarity_boost": 0.75, "style": 0},
        "speed": None,
        "lexicon": {},
        "previous_text": "",
        "next_text": "",
    }
    assert made["audio_sha256"] == hashlib.sha256((here / "a.wav").read_bytes()).hexdigest()


def test_the_audio_is_the_providers_samples_as_float_wav_at_44100_mono(here, provider):
    """Decoded once, never requantised: the 16-bit answer's samples come back
    exactly, scaled to floats."""
    assert main(["speak", "Hello.", "-o", "a.wav", "--voice", VOICE]) == 0

    assert sample_format(here / "a.wav") == (RATE, 1)
    samples = load_float32(here / "a.wav", RATE)
    assert len(samples) == RATE // 10
    assert np.array_equal(samples, np.arange(RATE // 10, dtype=np.float32) / 32768)


def test_the_same_text_and_settings_make_no_second_request(here, provider, capsys):
    arguments = ["speak", "Hello.", "-o", "a.wav", "--voice", VOICE, "--speed", "0.9",
                 "--previous", "Before.", "--next", "After."]
    assert main(arguments) == 0
    audio = (here / "a.wav").read_bytes()
    capsys.readouterr()

    assert main(arguments) == 0

    assert len(provider.requests) == 1
    assert (here / "a.wav").read_bytes() == audio
    printed = capsys.readouterr()
    assert printed.out == "a.wav\n"
    assert "unchanged" in printed.err


@pytest.mark.parametrize("changed", [
    ["Goodbye.", "-o", "a.wav", "--voice", VOICE],
    ["Hello.", "-o", "a.wav", "--voice", "other-voice"],
    ["Hello.", "-o", "a.wav", "--voice", VOICE, "--speed", "1.1"],
    ["Hello.", "-o", "a.wav", "--voice", VOICE, "--previous", "Before."],
    ["Hello.", "-o", "a.wav", "--voice", VOICE, "--next", "After."],
    ["Hello.", "-o", "a.wav", "--voice", VOICE, "--lexicon", "lexicon.json"],
    ["Hello.", "-o", "a.wav", "--voice", VOICE, "--force"],
    ["Hello.", "-o", "a.wav", "--voice", VOICE, "--model", "eleven_v3"],
], ids=["text", "voice", "speed", "previous", "next", "lexicon", "force", "model"])
def test_a_changed_text_or_setting_or_force_speaks_again(here, provider, changed):
    (here / "lexicon.json").write_text(json.dumps({"Hello": "Heh-low"}))
    assert main(["speak", "Hello.", "-o", "a.wav", "--voice", VOICE]) == 0

    assert main(["speak", *changed]) == 0

    assert len(provider.requests) == 2
    assert companion(here / "a.wav")["request"] == provider.requests[1][0]


def test_missing_audio_is_spoken_again_even_when_its_companion_matches(here, provider):
    assert main(["speak", "Hello.", "-o", "a.wav", "--voice", VOICE]) == 0
    (here / "a.wav").unlink()

    assert main(["speak", "Hello.", "-o", "a.wav", "--voice", VOICE]) == 0

    assert len(provider.requests) == 2


def test_the_text_comes_from_an_argument_a_file_or_stdin_alike(here, provider, monkeypatch):
    """A file's closing newline is not speech: all three forms send one request text."""
    (here / "a.txt").write_text("Hello there.\n")
    monkeypatch.setattr("sys.stdin", io.StringIO("Hello there.\n"))

    assert main(["speak", "Hello there.", "-o", "a.wav", "--voice", VOICE]) == 0
    assert main(["speak", "-f", "a.txt", "-o", "b.wav", "--voice", VOICE]) == 0
    assert main(["speak", "-", "-o", "c.wav", "--voice", VOICE]) == 0

    assert [request["text"] for request, _ in provider.requests] == ["Hello there."] * 3
    assert {companion(here / name)["text"] for name in ("a.wav", "b.wav", "c.wav")} == {"Hello there."}


def test_neighbours_come_from_files_and_go_as_context_only(here, provider):
    (here / "before.txt").write_text("The line before.\n")
    (here / "after.txt").write_text("The line after.\n")

    assert main(["speak", "This line.", "-o", "a.wav", "--voice", VOICE,
                 "--previous-file", "before.txt", "--next-file", "after.txt"]) == 0

    request = provider.requests[0][0]
    assert (request["text"], request["previous_text"], request["next_text"]) == (
        "This line.", "The line before.", "The line after.",
    )


def test_the_lexicon_respells_the_request_and_the_text_keeps_the_true_spelling(here, provider):
    """Respellings are for the voice only: `measure` and `verify` read the
    companion's text, which must be what the script says."""
    (here / "lexicon.json").write_text(json.dumps({"Henrique": "En-hee-kee"}))

    assert main(["speak", "Henrique wrote it. Henriques too.", "-o", "a.wav",
                 "--voice", VOICE, "--lexicon", "lexicon.json"]) == 0

    assert provider.requests[0][0]["text"] == (
        'En-hee-kee wrote it. <break time="0.22s" /> Henriques too.'
    )
    made = companion(here / "a.wav")
    assert made["text"] == "Henrique wrote it. Henriques too."
    assert made["settings"]["lexicon"] == {"Henrique": "En-hee-kee"}


def test_only_the_lexicon_entries_the_text_uses_are_recorded(here, provider):
    """One lexicon serves every part. An entry for a word this text does not
    say cannot change its audio, so adding one must not speak the part again."""
    (here / "lexicon.json").write_text(json.dumps({"Henrique": "En-hee-kee"}))
    arguments = ["speak", "Henrique wrote it.", "-o", "a.wav", "--voice", VOICE,
                 "--lexicon", "lexicon.json"]
    assert main(arguments) == 0

    (here / "lexicon.json").write_text(json.dumps({"Henrique": "En-hee-kee", "Lumiere": "Loo-myair"}))
    assert main(arguments) == 0

    assert len(provider.requests) == 1
    assert companion(here / "a.wav")["settings"]["lexicon"] == {"Henrique": "En-hee-kee"}


def test_a_companion_that_recorded_the_whole_lexicon_still_matches(here, provider):
    """Companions written before the change hold every entry. The entries the
    text uses are the same, so the audio is current and nothing is requested."""
    (here / "lexicon.json").write_text(json.dumps({"Henrique": "En-hee-kee", "Lumiere": "Loo-myair"}))
    arguments = ["speak", "Henrique wrote it.", "-o", "a.wav", "--voice", VOICE,
                 "--lexicon", "lexicon.json"]
    assert main(arguments) == 0
    path = here / "a.wav.json"
    old = json.loads(path.read_text())
    old["settings"]["lexicon"] = {"Henrique": "En-hee-kee", "Lumiere": "Loo-myair"}
    path.write_text(json.dumps(old))

    assert main(arguments) == 0

    assert len(provider.requests) == 1


def test_the_model_is_chosen_with_model(here, provider):
    assert main(["speak", "Hello.", "-o", "a.wav", "--voice", VOICE, "--model", "eleven_v3"]) == 0

    assert provider.requests[0][0]["model_id"] == "eleven_v3"
    assert companion(here / "a.wav")["settings"]["model"] == "eleven_v3"


def test_the_voice_defaults_to_the_environment(here, provider, monkeypatch):
    monkeypatch.setenv("ELEVENLABS_VOICE_ID", "env-voice")

    assert main(["speak", "Hello.", "-o", "a.wav"]) == 0

    assert provider.requests[0][1] == "env-voice"


def test_an_env_file_is_not_read(here, provider, capsys):
    """Credentials come from the environment only: a `.env` in the working
    directory is the shell's business (direnv), never Lumiere's."""
    (here / ".env").write_text("ELEVENLABS_VOICE_ID='file-voice'\n")

    with pytest.raises(SystemExit) as exit_info:
        main(["speak", "Hello.", "-o", "a.wav"])

    assert exit_info.value.code == 2
    assert "ELEVENLABS_VOICE_ID" in capsys.readouterr().err
    assert provider.requests == []


def test_a_missing_api_key_is_bad_input_and_writes_nothing(here, monkeypatch, capsys):
    """The default provider runs with no key in the environment. The HTTP
    call is replaced too, so nothing could leave the machine."""
    from lumiere.adapters import elevenlabs

    calls: list[dict[str, Any]] = []
    monkeypatch.delenv("ELEVENLABS_API_KEY", raising=False)
    monkeypatch.setattr(elevenlabs, "post_speech", lambda request, *rest: calls.append(request))

    with pytest.raises(SystemExit) as exit_info:
        main(["speak", "Hello.", "-o", "a.wav", "--voice", VOICE])

    assert exit_info.value.code == 2
    out, err = capsys.readouterr()
    assert out == ""
    assert err.count("\n") == 1
    assert "ELEVENLABS_API_KEY not found" in err
    assert "Traceback" not in err
    assert calls == []
    assert list(here.iterdir()) == []


def test_a_missing_voice_id_is_bad_input_in_one_line_and_writes_nothing(here, provider, capsys):
    """No --voice and no ELEVENLABS_VOICE_ID in the environment (the provider
    fixture clears it)."""
    with pytest.raises(SystemExit) as exit_info:
        main(["speak", "Hello.", "-o", "a.wav"])

    assert exit_info.value.code == 2
    out, err = capsys.readouterr()
    assert out == ""
    assert err == "lumiere speak: error: give --voice or set ELEVENLABS_VOICE_ID\n"
    assert provider.requests == []
    assert list(here.iterdir()) == []


@pytest.mark.parametrize("failure", [
    requests.HTTPError("401 Client Error: Unauthorized for url: https://api.elevenlabs.io/v1/text-to-speech/test-voice"),
    RuntimeError("quota exceeded\nfor this month"),
])
def test_a_failed_provider_request_exits_1_in_one_line_and_writes_nothing(here, monkeypatch, capsys, failure):
    def failing(request: dict[str, Any], voice: str) -> bytes:
        raise failure

    monkeypatch.setattr(speak_module, "_default_synthesizer", failing)

    assert main(["speak", "Hello.", "-o", "a.wav", "--voice", VOICE]) == 1

    out, err = capsys.readouterr()
    assert out == ""
    assert err.count("\n") == 1
    assert err.startswith("a.wav: the provider request failed: ")
    assert ("401 Client Error" in err) or ("quota exceeded for this month" in err)
    assert list(here.iterdir()) == []


def test_a_provider_answer_that_is_not_audio_exits_1_and_writes_nothing(here, monkeypatch, capsys):
    monkeypatch.setattr(speak_module, "_default_synthesizer", FakeProvider(b"not audio"))

    assert main(["speak", "Hello.", "-o", "a.wav", "--voice", VOICE]) == 1

    out, err = capsys.readouterr()
    assert out == ""
    assert err == "a.wav: the provider's answer is not audio ffmpeg can read\n"
    assert list(here.iterdir()) == []


def test_audio_speak_did_not_make_is_never_replaced_without_force(here, provider, capsys):
    """An `a.wav` with no companion request may be a recording or approved
    audio: refused before any request, and replaced only with --force."""
    (here / "a.wav").write_bytes(wav_bytes(10))
    original = (here / "a.wav").read_bytes()

    with pytest.raises(SystemExit) as exit_info:
        main(["speak", "Hello.", "-o", "a.wav", "--voice", VOICE])

    assert exit_info.value.code == 2
    assert "pass --force" in capsys.readouterr().err
    assert provider.requests == []
    assert (here / "a.wav").read_bytes() == original

    assert main(["speak", "Hello.", "-o", "a.wav", "--voice", VOICE, "--force"]) == 0
    assert len(provider.requests) == 1


@pytest.mark.parametrize("arguments, message", [
    (["-o", "a.wav", "--voice", VOICE], "either as an argument"),
    (["Hello.", "-f", "a.txt", "-o", "a.wav", "--voice", VOICE], "either as an argument"),
    (["Hello.", "-o", "a.mp3", "--voice", VOICE], "name the output .wav"),
    (["Hello.", "-o", "missing/a.wav", "--voice", VOICE], "no such directory"),
    (["-f", "missing.txt", "-o", "a.wav", "--voice", VOICE], "missing.txt: no such file"),
    (["Hello.", "-o", "a.wav", "--voice", VOICE, "--lexicon", "missing.json"], "no such lexicon"),
    (["Hello.", "-o", "a.wav", "--voice", VOICE, "--lexicon", "bad.json"], "respelling"),
    (["-f", "blank.txt", "-o", "a.wav", "--voice", VOICE], "empty"),
    (["-", "-o", "a.wav", "--voice", VOICE, "--next-file", "-"], "stdin"),
    (["Hello.", "-o", "a.wav", "--voice", VOICE, "--speed", "0"], "positive"),
    (["Hello.", "-o", "a.wav", "--voice", VOICE, "--model", " "], "model"),
    (["Hello.", "-o", "a.wav", "--voice", VOICE, "--previous", "x", "--previous-file", "a.txt"],
     "not allowed with"),
])
def test_bad_usage_exits_2_before_any_request(here, provider, capsys, arguments, message):
    (here / "a.txt").write_text("Hello.")
    (here / "blank.txt").write_text("\n")
    (here / "bad.json").write_text(json.dumps({"Hello": 1}))

    with pytest.raises(SystemExit) as exit_info:
        main(["speak", *arguments])

    assert exit_info.value.code == 2
    assert message in capsys.readouterr().err
    assert provider.requests == []
    assert not (here / "a.wav").exists()
