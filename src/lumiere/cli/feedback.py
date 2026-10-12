"""`lumiere feedback` - read what the producer asked for, and acknowledge it.

The file this reads is written by HyperFrames Studio when a producer submits
frame comments, and its lifecycle is their contract: revise exactly the frames
named, delete the file, re-present. Deletion is the acknowledgement - Studio
re-reads the file when its window regains focus, so one that is gone reads as
"applied" and one that lingers reads as "never seen".

Nothing here decides what a comment means. It carries the producer's words to
whoever is doing the revising, with enough context to start from the right file.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

COMMENTS = ".hyperframes/frame-comments.json"


@dataclass(frozen=True)
class Comment:
    """One frame's feedback, verbatim."""

    frame: int
    text: str
    src: str | None = None
    title: str | None = None

    def describe(self) -> str:
        where = f" ({self.src})" if self.src else ""
        name = f" {self.title}" if self.title else ""
        return f"Frame {self.frame}{name}{where}\n    {self.text}"


@dataclass(frozen=True)
class Batch:
    """Everything submitted and not yet applied."""

    pass_name: str
    submitted_at: str
    comments: tuple[Comment, ...]


def pending(project: Path) -> Batch | None:
    """The comments waiting to be applied, or None if there are none.

    Tolerant on purpose. Studio may be writing this file while we read it, and
    a torn read has to mean "nothing pending yet" rather than stopping a
    review over a race that resolves itself a moment later.
    """
    path = project / COMMENTS
    try:
        data = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict) or not isinstance(data.get("comments"), list):
        return None

    comments = tuple(
        Comment(
            frame=item["frame"],
            text=item["text"],
            src=item.get("src"),
            title=item.get("title"),
        )
        for item in data["comments"]
        if isinstance(item, dict)
        and isinstance(item.get("frame"), int)
        and isinstance(item.get("text"), str)
    )
    if not comments:
        return None

    return Batch(
        pass_name=str(data.get("pass", "storyboard")),
        submitted_at=str(data.get("submitted_at", "")),
        comments=comments,
    )


def wait_for(
    project: Path,
    attempts: int = 600,
    interval: float = 1.0,
    sleep: Callable[[float], None] = time.sleep,
) -> Batch | None:
    """Block until a batch is submitted, or give up after `attempts` polls.

    Polling rather than watching: the file is written by another process on a
    path that may not exist yet, and a poll of a single known path is both
    portable and impossible to get subtly wrong.

    It gives up rather than waiting forever, because a wait that never returns
    is a wedged agent rather than a patient one.
    """
    for _ in range(attempts):
        batch = pending(project)
        if batch is not None:
            return batch
        sleep(interval)
    return pending(project)


def acknowledge(project: Path) -> bool:
    """Delete the batch, which is how Studio learns the work was done."""
    path = project / COMMENTS
    if not path.exists():
        return False
    path.unlink()
    return True
