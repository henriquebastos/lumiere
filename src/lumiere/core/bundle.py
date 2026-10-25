"""One film in one page: what Lumiere adds to HyperFrames' bundle.

HyperFrames' bundler inlines every composition, script, style, font, and
image, and leaves audio and video as links to the project's files. A bundle
replaces those links; a watch page keeps them, so the browser reads the
project's files. Then the film goes inside the HyperFrames player.

Nothing in the film moves. The page holds the same compositions and the same
clips at the same seconds. Only a link becomes the file it pointed to.
"""

from __future__ import annotations

import html
import json
import re
from typing import Callable

#: The elements whose links name the project's media files.
MEDIA_TAGS = ("audio", "video", "source", "img")

# Scripts, styles, and comments are passed over whole: a tag written inside
# them is text, not an element.
_ELEMENT = re.compile(
    r"<script\b.*?</script\s*>|<style\b.*?</style\s*>|<!--.*?-->"
    rf"|<(?P<tag>{'|'.join(MEDIA_TAGS)})\b[^>]*>",
    re.DOTALL | re.IGNORECASE,
)
_LINK = re.compile(r"""(?P<name>\s(?:src|poster)\s*=\s*)(?P<quote>["'])(?P<link>.*?)(?P=quote)""", re.IGNORECASE)
_SCHEME = re.compile(r"^[a-zA-Z][a-zA-Z0-9+.-]*:")
_TITLE = re.compile(r"<title>(.*?)</title>", re.DOTALL | re.IGNORECASE)
_ROOT = re.compile(r"<[a-z]+\b[^>]*\bdata-composition-id=[^>]*>", re.IGNORECASE)
_SIZE = re.compile(r'\bdata-(width|height)="(\d+)"')

#: Given an element's tag and a link to a project file, what the link becomes.
Relinker = Callable[[str, str], str]


def is_local(link: str) -> bool:
    """Whether a link names a file of the project, not a URL or inline data."""
    return bool(link) and not link.startswith(("#", "//")) and not _SCHEME.match(link)


def relink(film: str, replace: Relinker) -> str:
    """`film` with every local media link replaced by `replace(tag, link)`.

    The link is given unescaped, as the browser would read it. Links in
    scripts, styles, and comments, and links that are URLs, stay as written.
    """

    def element(found: re.Match[str]) -> str:
        tag = found.group("tag")
        if tag is None:
            return found.group(0)

        def attribute(link: re.Match[str]) -> str:
            value = html.unescape(link.group("link"))
            if not is_local(value):
                return link.group(0)
            new = html.escape(replace(tag.lower(), value), quote=True)
            return f"{link.group('name')}{link.group('quote')}{new}{link.group('quote')}"

        return _LINK.sub(attribute, found.group(0))

    return _ELEMENT.sub(element, film)


def _script_text(source: str) -> str:
    """`source` safe between <script> and </script>."""
    return re.sub(r"</(script)", r"<\\/\1", source, flags=re.IGNORECASE)


def frame_size(film: str) -> tuple[int, int]:
    """The width and height the film's root composition declares, else 1920 by 1080."""
    root = _ROOT.search(film)
    size = dict(_SIZE.findall(root.group(0))) if root else {}
    return int(size.get("width", 1920)), int(size.get("height", 1080))


def player_page(film: str, player_script: str, credits: str) -> str:
    """A page that plays `film` in the HyperFrames player, as large as the
    window allows at the film's own proportions.

    The film goes in the player's `srcdoc`, so its links resolve against the
    page's own address. `f` or a double click toggles full screen.
    """
    found = _TITLE.search(film)
    title = found.group(1).strip() if found else "film"
    # Every "<" escaped: the film cannot end the script that carries it.
    carried = json.dumps(film).replace("<", "\\u003c")
    width, height = frame_size(film)
    return f"""<!doctype html>
<!-- {html.escape(credits)} -->
<html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{title}</title>
<style>
  html, body {{ margin: 0; height: 100%; background: #000; }}
  body {{ display: grid; place-items: center; overflow: hidden; }}
  hyperframes-player {{ width: min(100vw, calc(100vh * {width} / {height})); aspect-ratio: {width} / {height}; }}
</style>
<script>{_script_text(player_script)}</script>
</head><body>
<hyperframes-player controls></hyperframes-player>
<script>
const player = document.querySelector("hyperframes-player");
player.setAttribute("srcdoc", {carried});
const fullScreen = () => document.fullscreenElement
  ? document.exitFullscreen() : document.documentElement.requestFullscreen();
addEventListener("keydown", (event) => {{ if (event.key === "f") fullScreen(); }});
player.addEventListener("dblclick", fullScreen);
</script>
</body></html>
"""
