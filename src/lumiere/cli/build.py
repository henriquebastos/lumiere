"""`lumiere build` - resolve every anchor in a project into seconds.

The only side-effecting step in the chain. Everything it decides is decided by
`core`; this module reads files, hands their contents to the pure code, and
writes the result back.

One rule at every level: an element with `data-lumiere-words` owns a narration
for everything below it - its own cues, the hosts it anchors, the voiceovers it
defaults - and a host without one resolves against the nearest owner above,
scoped to its own span. `index.html` is just the top: nothing is read that the
markup does not name.

Given one composition and a word-timing file instead of a project, it resolves
that composition alone against those words: the composition is its own film,
starting at zero and lasting as long as its narration.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import re

from lumiere.core.anchor import FilmAnchor
from lumiere.core.compile import AnchoredElement, Timing, TimingPlan, frames, plan, sequence
from lumiere.core.composition import (
    ANCHORED_TAG,
    WORDS,
    apply_plan,
    attribute,
    identify,
    read_anchors,
)
from lumiere.core.frame import patch_cues
from lumiere.cli.conventions import read_words_json
from lumiere.core.timeline import SourceTimeline

DEFAULT_FPS = 30


def _fps(markup: str) -> int:
    """The composition's frame rate, which a narration's length is rounded to."""
    match = re.search(r'\sdata-fps\s*=\s*"(\d+)"', markup)
    return int(match.group(1)) if match else DEFAULT_FPS


@dataclass(frozen=True)
class BuildReport:
    """What the build changed."""

    patched: tuple[Path, ...] = ()


@dataclass(frozen=True)
class Resolution:
    """Every file's content with its seconds resolved, before anything is
    written. `build` writes it; `check` compares it with what is on disk."""

    files: dict[Path, str]
    #: The anchors as read from index.html, defaults included.
    elements: tuple[AnchoredElement, ...] = ()


#: A composition's root: the first element that is a composition and not a
#: host of one.
ROOT_TAG = re.compile(r"<[a-zA-Z][^>]*\bdata-composition-id\s*=[^>]*>")


def _root(markup: str) -> str | None:
    for tag in ROOT_TAG.findall(markup):
        if attribute(tag, "data-composition-src") is None:
            return tag
    return None


def _words(project: Path, name: str, path: str, fps: int) -> SourceTimeline:
    """A narration as its owner realises it: the words, lasting a whole
    number of the owner's frames, which is what `film:end` means inside."""
    try:
        words = read_words_json(project / path)
    except FileNotFoundError:
        raise ValueError(
            f"{name}: its narration's words are not at {path}; "
            f"run `lumiere join --words` for that scene"
        ) from None
    return SourceTimeline(
        entries=words.entries, media=words.media,
        duration=frames(words.duration, fps), language=words.language,
    )


def _resolve_file(
    project: Path,
    path: Path,
    files: dict[Path, str],
    narration: SourceTimeline | None,
    start: float,
    duration: float,
    within: tuple[float, float] | None,
    elements_of: dict[Path, tuple[AnchoredElement, ...]],
) -> None:
    """Resolve one composition and everything it hosts.

    `narration` is the words this file resolves against, inherited from the
    nearest owner above, and `start`/`duration`/`within` its span in that
    narration. A root that carries `data-lumiere-words` owns its own instead:
    child words win, and the file counts from zero.
    """
    markup = files.get(path) or path.read_text()
    root = _root(markup)
    own = attribute(root, WORDS) if root else None
    if own is not None:
        narration = _words(project, identify(root or "") or path.name, own, _fps(markup))
        start, within, duration = 0.0, None, narration.duration

    # Hosts that carry their own narration are placed back to back; the rest
    # are anchored into this file's narration.
    narrations: dict[str, SourceTimeline] = {}
    lengths: dict[str, float] = {}
    sources: dict[str, Path] = {}
    for tag in ANCHORED_TAG.findall(markup):
        name = identify(tag) or ""
        src = attribute(tag, "data-composition-src")
        if src is not None:
            sources[name] = project / src
        words = attribute(tag, WORDS)
        if words is None or tag == root:
            continue
        child = sources.get(name)
        fps = _fps(child.read_text()) if child and child.exists() else _fps(markup)
        narrations[name] = _words(project, name, words, fps)
        lengths[name] = narrations[name].duration

    # With nothing above and nothing of its own, the film is its hosts' sum.
    if narration is None:
        elements = read_anchors(markup, SourceTimeline(entries=(), media="", duration=0.0))
        placed = sequence(elements, lengths)
        duration = frames(max((t.start + t.duration for t in placed.times.values()), default=0.0), _fps(markup))
        narration = SourceTimeline(entries=(), media="", duration=duration)
        for element in elements:
            if element.start is not None and element.id not in placed.times and not isinstance(element.start, FilmAnchor):
                raise ValueError(
                    f"{element.id}: anchored to a word, but nothing above it owns a "
                    f"narration; give a root or a host {WORDS}"
                )
    else:
        elements = read_anchors(markup, narration)
        placed = sequence(elements, lengths)
    if path.name == "index.html":
        elements_of[path] = tuple(elements)

    # Word anchors resolve in the narration's time; a sequenced host counts
    # from this file's start. Written seconds are relative to this file.
    anchored = plan([e for e in elements if e.id not in placed.times], narration, (start, duration))
    relative = {name: Timing(t.start - start, t.duration) for name, t in anchored.times.items()}
    relative.update(placed.times)
    files[path] = patch_cues(
        apply_plan(markup, TimingPlan(times=relative)), narration, start, duration, within
    )

    slack = 0.5 / _fps(markup)
    for name, timing in relative.items():
        child = sources.get(name)
        if child is None or not child.exists():
            continue
        try:
            if name in narrations:
                _resolve_file(project, child, files, narrations[name], 0.0, lengths[name], None, elements_of)
            else:
                at = start + timing.start
                _resolve_file(
                    project, child, files, narration, at, timing.duration,
                    (max(0.0, at - slack), at + timing.duration + slack), elements_of,
                )
        except (ValueError, KeyError) as refusal:
            # Name the file: the producer changed a sentence and needs to
            # know which frame's motion depended on it, not just which word.
            message = refusal.args[0] if refusal.args else str(refusal)
            if not re.match(r"^\S+\.html: ", message):  # the deepest file names itself
                message = f"{child.relative_to(project)}: {message}"
            raise ValueError(message) from None


def resolve(project: Path) -> Resolution:
    """Resolve every anchor in `project` into seconds, in memory."""
    index = project / "index.html"
    files: dict[Path, str] = {}
    elements_of: dict[Path, tuple[AnchoredElement, ...]] = {}
    _resolve_file(project, index, files, None, 0.0, 0.0, None, elements_of)
    return Resolution(files=files, elements=elements_of.get(index, ()))


def build(project: Path) -> BuildReport:
    """Write resolved seconds into every composition in `project`."""
    resolution = resolve(project)
    patched = []
    for path, after in resolution.files.items():
        if after != path.read_text():
            path.write_text(after)
            patched.append(path)
    return BuildReport(patched=tuple(patched))


def build_composition(composition: Path, words: Path) -> BuildReport:
    """Write resolved seconds into one composition from its own word timings.

    Raises ValueError naming the file when the words are not a word-timing
    file or an anchor names a word they do not hold; nothing is written then.
    """
    before = composition.read_text()
    timeline = _words(words.parent, composition.name, words.name, _fps(before))
    files: dict[Path, str] = {}
    try:
        _resolve_file(
            composition.parent, composition, files, timeline, 0.0, timeline.duration, None, {},
        )
    except (ValueError, KeyError) as refusal:
        raise ValueError(f"{composition}: {refusal.args[0]}") from None

    after = files[composition]
    if after == before:
        return BuildReport()
    composition.write_text(after)
    return BuildReport(patched=(composition,))
