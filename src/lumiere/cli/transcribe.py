"""`lumiere transcribe` - one audio file into its word timings.

Every anchor addresses words as this transcription spelled them, so a part's
words are written once, beside it (`a.words.json`), and regenerated only when
the audio is. The provider's raw answer is cached beside it too
(`a.asr.json`), keyed by the audio's bytes, so re-running costs nothing and
sends nothing.
"""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import replace
from pathlib import Path
from typing import Callable

from lumiere.adapters.audio import sample_format
from lumiere.cli.conventions import STREAM, asr_path, opened
from lumiere.core.timeline import SourceTimeline

FileTranscriber = Callable[[Path, str | None], SourceTimeline]


def _default_file_transcriber(audio: Path, language: str | None) -> SourceTimeline:
    from lumiere.adapters.elevenlabs import load_api_key
    from lumiere.adapters.elevenlabs import transcribe as scribe

    return scribe(audio, load_api_key(), language=language)


def transcribe_file(
    audio: Path,
    output: Path,
    language: str | None = None,
    transcriber: FileTranscriber | None = None,
) -> SourceTimeline:
    """Write the word timings of one audio file to `output` (`-` is stdout).

    A file ffmpeg cannot read raises CalledProcessError before any request.
    A cache whose audio hash and requested language both match is used
    instead of the provider; a cache this command wrote for other audio or
    another language is replaced. A cache it did not write raises
    ValueError rather than being paid for again and overwritten.
    """
    cache = asr_path(audio)
    if str(output) != STREAM:
        for reserved, role in ((audio, "the audio"), (cache, "its transcription cache")):
            if _same_file(output, reserved):
                raise ValueError(f"{output} is {role}; choose another output")
    sample_format(audio)
    digest = hashlib.sha256(audio.read_bytes()).hexdigest()
    timeline = _cached(cache, digest, language)
    if timeline is None:
        timeline = (transcriber or _default_file_transcriber)(audio, language)
        record = json.loads(replace(timeline, media=audio.name).to_json())
        record.update(audio_sha256=digest, requested_language=language)
        cache.write_text(json.dumps(record, indent=2, ensure_ascii=False) + "\n")
    to_stdout = str(output) == STREAM
    media = str(audio) if to_stdout else os.path.relpath(audio, output.parent)
    with opened(output) as stream:
        # stdout carries one JSON line; the file on disk stays indented.
        stream.write(replace(timeline, media=media).to_json(compact=to_stdout) + "\n")
    return timeline


def _same_file(path: Path, other: Path) -> bool:
    # samefile also catches hard links and a case-insensitive file system.
    if path.exists() and other.exists():
        return path.samefile(other)
    return path.resolve() == other.resolve()


def _cached(cache: Path, digest: str, language: str | None) -> SourceTimeline | None:
    if not cache.is_file():
        return None
    try:
        record = json.loads(cache.read_text())
        written_here = "requested_language" in record
        if written_here and (
            record.get("audio_sha256") != digest
            or record["requested_language"] != language
        ):
            return None
        timeline = SourceTimeline.from_json(json.dumps(record))
    # AttributeError, TypeError: valid JSON whose root is not an object.
    except (ValueError, KeyError, TypeError, AttributeError) as malformed:
        raise ValueError(f"{cache}: not a transcription cache ({malformed})") from None
    # Another tool's cache under the same name is someone else's paid
    # result: never re-request over it.
    if not written_here:
        raise ValueError(
            f"{cache}: a transcription cache lumiere transcribe did not write "
            f"(no requested_language); move it aside to transcribe again"
        )
    return timeline
