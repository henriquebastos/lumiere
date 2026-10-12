"""Measuring the recording itself, to check assumptions rather than trust them.

The editing model treats the gaps between words as usable silence. That is an
assumption about a particular recording, not a general truth: a gap can contain
a breath, a filler, or room noise loud enough to be audible when the master pass
lifts everything by 19 dB.

This module exists so that assumption can be verified per recording instead of
discovered later by ear.
"""

from __future__ import annotations

import re
import subprocess
import wave
from dataclasses import dataclass
from pathlib import Path

import numpy as np

ANALYSIS_RATE = 16000


def load_mono(media: Path, rate: int = ANALYSIS_RATE) -> np.ndarray:
    """Decode to mono float samples in [-1, 1]."""
    raw = subprocess.run(
        [
            "ffmpeg", "-v", "error", "-i", str(media),
            "-vn", "-ac", "1", "-ar", str(rate), "-f", "s16le", "-",
        ],
        capture_output=True, check=True,
    ).stdout
    return np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0


def load_float32(media: Path, rate: int) -> np.ndarray:
    """Decode to mono float32 samples, as FFmpeg produces them.

    `load_mono` goes through 16-bit integers; this does not, so a decoded MP3
    keeps the precision `adjust` works on.
    """
    raw = subprocess.run(
        [
            "ffmpeg", "-v", "error", "-i", str(media),
            "-vn", "-ac", "1", "-ar", str(rate), "-f", "f32le", "-",
        ],
        capture_output=True, check=True,
    ).stdout
    return np.frombuffer(raw, dtype="<f4").copy()


def stretch(pcm: np.ndarray, rate: int, tempo: float) -> np.ndarray:
    """Mono float32 samples played `tempo` times faster at the same pitch (atempo)."""
    raw = subprocess.run(
        [
            "ffmpeg", "-v", "error", "-f", "f32le", "-ar", str(rate), "-ac", "1",
            "-i", "pipe:0", "-af", f"atempo={tempo:.8f}", "-f", "f32le", "-",
        ],
        input=pcm.astype("<f4").tobytes(), capture_output=True, check=True,
    ).stdout
    return np.frombuffer(raw, dtype="<f4").copy()


def write_pcm16(path: Path, pcm: np.ndarray, rate: int) -> None:
    """Write mono float samples as 16-bit WAV, scaled by 32767."""
    with wave.open(str(path), "wb") as out:
        out.setparams((1, 2, rate, 0, "NONE", "not compressed"))
        out.writeframes(np.round(np.clip(pcm, -1, 1) * 32767).astype("<i2").tobytes())


def sample_format(media: Path) -> tuple[int, int]:
    """Sample rate and channel count of the first audio stream."""
    out = subprocess.run(
        [
            "ffprobe", "-v", "error", "-select_streams", "a:0",
            "-show_entries", "stream=sample_rate,channels",
            "-of", "default=noprint_wrappers=1", str(media),
        ],
        capture_output=True, text=True, check=True,
    ).stdout
    fields = dict(line.split("=", 1) for line in out.split())
    if "sample_rate" not in fields or "channels" not in fields:
        raise subprocess.CalledProcessError(1, "ffprobe", out)
    return int(fields["sample_rate"]), int(fields["channels"])


def load_pcm16(media: Path, rate: int, channels: int) -> np.ndarray:
    """Decode to interleaved 16-bit samples, unchanged when already in that form.

    Integers rather than `load_mono`'s floats: joining 16-bit parts must give
    back exactly their samples, and a round trip through floats need not.
    """
    raw = subprocess.run(
        [
            "ffmpeg", "-v", "error", "-i", str(media),
            "-vn", "-ac", str(channels), "-ar", str(rate), "-f", "s16le", "-",
        ],
        capture_output=True, check=True,
    ).stdout
    return np.frombuffer(raw, dtype="<i2")


def loudness(media: Path) -> tuple[float, float]:
    """Integrated loudness (LUFS) and true peak (dBTP) from FFmpeg's EBU R128 meter.

    `ebur128` rather than `loudnorm`'s measurement pass: the two filters round
    differently, and every recorded number was measured with this one, so
    switching would move them all.
    """
    log = subprocess.run(
        [
            "ffmpeg", "-hide_banner", "-nostats", "-i", str(media),
            "-af", "ebur128=peak=true", "-f", "null", "-",
        ],
        capture_output=True, text=True, check=True,
    ).stderr
    summary = log[log.rindex("Summary:"):]
    integrated = re.search(r"I:\s+(-?[\d.]+) LUFS", summary)
    peak = re.search(r"Peak:\s+(-?[\d.]+) dBFS", summary)
    if integrated is None or peak is None:
        raise RuntimeError(f"{media}: could not read the ebur128 summary")
    return float(integrated[1]), float(peak[1])


def level_db(samples: np.ndarray) -> float:
    """RMS level in dBFS. Silence returns a large negative number, not -inf."""
    if len(samples) == 0:
        return -120.0
    return float(20 * np.log10(np.sqrt((samples**2).mean()) + 1e-10))


def noise_floor_db(samples: np.ndarray, rate: int = ANALYSIS_RATE) -> float:
    """The recording's quiet level, as the 5th percentile of 20ms frames.

    A percentile rather than a minimum, so one anomalous frame cannot define
    the floor for the whole take.
    """
    n = int(0.020 * rate)
    usable = samples[: len(samples) // n * n].reshape(-1, n)
    frames = 20 * np.log10(np.sqrt((usable**2).mean(axis=1)) + 1e-10)
    return float(np.percentile(frames, 5))


def breath_gaps(
    timeline,
    samples: np.ndarray,
    min_above_floor: float = 6.0,
    rate: int = ANALYSIS_RATE,
) -> set[int]:
    """Timeline indices of gaps that contain something other than room tone.

    Almost always a breath. In practice these cluster mid-phrase - mid-list,
    mid-clause - exactly where a speaker inhales, while gaps at sentence
    boundaries sit flat at the noise floor.

    That matters for cutting: a gap being long does not make it a good place to
    cut. A long gap with a breath in it is a bad one, because the join lands
    inside the inhale.
    """
    floor = noise_floor_db(samples, rate)
    noisy: set[int] = set()
    for index, entry in enumerate(timeline):
        if entry.kind != "spacing":
            continue
        a, b = entry.start + 0.06, entry.end - 0.06
        if b <= a:
            continue
        level = level_db(samples[int(a * rate) : int(b * rate)])
        if level - floor >= min_above_floor:
            noisy.add(index)
    return noisy


@dataclass(frozen=True)
class GapLevel:
    start: float
    end: float
    level_db: float
    above_floor_db: float


def gap_levels(
    samples: np.ndarray,
    gaps: list[tuple[float, float]],
    rate: int = ANALYSIS_RATE,
    trim: float = 0.06,
) -> list[GapLevel]:
    """Measure each gap, trimmed so neighbouring word onsets do not leak in.

    The trim matters. Measuring a gap to its stated edges catches the attack of
    the next word and reports a level 20 dB above the floor, which looks exactly
    like a breath and is not one.
    """
    floor = noise_floor_db(samples, rate)
    out: list[GapLevel] = []
    for start, end in gaps:
        a, b = start + trim, end - trim
        if b <= a:
            continue
        level = level_db(samples[int(a * rate) : int(b * rate)])
        out.append(GapLevel(start, end, level, level - floor))
    return out
