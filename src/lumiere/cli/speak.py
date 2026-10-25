"""`lumiere speak` - one text becomes one audio file, from one provider request.

The request: the lexicon respells
names for the voice (the text itself keeps the true spelling), a short pause
follows each sentence, and the neighbouring texts go along as context so
separately spoken files still sound like one narration.

`a.wav.json` records the text, the voice, the settings, and the exact
request. Speech costs money and is not deterministic, so a second call with
the same text, voice, and settings makes no request and leaves the audio
alone; `--force` speaks again. Audio this command did not make (an `a.wav`
whose companion records no request) is never replaced without `--force`.

The audio is the provider's MP3 decoded once into a 32-bit float WAV at
44.1 kHz mono: no requantising, so `adjust` works on the provider's own
samples.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Callable

from lumiere.adapters.elevenlabs import TTS_MODEL, VOICE_SETTINGS, speech_request
from lumiere.cli.conventions import opened, read_recipe, recipe_path
from lumiere.core.lexicon import apply_lexicon, used_entries
from lumiere.core.pace import RATE

REQUEST = "request"

#: Given the request body and the voice id, the provider's audio bytes.
Synthesizer = Callable[[dict[str, Any], str], bytes]


def _default_synthesizer(request: dict[str, Any], voice: str) -> bytes:
    from lumiere.adapters.elevenlabs import load_api_key, post_speech

    return post_speech(request, load_api_key(), voice)


def speak(
    text: str,
    output: Path,
    voice: str,
    previous_text: str = "",
    next_text: str = "",
    lexicon: dict[str, str] | None = None,
    speed: float | None = None,
    force: bool = False,
    synthesizer: Synthesizer | None = None,
    model: str = TTS_MODEL,
) -> bool:
    """Write `output` and `output.json`; False when the companion already
    records the same text, voice, and settings and nothing was requested.

    Raises ValueError, before any request, when `output` exists and its
    companion is malformed or records no request, unless `force`.
    """
    # Only the entries this text uses: one lexicon serves every part, and an
    # entry for a word not spoken here cannot change this audio.
    lexicon = used_entries(text, dict(lexicon or {}))
    settings = {
        "model": model,
        "voice_settings": VOICE_SETTINGS,
        "speed": speed,
        "lexicon": lexicon,
        "previous_text": previous_text,
        "next_text": next_text,
    }
    request = speech_request(
        apply_lexicon(text, lexicon), previous_text, next_text, speed, model
    )
    made = {"text": text, "voice": voice, "settings": settings, REQUEST: request}

    if output.exists() and not force:
        recorded = _recorded(output)
        if _comparable(recorded, text) == made:
            return False

    audio = (synthesizer or _default_synthesizer)(request, voice)
    _write_wav(audio, output)
    companion = {**made, "audio_sha256": hashlib.sha256(output.read_bytes()).hexdigest()}
    with opened(recipe_path(output)) as stream:
        stream.write(json.dumps(companion, indent=2, ensure_ascii=False) + "\n")
    return True


def _comparable(recorded: dict[str, Any], text: str) -> dict[str, Any]:
    """The recorded keys of `made`, with the recorded lexicon cut to the
    entries this text uses. A companion written when the whole lexicon was
    recorded then still matches, and nothing is spoken again."""
    comparable = {key: recorded.get(key) for key in ("text", "voice", "settings", REQUEST)}
    settings = comparable["settings"]
    if isinstance(settings, dict) and isinstance(settings.get("lexicon"), dict):
        comparable["settings"] = {**settings, "lexicon": used_entries(text, settings["lexicon"])}
    return comparable


def _recorded(output: Path) -> dict[str, Any]:
    recorded = read_recipe(output)
    if REQUEST not in recorded:
        raise ValueError(
            f"{output}: exists and {recipe_path(output).name} records no request, so speak did "
            f"not make it; pass --force to replace it"
        )
    return recorded


def _write_wav(audio: bytes, output: Path) -> None:
    # Decoded beside the output and moved into place, so an interrupted run
    # never leaves a partial file under a companion that claims it.
    with tempfile.TemporaryDirectory(dir=output.parent) as scratch:
        response = Path(scratch) / "response"
        response.write_bytes(audio)
        decoded = Path(scratch) / "decoded.wav"
        subprocess.run(
            [
                "ffmpeg", "-v", "error", "-y", "-i", str(response),
                "-vn", "-ac", "1", "-ar", str(RATE), "-c:a", "pcm_f32le", str(decoded),
            ],
            capture_output=True, check=True,
        )
        os.replace(decoded, output)
