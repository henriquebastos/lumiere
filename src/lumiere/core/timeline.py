"""The source timeline: an immutable record of what was said and when.

Written once from a transcription provider, never edited. Every entry the
provider returns is kept and tagged with its kind, because different consumers
need different kinds: motion sync reads words, cutting reads the silences
between them.

Times are seconds, always. Frames are a property of a render target, not of a
recording, and are projected at use.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Iterator, Literal

Kind = Literal["word", "spacing", "audio_event"]

SCHEMA_VERSION = 1


@dataclass(frozen=True)
class Entry:
    """One span of the recording, of a single kind."""

    kind: Kind
    text: str
    start: float
    end: float
    speaker: str | None = None

    @property
    def duration(self) -> float:
        return self.end - self.start


@dataclass(frozen=True)
class SourceTimeline:
    """Every entry in a recording, in order, covering its full duration."""

    entries: tuple[Entry, ...]
    media: str
    duration: float
    language: str | None = None

    def __post_init__(self) -> None:
        for a, b in zip(self.entries, self.entries[1:]):
            if b.start < a.start:
                raise ValueError(
                    f"entries must be ordered by start time; "
                    f"{b.text!r} at {b.start} follows {a.text!r} at {a.start}"
                )

    # -- selection ---------------------------------------------------------

    def of_kind(self, kind: Kind) -> list[tuple[int, Entry]]:
        """Indexed entries of one kind. Indices address the full timeline."""
        return [(i, e) for i, e in enumerate(self.entries) if e.kind == kind]

    @property
    def words(self) -> list[tuple[int, Entry]]:
        return self.of_kind("word")

    def __len__(self) -> int:
        return len(self.entries)

    def __iter__(self) -> Iterator[Entry]:
        return iter(self.entries)

    def __getitem__(self, i: int) -> Entry:
        return self.entries[i]

    # -- anchors -----------------------------------------------------------

    def find_word(
        self,
        text: str,
        occurrence: int = 0,
        within: tuple[float, float] | None = None,
    ) -> int:
        """Index of a word by text, optionally restricted to a time window.

        Deliberately strict. An anchor addressed by ordinal over the whole
        recording ("the 6th 'And'") silently rebinds to a different word when
        the narration above it changes. Here an anchor that cannot be resolved
        exactly is an error, not a guess.

        `within` exists because ordinals over a whole recording are the same
        trap wearing a different hat. A cue in a scene about Harbor wants *the*
        "Harbor" in that scene, and counting occurrences from the top of the take
        gives the wrong one the moment anything upstream changes. Scoping to
        the scene makes the anchor mean what its author meant.
        """
        norm = normalize(text)
        hits = [
            i
            for i, e in self.words
            if normalize(e.text) == norm
            and (within is None or within[0] <= e.start <= within[1])
        ]
        if not hits:
            where = f" within {within[0]:.2f}-{within[1]:.2f}s" if within else ""
            raise KeyError(f"no word {text!r} in timeline{where}")
        if occurrence >= len(hits):
            where = f" within {within[0]:.2f}-{within[1]:.2f}s" if within else ""
            raise KeyError(
                f"word {text!r} occurs {len(hits)} time(s){where}; "
                f"occurrence {occurrence} requested"
            )
        return hits[occurrence]

    # -- media -------------------------------------------------------------

    def media_path(self, project_dir: Path) -> Path:
        """Resolve `media` against its project directory.

        Media is normally stored project-relative (`in/first.mov`) so a project
        directory is self-contained and can be moved or handed over without
        rewriting its artifacts. Absolute paths are honoured but discouraged:
        they tie a timeline to one machine's filesystem.
        """
        path = Path(self.media)
        return path if path.is_absolute() else (project_dir / path).resolve()

    # -- persistence -------------------------------------------------------

    def to_json(self, compact: bool = False) -> str:
        """Indented for a file; `compact` is one line, for a JSON-lines stream."""
        return json.dumps(
            {
                "schema_version": SCHEMA_VERSION,
                "media": self.media,
                "duration": self.duration,
                "language": self.language,
                "entries": [asdict(e) for e in self.entries],
            },
            indent=None if compact else 2,
        )

    @classmethod
    def from_json(cls, text: str) -> SourceTimeline:
        raw = json.loads(text)
        version = raw.get("schema_version")
        if version != SCHEMA_VERSION:
            raise ValueError(
                f"timeline schema version {version!r}, expected {SCHEMA_VERSION}"
            )
        return cls(
            entries=tuple(Entry(**e) for e in raw["entries"]),
            media=raw["media"],
            duration=raw["duration"],
            language=raw.get("language"),
        )

    def write(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(self.to_json())

    @classmethod
    def read(cls, path: Path) -> SourceTimeline:
        return cls.from_json(path.read_text())


def normalize(text: str) -> str:
    """Compare words by their letters, ignoring case and surrounding marks.

    Punctuation travels with words in the provider's output, so 'revenue.' and
    'revenue' are the same word for anchoring and alignment purposes.
    """
    return "".join(c for c in text.lower() if c.isalnum())
