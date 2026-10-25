"""`lumiere check` - is the project's timing what the audio says it is?

Additive to `hyperframes check`, which owns lint, runtime, layout, motion, and
contrast. HyperFrames is the source of truth and a composition with typed
seconds is a valid one; what Lumiere can add is two answers the framework
cannot give:

- **Errors** (exit 1): an anchor Lumiere owns cannot be honoured - its word is
  not in the narration, a voiceover matched nothing, an element cannot be
  addressed - or the seconds on disk are not the ones the anchors resolve
  to, so the project is stale and `lumiere build` has to run.
- **Warnings** (exit 0): a timed element or a GSAP position carries a second
  nobody derived. It renders fine today and will not move with the audio.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from lumiere.cli.build import resolve
from lumiere.cli.conventions import read_words_json
from lumiere.core.composition import START, WORDS, attribute, identify, voiceover_of
from lumiere.core.frame import CUE
from lumiere.core.timeline import SourceTimeline
from lumiere.core.voiceover import VOICEOVER, voiceover_coverage

# A start tag carrying data-start - the attribute that makes an element timed.
TIMED_TAG = re.compile(r"<[a-zA-Z][^>]*\bdata-start\s*=[^>]*>")

# A voiceover below this share of spoken words is probably not what was said.
# A short sentence with one mispronounced name sits near 90%, so the bar is
# lower than that.
COVERAGE = 0.8


@dataclass(frozen=True)
class CheckReport:
    """What is wrong (errors) and what will not follow the audio (warnings)."""

    errors: tuple[str, ...] = ()
    warnings: tuple[str, ...] = field(default=())

    @property
    def ok(self) -> bool:
        return not self.errors


def _describe(tag: str) -> str:
    """Name the element the same way the build addresses it.

    Sharing `identify` matters: a report that called an element one thing while
    `build` wrote seconds onto another would send the author to the wrong line.
    """
    return identify(tag) or "<element with no id>"


# A GSAP call's trailing position argument, and whether a cue follows it.
GSAP_POSITION = re.compile(
    r"tl\.\w+\([^;\n]*,\s*(?P<position>-?\d+(?:\.\d+)?)\);(?P<trailer>[^\n]*)"
)


def _typed_positions(project: Path, markup: str) -> list[str]:
    """Positions inside referenced frames that nobody derived.

    A position of zero means "when this frame starts", which is derived by
    definition - the same standing `film:start` has at the top level.
    """
    warnings: list[str] = []
    for src in re.findall(r'\sdata-composition-src="([^"]*)"', markup):
        frame = project / src
        if not frame.exists():
            continue
        for match in GSAP_POSITION.finditer(frame.read_text()):
            position = float(match.group("position"))
            if position == 0 or CUE in match.group("trailer"):
                continue
            warnings.append(
                f"{src}: position {match.group('position')} is hand-written and "
                f"will not move with the audio. Cue it with `// {CUE} word:...`."
            )
    return warnings


def _typed_elements(markup: str) -> list[str]:
    """Timed elements in index.html that carry no anchor and no voiceover."""
    warnings: list[str] = []
    for tag in TIMED_TAG.findall(markup):
        if any(attribute(tag, name) is not None for name in (START, VOICEOVER, WORDS)):
            continue
        # Nothing is exempt. The composition root and the narration track have
        # no word to name, but they do have `film:start` / `film:end`, so they
        # can say what they mean like everything else.
        warnings.append(
            f"{_describe(tag)}: data-start is hand-written and will not move "
            f"with the audio. Anchor it to a word (word:Harbor) or to the piece "
            f"itself (film:start / film:end)."
        )
    return warnings


def _root_words(project: Path, markup: str) -> SourceTimeline | None:
    """The narration index.html's root owns, if it names one."""
    for tag in re.findall(r"<[a-zA-Z][^>]*\bdata-composition-id\s*=[^>]*>", markup):
        if attribute(tag, "data-composition-src") is None:
            words = attribute(tag, WORDS)
            if words is None:
                return None
            try:
                return read_words_json(project / words)
            except (FileNotFoundError, ValueError):
                return None
    return None


def _drifted_voiceovers(project: Path, markup: str) -> list[str]:
    """Hosts whose voiceover no longer reads as what was recorded over them.

    A host with its own narration is checked against that; the others are
    aligned together against the project's timeline.
    """
    tags = [
        tag for tag in re.findall(r"<[a-zA-Z][^>]*>", markup)
        if attribute(tag, VOICEOVER) is not None
    ]
    shares: list[tuple[str, float]] = []
    shared: list[tuple[str, str]] = []
    for tag in tags:
        words = attribute(tag, WORDS)
        text = voiceover_of(tag) or ""
        if words is not None:
            try:
                [share] = voiceover_coverage([text], read_words_json(project / words))
            except (ValueError, FileNotFoundError):
                continue  # reported by the resolution
            shares.append((tag, share))
        else:
            shared.append((tag, text))
    if shared:
        root = _root_words(project, markup)
        if root is not None:
            try:
                coverage = voiceover_coverage([text for _, text in shared], root)
                shares.extend((tag, share) for (tag, _), share in zip(shared, coverage))
            except ValueError:
                pass  # an unreadable voiceover is reported by the resolution
    return [
        f"{_describe(tag)}: only {share:.0%} of its {VOICEOVER} was spoken where it "
        f"says. Is the sentence still what the recording has over this host?"
        for tag, share in shares
        if share < COVERAGE
    ]


def _stale(project: Path) -> list[str]:
    """Anchors that cannot be honoured, and seconds the anchors disagree with."""
    try:
        resolution = resolve(project)
    except (ValueError, KeyError) as refusal:
        return [refusal.args[0] if refusal.args else str(refusal)]
    except FileNotFoundError as missing:
        return [str(missing)]
    errors: list[str] = []
    for path, resolved in resolution.files.items():
        if resolved != path.read_text():
            errors.append(
                f"{path.relative_to(project)}: its seconds are not what the anchors "
                f"resolve to. Run `lumiere build`."
            )
    return errors


def check(project: Path) -> CheckReport:
    """Errors Lumiere must refuse, and warnings about seconds it does not own."""
    markup = (project / "index.html").read_text()
    return CheckReport(
        errors=tuple(_stale(project)),
        warnings=tuple(
            _typed_elements(markup)
            + _typed_positions(project, markup)
            + _drifted_voiceovers(project, markup)
        ),
    )
