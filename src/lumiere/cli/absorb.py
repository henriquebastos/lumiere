"""`lumiere absorb` - keep a timing edit Studio made, by moving the anchors.

The hosts in `index.html` come first: a clip dragged later by half a second
means every word cue inside its frame now falls half a second earlier in the
frame's own time, so the frames are absorbed against a resolution that
already honours the moved clip. After absorbing, `lumiere build` has nothing
left to change.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from lumiere.cli.build import resolve
from lumiere.core.absorb import Change, absorb_frame, absorb_hosts


@dataclass(frozen=True)
class AbsorbReport:
    """Every anchor that moved, by file."""

    changes: tuple[tuple[Path, Change], ...] = ()


def absorb(project: Path) -> AbsorbReport:
    """Move the project's anchors so the seconds on disk are the derived ones."""
    changes: list[tuple[Path, Change]] = []
    index = project / "index.html"

    resolution = resolve(project)
    markup = index.read_text()
    absorbed, moved = absorb_hosts(markup, resolution.files[index], list(resolution.elements))
    if moved:
        index.write_text(absorbed)
        changes.extend((index, change) for change in moved)
        resolution = resolve(project)

    for path, derived in resolution.files.items():
        if path == index:
            continue
        absorbed, moved = absorb_frame(path.read_text(), derived)
        if moved:
            path.write_text(absorbed)
            changes.extend((path, change) for change in moved)

    return AbsorbReport(changes=tuple(changes))
