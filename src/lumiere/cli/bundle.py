"""`lumiere bundle` and `lumiere watch` - play a film outside Studio.

`bundle` writes one HTML file that plays the film with nothing else: HyperFrames'
own bundle of the project, every media file embedded, inside the HyperFrames
player. Audio is Opus at 32 kbps unless `copy` keeps the original bytes;
video and images are always copied.

`watch` serves the same page from the project as it is now. Every reload
bundles the project again, and media is read from the project's files, so a
refresh shows the latest edit and nothing is written anywhere.
"""

from __future__ import annotations

import base64
import mimetypes
import subprocess
import tempfile
from dataclasses import dataclass, field
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlsplit

from lumiere.adapters.hyperframes import Toolchain, ToolFailed
from lumiere.core.bundle import player_page, relink

#: What `--audio` can be: the ffmpeg encoding and the type it is served as.
AUDIO_ENCODINGS = {
    "opus32": (["-c:a", "libopus", "-b:a", "32k", "-f", "webm"], "audio/webm"),
    "copy": None,
}


class MissingMedia(ValueError):
    """A media link names a file the project does not have."""


def media_file(project: Path, link: str) -> Path:
    """The project file a media link names; a link out of the project names none."""
    root = project.resolve()
    path = (root / unquote(urlsplit(link).path).lstrip("/")).resolve()
    if not path.is_relative_to(root) or not path.is_file():
        raise MissingMedia(f"{project}: the film links {link}, which is not a file in the project")
    return path


def _media_type(path: Path) -> str:
    return mimetypes.guess_type(path.name)[0] or "application/octet-stream"


def _encoded(path: Path, audio: str) -> tuple[bytes, str]:
    encoding = AUDIO_ENCODINGS[audio]
    if encoding is None:
        return path.read_bytes(), _media_type(path)
    options, media_type = encoding
    # A file, not a pipe: the muxer writes the duration and seek index only
    # when it can go back, and the runtime seeks every clip.
    with tempfile.TemporaryDirectory(prefix="lumiere-audio-") as temporary:
        encoded = Path(temporary) / "audio"
        run = subprocess.run(
            ["ffmpeg", "-v", "error", "-i", str(path), "-vn", *options, str(encoded)],
            capture_output=True,
        )
        if run.returncode != 0:
            reason = " ".join(run.stderr.decode(errors="replace").split())
            raise ToolFailed(f"{path}: ffmpeg could not encode it: {reason}")
        return encoded.read_bytes(), media_type


def credits(chain: Toolchain) -> str:
    return (
        f"Bundled by Lumiere. Played by @hyperframes/player {chain.version('@hyperframes/player')} "
        f"with the @hyperframes/core {chain.version('@hyperframes/core')} runtime, Apache-2.0."
    )


@dataclass
class BundleReport:
    """What `bundle` wrote, and the files it embedded with their sizes."""

    output: Path
    size: int
    embedded: dict[str, int] = field(default_factory=dict)


def bundle(project: Path, output: Path, chain: Toolchain, audio: str = "opus32") -> BundleReport:
    """Write `output`: the film of `project` in one page, every media file embedded.

    A link to a missing file is refused before anything is written.
    """
    report = BundleReport(output=output, size=0)
    # One file can be both a muted <video> and its <audio>: keyed by both.
    data_urls: dict[tuple[Path, bool], str] = {}

    def embed(tag: str, link: str) -> str:
        path = media_file(project, link)
        key = (path, tag == "audio")
        if key not in data_urls:
            content, media_type = _encoded(path, audio) if tag == "audio" else (
                path.read_bytes(), _media_type(path))
            data_urls[key] = f"data:{media_type};base64,{base64.b64encode(content).decode()}"
            report.embedded[f"{link} ({tag})"] = len(content)
        return data_urls[key]

    page = player_page(relink(chain.bundle(project), embed), chain.player_script(), credits(chain))
    output.write_text(page, encoding="utf-8")
    report.size = len(page.encode())
    return report


def watch_page(project: Path, chain: Toolchain) -> str:
    """The page `watch` serves: the film as it is now, its media left as links."""
    return player_page(chain.bundle(project), chain.player_script(), credits(chain))


class _Watch(BaseHTTPRequestHandler):
    project: Path
    chain: Toolchain

    def log_message(self, format: str, *args: object) -> None:
        pass

    def _send(self, status: int, body: bytes, media_type: str, headers: dict[str, str] | None = None) -> None:
        self.send_response(status)
        self.send_header("Content-Type", media_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        for name, value in (headers or {}).items():
            self.send_header(name, value)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def do_HEAD(self) -> None:
        self.do_GET()

    def do_GET(self) -> None:
        # Only this machine's own names: a page that points its domain at
        # 127.0.0.1 must not read the project's files.
        port = self.server.server_address[1]
        if self.headers.get("Host") not in (f"127.0.0.1:{port}", f"localhost:{port}"):
            self._send(HTTPStatus.FORBIDDEN, b"forbidden\n", "text/plain; charset=utf-8")
            return
        path = unquote(urlsplit(self.path).path)
        if path == "/":
            try:
                page = watch_page(self.project, self.chain)
            except ToolFailed as failed:
                self._send(HTTPStatus.INTERNAL_SERVER_ERROR, f"{failed}\n".encode(), "text/plain; charset=utf-8")
                return
            self._send(HTTPStatus.OK, page.encode(), "text/html; charset=utf-8")
            return
        root = self.project.resolve()
        file = (root / path.lstrip("/")).resolve()
        if not file.is_relative_to(root) or not file.is_file():
            self._send(HTTPStatus.NOT_FOUND, b"not found\n", "text/plain; charset=utf-8")
            return
        self._send_file(file)

    def _send_file(self, file: Path) -> None:
        """The file, or the one byte range asked for: media seeks by range."""
        size = file.stat().st_size
        wanted = self.headers.get("Range", "")
        if not wanted.startswith("bytes=") or "," in wanted:
            self._send(HTTPStatus.OK, file.read_bytes(), _media_type(file), {"Accept-Ranges": "bytes"})
            return
        first, _, last = wanted[len("bytes="):].partition("-")
        try:
            if first:
                start, end = int(first), int(last) if last else size - 1
            else:
                start, end = max(size - int(last), 0), size - 1
        except ValueError:
            self._send(HTTPStatus.OK, file.read_bytes(), _media_type(file), {"Accept-Ranges": "bytes"})
            return
        end = min(end, size - 1)
        if start > end:
            self._send(HTTPStatus.REQUESTED_RANGE_NOT_SATISFIABLE, b"", _media_type(file),
                       {"Content-Range": f"bytes */{size}"})
            return
        with file.open("rb") as media:
            media.seek(start)
            part = media.read(end - start + 1)
        self._send(HTTPStatus.PARTIAL_CONTENT, part, _media_type(file),
                   {"Accept-Ranges": "bytes", "Content-Range": f"bytes {start}-{end}/{size}"})


def watch_server(project: Path, chain: Toolchain, port: int) -> ThreadingHTTPServer:
    """A server on this machine only that plays `project`; port 0 picks a free one."""
    handler = type("Watch", (_Watch,), {"project": project, "chain": chain})
    return ThreadingHTTPServer(("127.0.0.1", port), handler)
