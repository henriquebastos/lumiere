"""ElevenLabs Scribe as a transcription provider.

Above the seam the contract is: audio in, SourceTimeline out. Nothing outside
this module refers to ElevenLabs, and nothing here decides what the timeline is
used for.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import tempfile
from pathlib import Path

import requests

from lumiere.core.timeline import Entry, SourceTimeline

SCRIBE_URL = "https://api.elevenlabs.io/v1/speech-to-text"
MODEL = "scribe_v1"


class MissingApiKey(RuntimeError):
    """No ELEVENLABS_API_KEY in the environment: bad input, not a provider
    failure, because no request was made."""


def load_api_key() -> str:
    """ELEVENLABS_API_KEY from the environment. Lumiere reads credentials
    from the environment only; the caller's shell (direnv, a secrets
    manager, CI) decides where they come from."""
    key = os.environ.get("ELEVENLABS_API_KEY", "").strip()
    if key:
        return key
    raise MissingApiKey("ELEVENLABS_API_KEY not found in the environment")


def voice_from_env() -> str | None:
    """ELEVENLABS_VOICE_ID from the environment; None when unset or empty."""
    return os.environ.get("ELEVENLABS_VOICE_ID", "").strip() or None


def extract_audio(media: Path, dest: Path) -> None:
    """Mono 16 kHz PCM, which is what Scribe wants and the smallest upload."""
    subprocess.run(
        [
            "ffmpeg", "-y", "-i", str(media),
            "-vn", "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le",
            str(dest),
        ],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def probe_duration(media: Path) -> float:
    out = subprocess.run(
        [
            "ffprobe", "-v", "error",
            "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1",
            str(media),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    return float(out.stdout.strip())


def call_scribe(audio: Path, api_key: str, language: str | None = None) -> dict:
    data = {
        "model_id": MODEL,
        "diarize": "true",
        "tag_audio_events": "true",
        "timestamps_granularity": "word",
    }
    if language:
        data["language_code"] = language

    with open(audio, "rb") as fh:
        resp = requests.post(
            SCRIBE_URL,
            headers={"xi-api-key": api_key},
            files={"file": (audio.name, fh, "audio/wav")},
            data=data,
            timeout=1800,
        )
    if resp.status_code != 200:
        raise RuntimeError(f"Scribe returned {resp.status_code}: {resp.text[:500]}")
    return resp.json()


def timeline_from_scribe(payload: dict, media: Path, duration: float) -> SourceTimeline:
    """Project a Scribe response onto a SourceTimeline, keeping every kind."""
    entries = []
    for raw in payload.get("words", []):
        kind = raw.get("type", "word")
        if kind not in ("word", "spacing", "audio_event"):
            kind = "word"
        entries.append(
            Entry(
                kind=kind,
                text=raw.get("text", ""),
                start=float(raw["start"]),
                end=float(raw["end"]),
                speaker=raw.get("speaker_id"),
            )
        )
    return SourceTimeline(
        entries=tuple(entries),
        media=str(media),
        duration=duration,
        language=payload.get("language_code"),
    )


def transcribe(
    media: Path,
    api_key: str,
    language: str | None = None,
    raw_dest: Path | None = None,
) -> SourceTimeline:
    """Audio or video in, SourceTimeline out."""
    duration = probe_duration(media)
    with tempfile.TemporaryDirectory() as tmp:
        audio = Path(tmp) / f"{media.stem}.wav"
        extract_audio(media, audio)
        payload = call_scribe(audio, api_key, language)
    if raw_dest is not None:
        raw_dest.parent.mkdir(parents=True, exist_ok=True)
        raw_dest.write_text(json.dumps(payload, indent=2))
    return timeline_from_scribe(payload, media, duration)


# -- synthesis ------------------------------------------------------------

TTS_URL = "https://api.elevenlabs.io/v1/text-to-speech"
TTS_MODEL = "eleven_multilingual_v2"

#: Default voice settings: balanced stability, close to the voice sample, no style.
VOICE_SETTINGS = {"stability": 0.5, "similarity_boost": 0.75, "style": 0}


def synthesize(
    text: str,
    api_key: str,
    voice_id: str,
    previous_text: str | None = None,
    next_text: str | None = None,
    model: str = TTS_MODEL,
) -> bytes:
    """One paragraph of speech, conditioned on its neighbours.

    `previous_text` / `next_text` are what keep per-paragraph generation
    sounding like one take: the model hears the seam it is about to cross.
    """
    body: dict = {
        "text": text,
        "model_id": model,
        "voice_settings": VOICE_SETTINGS,
    }
    if previous_text:
        body["previous_text"] = previous_text
    if next_text:
        body["next_text"] = next_text
    return post_speech(body, api_key, voice_id)


#: The pause after each sentence inside one request. A request may hold
#: several sentences, and without it the voice runs them together.
SENTENCE_PAUSE = '<break time="0.22s" />'


def speech_request(
    text: str,
    previous_text: str = "",
    next_text: str = "",
    speed: float | None = None,
    model: str = TTS_MODEL,
) -> dict:
    """The body of one text-to-speech request.

    `text` is what the voice should say, respellings already applied; a
    pause goes after every sentence that another follows. The neighbours are
    sent verbatim, empty when there is none, and `speed` only when given, so
    the same inputs always give the same body, and `speak` can tell a
    repeated request from a new one.
    """
    voice_settings: dict = dict(VOICE_SETTINGS)
    if speed is not None:
        voice_settings["speed"] = speed
    return {
        "text": re.sub(r"([.!?]) ", rf"\1 {SENTENCE_PAUSE} ", text),
        "model_id": model,
        "voice_settings": voice_settings,
        "previous_text": previous_text,
        "next_text": next_text,
    }


def post_speech(request: dict, api_key: str, voice_id: str) -> bytes:
    """One TTS request with the given body; the MP3 bytes it returns."""
    response = requests.post(
        f"{TTS_URL}/{voice_id}",
        params={"output_format": "mp3_44100_128"},
        headers={"xi-api-key": api_key},
        json=request,
        timeout=300,
    )
    response.raise_for_status()
    return response.content
