"""What every audio primitive shares: argument shapes, streams, companions.

`speak`, `measure`, `adjust`, `verify`, and `join` each take files and write
files. They agree on a few things so that a video's scripts can pipe them
together without learning each one separately:

- Values with a shape are checked by argparse `type=` converters, so a bad
  range fails at parse time with exit code 2 before any work starts.
- `-` means stdin when read and stdout when written. Reading goes through
  `fileinput`, which already knows that; writing goes through `opened()`.
- No converter opens a file. `argparse.FileType` did, which is why it was
  deprecated in 3.14 and why it is not used here.
- Results go to stdout as JSON lines or the path of a written file; progress
  and failed checks go to stderr.
- Audio never travels on a stream. It goes to a named file with two
  companions beside it: `a.wav.json` says how it was made, `a.words.json`
  holds its word timings.
"""

from __future__ import annotations

import fileinput
import json
import math
import sys
from argparse import ArgumentTypeError
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import IO, Any, Iterable, Iterator

from lumiere.core.timeline import SourceTimeline

EXIT_OK = 0
# Also an operation that ran and failed, such as a provider request.
EXIT_CHECK_FAILED = 1
EXIT_USAGE = 2

STREAM = "-"


def _number(text: str, unit: str) -> float:
    try:
        value = float(text)
    except ValueError:
        raise ArgumentTypeError(f"{text!r} is not a number of {unit}") from None
    if not math.isfinite(value):
        raise ArgumentTypeError(f"{text!r} is not a finite number of {unit}")
    return value


def seconds(text: str) -> float:
    """A non-negative duration, such as `--gap 0.32`."""
    value = _number(text, "seconds")
    if value < 0:
        raise ArgumentTypeError(f"{text!r}: seconds cannot be negative")
    return value


def speech_speed(text: str) -> float:
    """How fast the voice speaks, 1 being its own pace, such as `--speed 0.9`."""
    value = _number(text, "speed")
    if value <= 0:
        raise ArgumentTypeError(f"{text!r}: a speed is a positive number")
    return value


def count(text: str) -> int:
    """A whole number of at least 1, such as `--limit 20`."""
    try:
        value = int(text)
    except ValueError:
        raise ArgumentTypeError(f"{text!r}: give a whole number such as 20") from None
    if value < 1:
        raise ArgumentTypeError(f"{text!r}: give a whole number of at least 1")
    return value


def port_number(text: str) -> int:
    """A TCP port, 0 to 65535; 0 lets the system pick a free one."""
    try:
        port = int(text)
    except ValueError:
        port = -1
    if not 0 <= port <= 65535:
        raise ArgumentTypeError(f"{text!r}: give a port from 0 to 65535")
    return port


def speech_model(text: str) -> str:
    """A provider model id, such as `--model eleven_v3`."""
    model = text.strip()
    if not model or any(character.isspace() for character in model):
        raise ArgumentTypeError(f"{text!r}: a model is one provider model id")
    return model


def lufs(text: str) -> float:
    """A loudness in LUFS, such as `--loudness -22.85`."""
    return _number(text, "LUFS")


def dbtp(text: str) -> float:
    """A true-peak ceiling in dBTP, such as `--peak -1`."""
    return _number(text, "dBTP")


EXACT = "exact"


def match_threshold(text: str) -> float:
    """The least transcript match to accept: `exact` (1.0) or a ratio such as `0.98`."""
    if text == EXACT:
        return 1.0
    value = _number(text, "match ratio")
    if not 0 <= value <= 1:
        raise ArgumentTypeError(f"{text!r}: a match is `exact` or a ratio from 0 to 1")
    return value


@dataclass(frozen=True)
class Span:
    """An inclusive range written `low:high`, such as `5.0:5.6` or `-24:-21.7`.

    Both ends are required: a one-sided check is a plain threshold and gets a
    plain number. Python 3.14 argparse lets `--loudness -24:-21.7` parse
    without `=`, because an option value that is not itself an option name is
    no longer mistaken for one.
    """

    low: float
    high: float

    @classmethod
    def parse(cls, text: str) -> Span:
        low, separator, high = text.partition(":")
        if not separator or not low or not high:
            raise ArgumentTypeError(f"{text!r} is not a range like 5.0:5.6")
        span = cls(_number(low, "range"), _number(high, "range"))
        if span.low > span.high:
            raise ArgumentTypeError(f"{text!r}: the low end is above the high end")
        return span

    def __contains__(self, value: float) -> bool:
        return self.low <= value <= self.high

    def __str__(self) -> str:
        return f"{self.low:g}:{self.high:g}"


span = Span.parse


def pace_target(text: str) -> Span:
    """A pace for `adjust --pace`: `5.4` always moves there; `5.2:5.6` moves
    only a pace outside the range, to its middle. A bare number is a range of
    zero width."""
    if ":" in text:
        wanted = span(text)
    else:
        target = _number(text, "syllables/s")
        wanted = Span(target, target)
    if wanted.low <= 0:
        raise ArgumentTypeError(f"{text!r}: a pace is a positive number of syllables/s")
    return wanted


def read_text(path: Path | str) -> str:
    """The whole content of one file; `-` reads stdin."""
    return "".join(_lines([path]))


def read_lines(paths: Iterable[Path | str]) -> Iterator[str]:
    """Non-blank lines of the given files in order, stripped; `-` reads stdin.

    This is how path lists reach `measure -`, `verify -`, and `join -l -`.
    """
    for line in _lines(paths):
        stripped = line.strip()
        if stripped:
            yield stripped


def _lines(paths: Iterable[Path | str]) -> Iterator[str]:
    files = [str(p) for p in paths]
    if not files:
        # fileinput with no files reads sys.argv, which is never what a
        # command that already parsed its arguments means.
        return
    # FileInput rather than fileinput.input(): the module-level form keeps
    # one global reader and refuses a second while the first is open.
    with fileinput.FileInput(files=files, encoding="utf-8") as stream:
        yield from stream


@contextmanager
def opened(path: Path | str) -> Iterator[IO[str]]:
    """A text stream to write to; `-` is stdout and is left open afterwards."""
    if str(path) == STREAM:
        yield sys.stdout
        return
    with open(path, "w", encoding="utf-8") as stream:
        yield stream


def write_json_line(record: Any, stream: IO[str] | None = None) -> None:
    """One result as one line, the same in a terminal and in a pipe."""
    out = sys.stdout if stream is None else stream
    out.write(json.dumps(record, ensure_ascii=False) + "\n")
    out.flush()


def recipe_path(audio: Path) -> Path:
    """`a.wav` -> `a.wav.json`: how the audio was made."""
    return audio.with_name(audio.name + ".json")


def words_path(audio: Path) -> Path:
    """`a.wav` -> `a.words.json`: the audio's word timings."""
    return audio.with_name(audio.stem + ".words.json")


def asr_path(audio: Path) -> Path:
    """`a.wav` -> `a.asr.json`: the cached transcription provider response."""
    return audio.with_name(audio.stem + ".asr.json")


def read_recipe(audio: Path) -> dict[str, Any]:
    """The `a.wav.json` beside `audio`, or `{}` when there is none.

    Raises ValueError naming the file when it is not a JSON object, so every
    command reports a malformed companion as bad input in one line.
    """
    path = recipe_path(audio)
    if not path.is_file():
        return {}
    try:
        recipe = json.loads(path.read_text())
    except ValueError as malformed:
        raise ValueError(f"{path}: not JSON ({malformed})") from None
    if not isinstance(recipe, dict):
        raise ValueError(f"{path}: not a JSON object")
    return recipe


def read_words_json(path: Path) -> SourceTimeline:
    """A word-timing file such as `a.words.json`.

    Raises ValueError naming the file when it is not a timeline or its
    duration is not a non-negative number; FileNotFoundError when absent.
    """
    try:
        timeline = SourceTimeline.read(path)
        duration = timeline.duration
        number = isinstance(duration, (int, float)) and not isinstance(duration, bool)
        # `not >= 0` also refuses NaN.
        if not number or not duration >= 0:
            raise ValueError(f"duration {duration!r} is not a non-negative number")
    # AttributeError: valid JSON whose root is not an object, like [] or null.
    except (ValueError, KeyError, TypeError, AttributeError) as malformed:
        raise ValueError(f"{path}: not a word-timing file ({malformed})") from None
    return timeline
