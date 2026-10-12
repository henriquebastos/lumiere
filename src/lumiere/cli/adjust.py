"""`lumiere adjust` - one audio file brought to a pace, trimmed, faded, levelled.

Each option is one step, and the steps always run in the same order: tempo
(`--pace`), `--trim`, `--fade`, then gain (`--loudness`). The order
matters: trimming after a
tempo change trims the audio that will be heard, and levelling last measures
the loudness of the final edges.

Nothing is normalised unless `--loudness` asks for it: a video chooses
per file; `join` concatenates the adjusted parts.

The output is a 16-bit mono WAV at 44.1 kHz. Its `b.wav.json` companion
starts as a copy of `a.wav.json`, so the text and how the audio was spoken
travel with it; the steps taken are appended to its `adjustments`, and its
`audio_sha256` is the new file's, so `verify` checks the adjusted audio
rather than the original.
"""

from __future__ import annotations

import hashlib
import json
import tempfile
from pathlib import Path
from typing import Any

from lumiere.adapters.audio import load_float32, loudness, stretch, write_pcm16
from lumiere.cli.conventions import Span, opened, read_recipe, read_text, recipe_path
from lumiere.cli.measure import articulation
from lumiere.core.adjust import (
    FADE_IN,
    FADE_OUT,
    fade_edges,
    gained,
    level_gain,
    tempo_for,
    trim_bounds,
)
from lumiere.core.pace import RATE

ADJUSTMENTS = "adjustments"


def adjust(
    source: Path,
    output: Path,
    pace: Span | None = None,
    trim: bool = False,
    fade: bool = False,
    target_lufs: float | None = None,
    text_file: Path | None = None,
    overrides: dict[str, int] | None = None,
) -> list[dict[str, Any]]:
    """Write the adjusted `source` to `output` and return the steps taken.

    Raises `Refusal` for a step that would harm the audio, before anything
    is written; CalledProcessError for a file ffmpeg cannot read; and
    ValueError for bad input such as a malformed companion or `--pace`
    without the spoken text.
    """
    recipe = read_recipe(source)
    if not isinstance(recipe.get(ADJUSTMENTS, []), list):
        raise ValueError(f"{recipe_path(source)}: {ADJUSTMENTS} is not a list")
    text = read_text(text_file) if text_file is not None else recipe.get("text")
    if text_file is not None:
        recipe["text"] = text
    pcm = load_float32(source, RATE)
    steps: list[dict[str, Any]] = []

    if pace is not None:
        if not isinstance(text, str):
            raise ValueError(
                f"{source}: --pace needs the spoken text - give --text-file "
                f"or a 'text' in {recipe_path(source).name}"
            )
        measured = articulation(pcm, text, overrides or {})
        if measured == 0:
            # Speech with no syllables to time: the text, not the audio, is wrong.
            raise ValueError(
                f"{source}: --pace needs spoken text with syllables; "
                f"the text has none ({text!r})"
            )
        tempo = tempo_for(measured, pace.low, pace.high)
        if tempo != 1:
            pcm = stretch(pcm, RATE, tempo)
        steps.append({
            "step": "tempo",
            "pace": pace.low if pace.low == pace.high else str(pace),
            "measured_pace": measured,
            "tempo": tempo,
        })

    if trim:
        start, end = trim_bounds(pcm)
        pcm = pcm[start:end]
        steps.append({"step": "trim", "start": start / RATE, "end": end / RATE})

    if fade:
        fade_edges(pcm)
        steps.append({"step": "fade", "in_samples": FADE_IN, "out_samples": FADE_OUT})

    if target_lufs is not None:
        # Measured on the 16-bit file it would be written as, with the meter
        # `measure` and `verify` use, so the gain answers to those numbers.
        with tempfile.TemporaryDirectory() as scratch:
            unlevelled = Path(scratch) / "unlevelled.wav"
            write_pcm16(unlevelled, pcm, RATE)
            lufs, true_peak = loudness(unlevelled)
        gain_db = level_gain(target_lufs, lufs, true_peak)
        pcm = gained(pcm, gain_db)
        steps.append({
            "step": "loudness",
            "target_lufs": target_lufs,
            "measured_lufs": lufs,
            "measured_true_peak": true_peak,
            "gain_db": gain_db,
        })

    write_pcm16(output, pcm, RATE)
    recipe[ADJUSTMENTS] = [*recipe.get(ADJUSTMENTS, []), *steps]
    recipe["audio_sha256"] = hashlib.sha256(output.read_bytes()).hexdigest()
    with opened(recipe_path(output)) as stream:
        stream.write(json.dumps(recipe, indent=2, ensure_ascii=False) + "\n")
    return steps
