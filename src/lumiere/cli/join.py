"""`lumiere join` - one audio file and one word-timing file from parts.

Parts come as arguments with one `--gap` between each, or as a sequence
file (`-l sequence.txt`, `-l -` for stdin) that gives the pause after each
part. Every part needs its `a.words.json` companion: the joined word timings
are those, shifted, and never a new transcription.

The joined audio is 16-bit PCM WAV at the first part's sample rate and
channel count. Audio does not travel on a stream, so `-o` names a file.
"""

from __future__ import annotations

import os
import subprocess
import wave
from pathlib import Path
from typing import Any, Callable

import numpy as np

from lumiere.adapters.audio import load_pcm16, sample_format
from lumiere.cli.conventions import STREAM, opened, read_lines, read_words_json, words_path
from lumiere.core.join import Part, joined_timeline, parse_sequence, pause_samples
from lumiere.core.timeline import SourceTimeline

SAMPLE_BYTES = 2


def parts_from_arguments(audio: list[Path], gap: float) -> list[Part]:
    """A gap after every part but the last."""
    return [
        Part(path, gap if i + 1 < len(audio) else 0.0) for i, path in enumerate(audio)
    ]


def parts_from_sequence(sequence: Path) -> list[Part]:
    """Paths in a sequence file are relative to it; on stdin, to the working directory."""
    base = Path.cwd() if str(sequence) == STREAM else sequence.parent
    return parse_sequence(read_lines([sequence]), base)


def join(parts: list[Part], output: Path, words: Path) -> SourceTimeline:
    """Write the joined audio to `output` and its word timings to `words`.

    A part ffmpeg cannot read, or a words file that is not a timeline, is a
    ValueError naming the file, raised before anything is written.
    """
    timelines = [read_words_json(words_path(part.audio)) for part in parts]
    rate, channels = _readable(sample_format, parts[0].audio)
    pieces: list[np.ndarray] = []
    offsets: list[int] = []
    offset = 0
    for part in parts:
        samples = _readable(load_pcm16, part.audio, rate, channels)
        offsets.append(offset)
        pause = np.zeros(pause_samples(part.pause, rate) * channels, dtype="<i2")
        pieces.extend([samples, pause])
        offset += (len(samples) + len(pause)) // channels
    to_stdout = str(words) == STREAM
    media = str(output) if to_stdout else os.path.relpath(output, words.parent)
    timeline = joined_timeline(zip(timelines, offsets), rate, offset, media)
    with wave.open(str(output), "wb") as out:
        out.setparams((channels, SAMPLE_BYTES, rate, 0, "NONE", "not compressed"))
        out.writeframes(np.concatenate(pieces).tobytes())
    with opened(words) as stream:
        # stdout carries one JSON line; the file on disk stays indented.
        stream.write(timeline.to_json(compact=to_stdout) + "\n")
    return timeline


def _readable(decode: Callable[..., Any], audio: Path, *args: int) -> Any:
    try:
        return decode(audio, *args)
    except subprocess.CalledProcessError:
        raise ValueError(f"{audio}: not audio ffmpeg can read") from None
