"""`lumiere transcribe a.wav` - one audio file becomes its word timings.

A project directory keeps the once-per-recording behaviour tested in
`test_transcribe_command.py`; these tests cover the file form. The provider
is a fake that counts its calls, so the cache's whole claim - a repeated
call makes no provider request - is a number. No test reaches ElevenLabs or
resolves a credential: every path to the real provider is replaced.

Skipped without ffmpeg, which refuses non-audio before any request.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import wave
from dataclasses import replace
from pathlib import Path

import numpy as np
import pytest
import requests

from conftest import speech
from lumiere.cli import transcribe as transcribe_module
from lumiere.cli.main import main
from lumiere.cli.transcribe import transcribe_file
from lumiere.core.timeline import SourceTimeline

pytestmark = pytest.mark.skipif(
    shutil.which("ffmpeg") is None, reason="ffmpeg not installed"
)

RATE = 8000


def write_wav(path: Path, first_sample: int = 1) -> Path:
    with wave.open(str(path), "wb") as out:
        out.setparams((1, 2, RATE, 0, "NONE", "not compressed"))
        out.writeframes(np.arange(first_sample, first_sample + RATE, dtype="<i2").tobytes())
    return path


class FakeProvider:
    """Records each request; answers with three evenly spaced words."""

    def __init__(self) -> None:
        self.requests: list[tuple[Path, str | None]] = []

    def __call__(self, audio: Path, language: str | None) -> SourceTimeline:
        self.requests.append((audio, language))
        return replace(
            speech(["alpha", "bravo", "charlie"], 0.2, 0.1),
            media=str(audio.resolve()), language=language or "eng",
        )


@pytest.fixture
def provider(monkeypatch) -> FakeProvider:
    """Stands in for ElevenLabs wherever `main` would reach it."""
    fake = FakeProvider()
    monkeypatch.setattr(transcribe_module, "_default_file_transcriber", fake)
    return fake


@pytest.fixture
def audio(tmp_path: Path, monkeypatch) -> Path:
    monkeypatch.chdir(tmp_path)
    return write_wav(tmp_path / "a.wav")


def words_of(timeline: SourceTimeline) -> list[tuple[str, float, float]]:
    return [(e.text, e.start, e.end) for _, e in timeline.words]


def test_an_audio_file_gets_its_word_timings_beside_it(audio, provider, capsys):
    """The default output is the D1 companion `a.words.json`, and stdout
    carries only its path. Media is relative to the words file, so the pair
    can move together."""
    assert main(["transcribe", "a.wav"]) == 0

    assert capsys.readouterr().out == "a.words.json\n"
    written = SourceTimeline.read(audio.with_name("a.words.json"))
    assert written.media == "a.wav"
    assert words_of(written) == [
        ("alpha", 0.0, 0.2), ("bravo", pytest.approx(0.3), 0.5), ("charlie", 0.6, 0.8),
    ]
    assert provider.requests == [(Path("a.wav"), None)]


def test_a_repeated_call_reads_the_cache_and_makes_no_provider_request(audio, provider):
    """ASR is not deterministic: a second request could spell words
    differently and break every anchor on them. The cache beside the audio
    is keyed by the audio's hash, and a hit writes the same timings."""
    assert main(["transcribe", "a.wav"]) == 0
    first = audio.with_name("a.words.json").read_text()
    audio.with_name("a.words.json").unlink()

    assert main(["transcribe", "a.wav"]) == 0

    assert len(provider.requests) == 1
    assert audio.with_name("a.words.json").read_text() == first
    cache = json.loads(audio.with_name("a.asr.json").read_text())
    assert cache["audio_sha256"] == hashlib.sha256(audio.read_bytes()).hexdigest()
    assert cache["requested_language"] is None


def test_changed_audio_is_transcribed_again(audio, provider):
    """The cache answers for the samples it heard, not for the file name."""
    assert main(["transcribe", "a.wav"]) == 0
    write_wav(audio, first_sample=100)

    assert main(["transcribe", "a.wav"]) == 0

    assert len(provider.requests) == 2


def test_the_language_is_passed_to_the_provider_and_keys_the_cache(audio, provider):
    assert main(["transcribe", "a.wav", "--language", "en"]) == 0
    assert main(["transcribe", "a.wav", "--language", "en"]) == 0
    assert main(["transcribe", "a.wav"]) == 0

    assert provider.requests == [(Path("a.wav"), "en"), (Path("a.wav"), None)]


def test_dash_output_prints_the_word_timings_and_writes_no_words_file(audio, provider, capsys):
    """`-o -` puts the timings on stdout and nothing else there; the cache
    is still written beside the audio, because that is where audio lives."""
    assert main(["transcribe", "a.wav", "-o", "-"]) == 0

    out = capsys.readouterr().out
    printed = SourceTimeline.from_json(out)
    assert words_of(printed)[0] == ("alpha", 0.0, 0.2)
    assert printed.media == "a.wav"
    assert not audio.with_name("a.words.json").exists()
    assert audio.with_name("a.asr.json").is_file()
    # Every stdout result is one JSON line, as `verify --report -` prints.
    assert out.endswith("\n") and out.count("\n") == 1


def test_the_words_file_on_disk_stays_indented(audio, provider):
    assert main(["transcribe", "a.wav"]) == 0

    written = audio.with_name("a.words.json").read_text()
    assert written.startswith('{\n  "schema_version": 1,')


def test_output_elsewhere_records_the_audio_relative_to_it(audio, provider, tmp_path, capsys):
    (tmp_path / "timings").mkdir()

    assert main(["transcribe", "a.wav", "-o", "timings/a.json"]) == 0

    assert capsys.readouterr().out == "timings/a.json\n"
    assert SourceTimeline.read(tmp_path / "timings/a.json").media == "../a.wav"


def test_a_file_that_is_not_audio_is_bad_input_and_requests_nothing(tmp_path, monkeypatch, provider, capsys):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "notes.wav").write_text("not audio\n")

    with pytest.raises(SystemExit) as exit_info:
        main(["transcribe", "notes.wav"])

    assert exit_info.value.code == 2
    out, err = capsys.readouterr()
    assert out == ""
    assert "notes.wav: not audio ffmpeg can read" in err
    assert "Traceback" not in err
    assert provider.requests == []
    assert not (tmp_path / "notes.asr.json").exists()


def test_a_missing_path_is_a_usage_error(tmp_path, monkeypatch, provider, capsys):
    monkeypatch.chdir(tmp_path)

    with pytest.raises(SystemExit) as exit_info:
        main(["transcribe", "absent.wav"])

    assert exit_info.value.code == 2
    assert "absent.wav: no such audio file" in capsys.readouterr().err


def test_a_missing_output_directory_is_a_usage_error_before_any_request(audio, provider, capsys):
    with pytest.raises(SystemExit) as exit_info:
        main(["transcribe", "a.wav", "-o", "nowhere/a.words.json"])

    assert exit_info.value.code == 2
    assert "no such directory nowhere" in capsys.readouterr().err
    assert provider.requests == []


def test_a_missing_api_key_is_bad_input_and_writes_nothing(audio, monkeypatch, capsys):
    """The default provider runs with no key in the environment. The HTTP
    call is replaced too, so nothing could leave the machine."""
    from lumiere.adapters import elevenlabs

    calls: list[Path] = []
    monkeypatch.delenv("ELEVENLABS_API_KEY", raising=False)
    monkeypatch.setattr(elevenlabs, "call_scribe", lambda upload, *rest, **options: calls.append(upload))

    with pytest.raises(SystemExit) as exit_info:
        main(["transcribe", "a.wav"])

    assert exit_info.value.code == 2
    out, err = capsys.readouterr()
    assert out == ""
    assert err.count("\n") == 1
    assert "ELEVENLABS_API_KEY not found" in err
    assert "Traceback" not in err
    assert calls == []
    assert sorted(p.name for p in audio.parent.iterdir()) == ["a.wav"]


@pytest.mark.parametrize("failure", [
    requests.HTTPError("500 Server Error: Internal Server Error for url: https://api.elevenlabs.io/v1/speech-to-text"),
    RuntimeError("Scribe returned 503: {\n  \"detail\": \"busy\"\n}"),
])
@pytest.mark.parametrize("output", [[], ["-o", "-"]])
def test_a_failed_provider_request_exits_1_in_one_line_and_writes_nothing(
    audio, monkeypatch, capsys, failure, output,
):
    def failing(upload: Path, language: str | None) -> SourceTimeline:
        raise failure

    monkeypatch.setattr(transcribe_module, "_default_file_transcriber", failing)

    assert main(["transcribe", "a.wav", *output]) == 1

    out, err = capsys.readouterr()
    assert out == ""
    assert err.count("\n") == 1
    assert err.startswith("a.wav: the provider request failed: ")
    assert ("500 Server Error" in err) or ("Scribe returned 503" in err)
    assert sorted(p.name for p in audio.parent.iterdir()) == ["a.wav"]


def test_a_malformed_cache_is_bad_input_not_a_new_request(audio, provider, capsys):
    """A broken cache is reported rather than silently paid for again."""
    audio.with_name("a.asr.json").write_text("[]")

    with pytest.raises(SystemExit) as exit_info:
        main(["transcribe", "a.wav"])

    assert exit_info.value.code == 2
    assert "a.asr.json: not a transcription cache" in capsys.readouterr().err
    assert provider.requests == []


def test_a_cache_this_command_did_not_write_is_refused_not_replaced(audio, provider, capsys):
    """Another tool may cache Scribe results under the same `a.asr.json`
    name, without the requested language. That is a paid,
    independent transcription: it is reported, never re-requested over."""
    cache = audio.with_name("a.asr.json")
    foreign = json.loads(speech(["alpha"]).to_json())
    foreign["audio_sha256"] = hashlib.sha256(audio.read_bytes()).hexdigest()
    cache.write_text(json.dumps(foreign))
    before = cache.read_text()

    with pytest.raises(SystemExit) as exit_info:
        main(["transcribe", "a.wav"])

    assert exit_info.value.code == 2
    out, err = capsys.readouterr()
    assert out == ""
    assert "a.asr.json: a transcription cache lumiere transcribe did not write" in err
    assert provider.requests == []
    assert cache.read_text() == before
    assert not audio.with_name("a.words.json").exists()


@pytest.mark.parametrize("output, role", [
    ("a.wav", "the audio"),
    ("./a.wav", "the audio"),
    ("a.asr.json", "its transcription cache"),
])
def test_output_onto_the_audio_or_its_cache_is_refused_before_any_request(
    audio, provider, capsys, output, role,
):
    """Writing the timings over the recording would destroy it; over the
    cache, every later call would miss and pay the provider again."""
    recording = audio.read_bytes()

    with pytest.raises(SystemExit) as exit_info:
        main(["transcribe", "a.wav", "-o", output])

    assert exit_info.value.code == 2
    assert f"{Path(output)} is {role}; choose another output" in capsys.readouterr().err
    assert provider.requests == []
    assert audio.read_bytes() == recording
    assert not audio.with_name("a.asr.json").exists()


def test_output_onto_an_existing_cache_leaves_it_intact(audio, provider, capsys):
    assert main(["transcribe", "a.wav", "-o", "-"]) == 0
    cache = audio.with_name("a.asr.json")
    before = cache.read_text()
    capsys.readouterr()

    with pytest.raises(SystemExit) as exit_info:
        main(["transcribe", "a.wav", "-o", str(cache)])

    assert exit_info.value.code == 2
    assert cache.read_text() == before
    assert len(provider.requests) == 1




def test_the_default_provider_gets_the_language_and_resolves_no_real_key(audio, monkeypatch):
    """The ElevenLabs adapter is used unchanged except at its two edges: the
    key lookup and the HTTP call are replaced, so nothing leaves the machine."""
    from lumiere.adapters import elevenlabs

    calls: list[str | None] = []

    def fake_scribe(upload: Path, key: str, language: str | None = None) -> dict:
        assert key == "test-key"
        calls.append(language)
        return {
            "language_code": "eng",
            "words": [{"text": "hello", "start": 0.1, "end": 0.4, "type": "word", "speaker_id": "speaker_0"}],
        }

    monkeypatch.setattr(elevenlabs, "load_api_key", lambda: "test-key")
    monkeypatch.setattr(elevenlabs, "call_scribe", fake_scribe)

    timeline = transcribe_file(audio, audio.with_name("a.words.json"), language="en")

    assert calls == ["en"]
    assert words_of(timeline) == [("hello", 0.1, 0.4)]
    assert timeline.duration == 1.0
