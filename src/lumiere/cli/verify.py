"""`lumiere verify` - `measure`'s numbers held against what a video requires.

Each option is one check: `--pace` and `--loudness` are inclusive ranges,
`--peak` is a true-peak ceiling, `--match` is the least transcript match to
accept. One more check needs no option: when the `a.wav.json` companion
records an `audio_sha256`, the file's bytes must still hash to it, so a
changed sample cannot pass for the audio that was approved.

Every file is checked before the exit code is decided, so one run reports
every failure: a JSON line per file on stdout, a readable line per failed
check on stderr, exit 1 if any check failed.

A requested check whose number cannot be measured fails rather than passes:
`--pace` needs the spoken text, `--match` needs word timings, and a check
that was asked for and could not be made is not evidence of anything.
"""

from __future__ import annotations

import hashlib
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from lumiere.adapters.audio import load_mono, loudness, sample_format
from lumiere.cli.conventions import Span, read_recipe, read_text, recipe_path, words_path
from lumiere.cli.measure import articulation, recognized_words
from lumiere.core.pace import RATE, transcript_match

HASH = "audio_sha256"


@dataclass(frozen=True)
class Requirements:
    pace: Span | None = None
    loudness: Span | None = None
    # True-peak ceiling in dBTP.
    peak: float | None = None
    # Least transcript match, 0 to 1; 1.0 is `exact`.
    match: float | None = None


def verify(
    audio: Path,
    required: Requirements,
    text_file: Path | None = None,
    words_file: Path | None = None,
    overrides: dict[str, int] | None = None,
) -> dict[str, Any]:
    """Check one file and print a line on stderr for each check that failed.

    Raises CalledProcessError for a file ffmpeg cannot read, and ValueError
    for a malformed companion: bad input, not a failed check.
    """
    # Probed even when no check decodes the audio, so a file that is not
    # audio is always bad input rather than sometimes passing.
    sample_format(audio)
    recipe = read_recipe(audio)
    checks: list[dict[str, Any]] = []

    if HASH in recipe:
        recorded = recipe[HASH]
        if not isinstance(recorded, str):
            raise ValueError(f"{recipe_path(audio)}: {HASH} is not a hex digest")
        actual = hashlib.sha256(audio.read_bytes()).hexdigest()
        checks.append(_check(
            "hash", actual == recorded, actual, recorded,
            f"sha256 {actual} is not the {HASH} {recorded} recorded in {recipe_path(audio).name}",
        ))

    if required.loudness is not None or required.peak is not None:
        lufs, true_peak = loudness(audio)
        if required.loudness is not None:
            checks.append(_check(
                "loudness", lufs in required.loudness, lufs, str(required.loudness),
                f"loudness {lufs:g} LUFS is outside {required.loudness}",
            ))
        if required.peak is not None:
            checks.append(_check(
                "true_peak", true_peak <= required.peak, true_peak, f"<= {required.peak:g}",
                f"true peak {true_peak:g} dBTP is above {required.peak:g}",
            ))

    text = read_text(text_file) if text_file is not None else recipe.get("text")
    if not isinstance(text, str):
        text = None
    no_text = f"no text - give --text-file or a 'text' in {recipe_path(audio).name}"

    if required.pace is not None:
        sps = None if text is None else articulation(load_mono(audio, rate=RATE), text, overrides or {})
        checks.append(_check(
            "pace", sps is not None and sps in required.pace, sps, str(required.pace),
            f"pace: {no_text}" if text is None
            else "pace: no speech to time" if sps is None
            else f"pace {sps:.3f} syllables/s is outside {required.pace}",
        ))

    if required.match is not None:
        words = recognized_words(words_file if words_file is not None else words_path(audio))
        ratio = None if text is None or words is None else transcript_match(text, words)
        wanted = "exact" if required.match == 1.0 else f">= {required.match:g}"
        checks.append(_check(
            "match", ratio is not None and ratio >= required.match, ratio, wanted,
            f"match: {no_text}" if text is None
            else f"match: no word timings - give --words or {words_path(audio).name}" if words is None
            else f"match {ratio:.4f} is not {wanted}",
        ))

    for check in checks:
        if not check["passed"]:
            print(f"{audio}: {check['reason']}", file=sys.stderr)
    return {
        "file": str(audio),
        "checks": checks,
        "passed": all(check["passed"] for check in checks),
    }


def _check(name: str, passed: bool, value: Any, required: str, reason: str) -> dict[str, Any]:
    check = {"check": name, "passed": passed, "value": value, "required": required}
    if not passed:
        check["reason"] = reason
    return check
