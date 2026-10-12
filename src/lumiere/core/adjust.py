"""Adjusting a part: its pace, its edges, and its level.

These are the steps applied to every generated part, with constants fixed so
that replaying them gives back the same samples. Samples are float32 in
[-1, 1] at `RATE`, and every operation keeps one NumPy dtype: a different but
equivalent formula would round differently and move the result by a sample
value.

A step that cannot be done well is refused rather than done badly: a pace
that would need too large a tempo change, a gain that would push the true
peak above -1 dBTP, audio with nothing audible to trim to.
"""

from __future__ import annotations

import numpy as np

from lumiere.core.pace import FRAME

# atempo beyond these stretches a voice audibly; such a part is regenerated,
# not adjusted. An audio-quality limit, not a video's policy.
TEMPO_BOUNDS = (0.85, 1.25)
# -48 dBFS: a 10 ms frame above this RMS holds sound worth keeping.
AUDIBLE_RMS = 0.004
# Frames of air kept before the first and after the last audible frame.
TRIM_PAD_BEFORE = 6
TRIM_PAD_AFTER = 7
# Samples of fade at each edge (8 ms in, 12 ms out at 44.1 kHz), so a trimmed
# edge never starts or stops on a click.
FADE_IN = 353
FADE_OUT = 529
# The highest true peak, in dBTP, a level change may produce.
PEAK_CEILING = -1.0


class Refusal(Exception):
    """A step that cannot be done without harming the audio; nothing is written."""


def tempo_for(articulation_sps: float | None, low: float, high: float) -> float:
    """The atempo factor that brings a pace into `low`-`high` syllables per second.

    A pace inside is left alone (1). One outside moves to the midpoint, so a
    bare target (`low == high`) always moves.
    """
    if articulation_sps is None:
        raise Refusal("pace: no speech to time")
    if low <= articulation_sps <= high:
        return 1
    tempo = (low + high) / 2 / articulation_sps
    slowest, fastest = TEMPO_BOUNDS
    if not slowest <= tempo <= fastest:
        raise Refusal(
            f"pace {articulation_sps:.3f} syllables/s needs tempo {tempo:.3f}, "
            f"outside {slowest:g}-{fastest:g}; regenerate rather than stretch"
        )
    return tempo


def trim_bounds(pcm: np.ndarray) -> tuple[int, int]:
    """The samples to keep: the audible frames and a little air either side."""
    frames = len(pcm) // FRAME
    rms = np.sqrt(np.mean(pcm[: frames * FRAME].reshape(-1, FRAME) ** 2, axis=1))
    audible = np.flatnonzero(rms > AUDIBLE_RMS)
    if len(audible) == 0:
        raise Refusal(f"trim: nothing louder than {AUDIBLE_RMS} RMS to keep")
    start = max(0, (int(audible[0]) - TRIM_PAD_BEFORE) * FRAME)
    end = min(len(pcm), (int(audible[-1]) + TRIM_PAD_AFTER) * FRAME)
    return start, end


def fade_edges(pcm: np.ndarray) -> None:
    """Fade both edges in place."""
    if len(pcm) < FADE_IN + FADE_OUT:
        raise Refusal(f"fade: {len(pcm)} samples is shorter than the fades")
    pcm[:FADE_IN] *= np.linspace(0, 1, FADE_IN)
    pcm[-FADE_OUT:] *= np.linspace(1, 0, FADE_OUT)


def level_gain(target_lufs: float, lufs: float, true_peak: float) -> float:
    """The gain in dB that moves `lufs` to `target_lufs`, if the peak allows it."""
    gain_db = target_lufs - lufs
    if true_peak + gain_db > PEAK_CEILING:
        raise Refusal(
            f"loudness: {gain_db:+.2f} dB to reach {target_lufs:g} LUFS would put "
            f"the true peak at {true_peak + gain_db:.2f} dBTP, above {PEAK_CEILING:g}"
        )
    return gain_db


def gained(pcm: np.ndarray, gain_db: float) -> np.ndarray:
    return pcm * 10 ** (gain_db / 20)
