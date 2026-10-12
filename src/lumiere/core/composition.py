"""Anchors in, seconds out - the composition's side of the contract.

An author writes `data-lumiere-start="word:Harbor"` next to the element it moves. The
build resolves it and writes `data-start` / `data-duration`, which are what
HyperFrames actually reads. Those two are build artifacts: regenerated on every
edit, never typed by hand.

HyperFrames is the source of truth and Lumiere extends it. Everything Lumiere
adds to a composition is namespaced - `data-lumiere-*` attributes here, the
`// @lumiere` comment inside a frame - so HyperFrames ignores it, the file
stays a valid HyperFrames composition with or without Lumiere, and no name
can collide with one the framework introduces later.

Markup is patched as text rather than reparsed and re-serialised, because the
file is hand-authored and also written by Studio. Whitespace, attribute order,
and everything this module does not own must survive untouched.
"""

from __future__ import annotations

import html
import re

from lumiere.core.anchor import FilmAnchor, parse_anchor
from lumiere.core.compile import AnchoredElement, TimingPlan
from lumiere.core.timeline import SourceTimeline
from lumiere.core.voiceover import VOICEOVER, voiceover_anchors

START = "data-lumiere-start"
END = "data-lumiere-end"
#: A scene host that carries its own narration: the project-relative path of
#: the word timings its composition is resolved against. Such a host starts
#: where the previous one ends and lasts as long as its narration.
WORDS = "data-lumiere-words"

# Any start tag whose timing Lumiere decides: it carries an anchor, a
# voiceover the anchors default from, or its own narration.
ANCHORED_TAG = re.compile(
    rf"<[a-zA-Z][^>]*\b(?:{START}|{VOICEOVER}|{WORDS})\s*=[^>]*>"
)


def attribute(tag: str, name: str) -> str | None:
    """The attribute's value, matching the whole name and not a suffix of one.

    `\\b` is not enough: a hyphen is a word boundary, so `\\bid=` happily matches
    the tail of `data-hf-id=`. Attributes are always preceded by whitespace
    inside a tag, so that is what the match requires.
    """
    match = re.search(rf'\s{re.escape(name)}\s*=\s*"([^"]*)"', tag)
    return match.group(1) if match else None


#: How an element is addressed, in order of preference. Nothing here is
#: invented by Lumiere: `id` is HTML's own identity attribute and is what the
#: GSAP selectors inside a frame already use, and `data-composition-id` covers
#: the sub-composition clips, which carry no `id` of their own.
#:
#: `data-hf-id` is deliberately absent: HyperFrames assigns those downstream,
#: so authored source - the only thing this module patches - never has one.
HANDLES = ("id", "data-composition-id")


def voiceover_of(tag: str) -> str | None:
    """The sentences spoken over this element, as written: the attribute
    value is HTML, so `Let&#x27;s` comes back as `Let's`."""
    value = attribute(tag, VOICEOVER)
    return html.unescape(value) if value is not None else None


def identify(tag: str) -> str | None:
    """The handle this element is addressed by, if it has one."""
    for name in HANDLES:
        value = attribute(tag, name)
        if value:
            return value
    return None


def set_attribute(tag: str, name: str, value: str) -> str:
    """Replace the attribute's value, or add it if the tag has none yet."""
    pattern = re.compile(rf'(\b{re.escape(name)}\s*=\s*")[^"]*(")')
    if pattern.search(tag):
        return pattern.sub(lambda m: f"{m.group(1)}{value}{m.group(2)}", tag)
    # Insert before the tag's closing bracket, keeping any self-closing slash.
    body = tag[1:-1].rstrip()
    slash = ""
    if body.endswith("/"):
        body, slash = body[:-1].rstrip(), " /"
    return f'<{body} {name}="{value}"{slash}>'


def apply_plan(html: str, plan: TimingPlan) -> str:
    """Write each element's resolved seconds into the markup it came from."""

    def patch(match: re.Match[str]) -> str:
        tag = match.group(0)
        timing = plan.times.get(identify(tag) or "")
        if timing is None:
            return tag
        # Round the two ENDPOINTS, then derive the printed duration, so
        # adjacent clips that share a boundary anchor serialize to the same
        # millisecond. Rounding start and duration independently can print an
        # end one millisecond past the neighbour's start.
        start = round(timing.start, 3)
        end = round(timing.start + timing.duration, 3)
        tag = set_attribute(tag, "data-start", f"{start:.3f}")
        return set_attribute(tag, "data-duration", f"{end - start:.3f}")

    return ANCHORED_TAG.sub(patch, html)


def read_anchors(
    html: str, timeline: SourceTimeline | None = None
) -> list[AnchoredElement]:
    """Every element whose timing is authored as words.

    An element with a `data-lumiere-voiceover` and no explicit anchor gets
    its start and end from the voiceover, which needs the `timeline` to find
    the words in; explicit anchors never do.
    """
    tags = ANCHORED_TAG.findall(html)

    defaults: dict[int, tuple] = {}
    spoken = [
        (n, voiceover_of(tag)) for n, tag in enumerate(tags)
        if attribute(tag, WORDS) is None or attribute(tag, "data-composition-src") is None
    ]
    spoken = [(n, text) for n, text in spoken if text is not None]
    needs_default = any(
        attribute(tags[n], START) is None or attribute(tags[n], END) is None
        for n, _ in spoken
    )
    if needs_default:
        if timeline is None:
            raise ValueError(
                f"an element's anchors default from its {VOICEOVER}, "
                f"which needs the timeline to find the words in"
            )
        anchors = voiceover_anchors([text for _, text in spoken], timeline)
        defaults = {n: pair for (n, _), pair in zip(spoken, anchors)}

    elements: list[AnchoredElement] = []
    for n, tag in enumerate(tags):
        identifier = identify(tag)
        if not identifier:
            raise ValueError(
                f"anchored element has no id to address it by "
                f"({' or '.join(HANDLES)}): {tag}"
            )
        if any(existing.id == identifier for existing in elements):
            raise ValueError(
                f"two anchored elements are both addressed as {identifier!r}; "
                f"give one of them its own id"
            )
        start = attribute(tag, START)
        end = attribute(tag, END)
        words = attribute(tag, WORDS)
        if words is not None and attribute(tag, "data-composition-src") is not None:
            # A host with its own narration: placed after the host before it.
            if start or end:
                raise ValueError(
                    f"{identifier}: timed by its narration ({WORDS}), so it takes "
                    f"no {START} or {END}; its place follows the host before it"
                )
            elements.append(AnchoredElement(id=identifier, start=None, words=words))
            continue
        if words is not None:
            # A root that owns a narration spans it unless it says otherwise.
            elements.append(
                AnchoredElement(
                    id=identifier,
                    start=parse_anchor(start) if start else FilmAnchor("start"),
                    end=parse_anchor(end) if end else FilmAnchor("end"),
                )
            )
            continue
        default = defaults.get(n)
        elements.append(
            AnchoredElement(
                id=identifier,
                start=parse_anchor(start) if start else default[0],
                end=parse_anchor(end) if end else (default[1] if default else None),
            )
        )
    return elements
