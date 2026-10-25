"""`lumiere bundle` and `lumiere watch`: the film outside Studio, unchanged.

A fake pair of HyperFrames packages stands in for the real ones: its
"bundler" returns the project's index.html with a marker, so a test can see
what the real bundler would be handed and what Lumiere did after it. No test
reaches the network.
"""

from __future__ import annotations

import base64
import json
import re
import shutil
import signal
import subprocess
import sys
import threading
import urllib.error
import urllib.request
from pathlib import Path

import pytest

from lumiere.adapters.hyperframes import Toolchain, project_version
from lumiere.cli.bundle import watch_server
from lumiere.cli.main import main
from lumiere.core.bundle import frame_size, player_page, relink

needs_node = pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")
needs_ffmpeg = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg not installed")

FAKE_COMPILER = """
import { readFileSync } from "node:fs";
import { join } from "node:path";
export async function bundleToSingleHtml(project) {
  const index = readFileSync(join(project, "index.html"), "utf8");
  if (index.includes("BREAK")) throw new Error("the composition does not parse");
  console.log("a bundler note");
  return index.replace("</body>", "<script>/* bundled runtime */</script></body>");
}
"""


def fake_packages(root: Path, version: str = "9.9.9") -> None:
    core = root / "node_modules/@hyperframes/core"
    player = root / "node_modules/@hyperframes/player"
    for package in (core, player):
        package.mkdir(parents=True)
    (core / "package.json").write_text(json.dumps(
        {"name": "@hyperframes/core", "version": version,
         "exports": {"./compiler": {"import": "./dist/compiler.js"}}}))
    (core / "dist").mkdir()
    (core / "dist/compiler.js").write_text(FAKE_COMPILER)
    (player / "package.json").write_text(json.dumps(
        {"name": "@hyperframes/player", "version": version,
         "exports": {".": {"script": "./dist/player.global.js"}}}))
    (player / "dist").mkdir()
    (player / "dist/player.global.js").write_text("/* PLAYER */ if (x</script>y) {}")


def tone(path: Path, seconds: float = 0.5) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", f"sine=frequency=440:duration={seconds}",
                    "-ac", "1", str(path)], check=True)


INDEX = """<!doctype html><html><head><title>Demo</title></head><body>
<div id="main" data-composition-id="main" data-width="1080" data-height="1920" data-start="0" data-duration="4">
  <audio id="vo" src="assets/vo.wav" data-start="2" data-duration="1"></audio>
  <video id="clip" src="assets/clip.mp4" poster="assets/still.png" data-start="0"></video>
  <img src="https://example.com/logo.png">
  <script>const fake = '<audio src="assets/not-a-link.wav">';</script>
  <!-- <audio src="assets/commented.wav"> -->
</div>
</body></html>
"""


@pytest.fixture
def project(tmp_path: Path) -> Path:
    root = tmp_path / "film"
    root.mkdir()
    (root / "index.html").write_text(INDEX)
    (root / "assets").mkdir()
    (root / "assets/clip.mp4").write_bytes(b"VIDEO-BYTES")
    (root / "assets/still.png").write_bytes(b"PNG-BYTES")
    fake_packages(root)
    return root


def film_of(page: str) -> str:
    """The film a bundle page hands the player."""
    carried = re.search(r'player\.setAttribute\("srcdoc", (".*?")\);\n', page, re.DOTALL).group(1)
    return json.loads(carried)


def data_of(film: str, element_id: str, attribute: str = "src") -> tuple[str, bytes]:
    tag = re.search(rf'<[a-z]+ id="{element_id}"[^>]*>', film).group(0)
    value = re.search(rf'\s{attribute}="data:([^;]+);base64,([^"]+)"', tag)
    return value.group(1), base64.b64decode(value.group(2))


# -- relink and the page: no Node needed ------------------------------------

def test_relink_replaces_only_local_media_links_outside_scripts_and_comments():
    seen = []

    def replace(tag: str, link: str) -> str:
        seen.append((tag, link))
        return f"EMBEDDED:{link}"

    film = relink(INDEX + '<audio src="assets/a&amp;b.wav">', replace)
    assert seen == [("audio", "assets/vo.wav"), ("video", "assets/clip.mp4"),
                    ("video", "assets/still.png"), ("audio", "assets/a&b.wav")]
    assert 'src="EMBEDDED:assets/vo.wav" data-start="2" data-duration="1"' in film
    assert 'src="https://example.com/logo.png"' in film
    assert "<audio src=\"assets/not-a-link.wav\">" in film
    assert '<audio src="assets/commented.wav">' in film
    assert 'src="EMBEDDED:assets/a&amp;b.wav"' in film


def test_the_page_carries_the_film_unchanged_and_fits_its_proportions():
    film = INDEX.replace("</body>", "<script>x</script></body>")
    page = player_page(film, "/* PLAYER */ a</script>b", "credits 1.2.3")
    assert film_of(page) == film
    assert page.count("</script>") == 2, "neither the player nor the film may end a script"
    assert "a<\\/script>b" in page
    assert "<!-- credits 1.2.3 -->" in page
    assert "aspect-ratio: 1080 / 1920" in page
    assert "<title>Demo</title>" in page


def test_a_film_without_a_declared_size_is_1920_by_1080():
    assert frame_size("<div data-composition-id='x'></div>") == (1920, 1080)


def test_the_project_version_is_the_installed_package_then_an_exact_pin(tmp_path: Path):
    assert project_version(tmp_path) is None
    (tmp_path / "package.json").write_text(json.dumps({"devDependencies": {"hyperframes": "^0.8.0"}}))
    assert project_version(tmp_path) is None, "a range is not a version"
    (tmp_path / "package.json").write_text(json.dumps({"devDependencies": {"hyperframes": "0.8.179"}}))
    assert project_version(tmp_path) == "0.8.179"
    installed = tmp_path / "node_modules/hyperframes"
    installed.mkdir(parents=True)
    (installed / "package.json").write_text(json.dumps({"version": "0.8.180"}))
    assert project_version(tmp_path) == "0.8.180"


# -- bundle ------------------------------------------------------------------

@needs_node
@needs_ffmpeg
def test_bundle_embeds_audio_as_opus_and_copies_video_and_images(project: Path, tmp_path: Path, capsys):
    tone(project / "assets/vo.wav")
    output = tmp_path / "film.html"
    assert main(["bundle", str(project), "-o", str(output)]) == 0
    page = output.read_text()
    film = film_of(page)
    media_type, audio = data_of(film, "vo")
    assert media_type == "audio/webm"
    codec = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "stream=codec_name", "-of", "csv=p=0",
                            "-"], input=audio, capture_output=True).stdout.decode().strip()
    assert codec == "opus"
    assert data_of(film, "clip") == ("video/mp4", b"VIDEO-BYTES")
    assert data_of(film, "clip", "poster") == ("image/png", b"PNG-BYTES")
    assert 'data-start="2" data-duration="1"' in film, "a clip keeps its seconds"
    assert "/* bundled runtime */" in film and "/* PLAYER */" in page
    assert "@hyperframes/player 9.9.9" in page
    assert "a bundler note" not in page
    printed = capsys.readouterr()
    assert printed.out.splitlines()[-1].startswith(f"{output} (")
    assert "a bundler note" in printed.err, "the bundler's notes reach the user"
    duration = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0",
                               "-"], input=audio, capture_output=True).stdout.decode().strip()
    assert float(duration) == pytest.approx(0.5, abs=0.05), "the runtime seeks: the audio must know its length"


@needs_node
@needs_ffmpeg
def test_bundle_copy_embeds_the_original_audio_bytes(project: Path, tmp_path: Path):
    tone(project / "assets/vo.wav")
    output = tmp_path / "film.html"
    assert main(["bundle", str(project), "-o", str(output), "--audio", "copy"]) == 0
    assert data_of(film_of(output.read_text()), "vo") == ("audio/x-wav", (project / "assets/vo.wav").read_bytes())


@needs_node
def test_a_link_to_a_missing_file_writes_nothing(project: Path, tmp_path: Path, capsys):
    output = tmp_path / "film.html"
    assert main(["bundle", str(project), "-o", str(output)]) == 1
    assert "assets/vo.wav, which is not a file in the project" in capsys.readouterr().err
    assert not output.exists()


@needs_node
def test_a_bundler_failure_is_exit_1_with_its_reason(project: Path, tmp_path: Path, capsys):
    (project / "index.html").write_text("BREAK")
    assert main(["bundle", str(project), "-o", str(tmp_path / "film.html")]) == 1
    assert "the composition does not parse" in capsys.readouterr().err


@needs_node
def test_without_a_version_the_command_refuses_in_one_line(tmp_path: Path, capsys):
    (tmp_path / "index.html").write_text(INDEX)
    with pytest.raises(SystemExit) as exit:
        main(["bundle", str(tmp_path), "-o", str(tmp_path / "film.html")])
    assert exit.value.code == 2
    error = capsys.readouterr().err
    assert "--hyperframes VERSION" in error and len(error.splitlines()) == 1


def test_without_node_the_command_refuses_in_one_line(project: Path, tmp_path: Path, monkeypatch, capsys):
    monkeypatch.setenv("PATH", str(tmp_path / "empty"))
    with pytest.raises(SystemExit) as exit:
        main(["bundle", str(project), "-o", str(tmp_path / "film.html"), "--audio", "copy"])
    assert exit.value.code == 2
    assert "node: not on the PATH" in capsys.readouterr().err


@needs_node
@needs_ffmpeg
def test_one_file_as_muted_video_and_as_audio_is_embedded_once_for_each(project: Path, tmp_path: Path):
    movie = project / "assets/av.mp4"
    subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "testsrc=size=64x64:duration=0.5",
                    "-f", "lavfi", "-i", "sine=duration=0.5", "-shortest", "-pix_fmt", "yuv420p", str(movie)],
                   check=True)
    tone(project / "assets/vo.wav")
    (project / "index.html").write_text(INDEX.replace(
        "</div>", '<audio id="av-sound" src="assets/av.mp4"></audio>'
                  '<video id="av-picture" src="assets/av.mp4" muted></video></div>'))
    output = tmp_path / "film.html"
    assert main(["bundle", str(project), "-o", str(output)]) == 0
    film = film_of(output.read_text())
    assert data_of(film, "av-picture") == ("video/mp4", movie.read_bytes())
    assert data_of(film, "av-sound")[0] == "audio/webm"


@needs_node
def test_a_link_out_of_the_project_is_refused(project: Path, tmp_path: Path, capsys):
    (project.parent / "outside.wav").write_bytes(b"x")
    (project / "index.html").write_text(INDEX.replace("assets/vo.wav", "../outside.wav"))
    output = tmp_path / "film.html"
    assert main(["bundle", str(project), "-o", str(output), "--audio", "copy"]) == 1
    assert "../outside.wav, which is not a file in the project" in capsys.readouterr().err
    assert not output.exists()


def test_opus_without_ffmpeg_refuses_in_one_line(project: Path, tmp_path: Path, monkeypatch, capsys):
    monkeypatch.setenv("PATH", str(tmp_path / "empty"))
    with pytest.raises(SystemExit) as exit:
        main(["bundle", str(project), "-o", str(tmp_path / "film.html")])
    assert exit.value.code == 2
    error = capsys.readouterr().err
    assert "ffmpeg: not on the PATH" in error and len(error.splitlines()) == 1


@pytest.mark.parametrize("arguments", [["watch", "--port", "70000"], ["bundle", "-o", "."]])
def test_a_bad_port_or_output_is_a_usage_error(project: Path, arguments: list[str]):
    with pytest.raises(SystemExit) as exit:
        main([arguments[0], str(project), *arguments[1:]])
    assert exit.value.code == 2


def a_path_with(tmp_path: Path, programs: dict[str, str]) -> str:
    """A PATH holding node and ffmpeg, if present, and the given scripts."""
    bin = tmp_path / "bin"
    bin.mkdir()
    for tool in ("node", "ffmpeg"):
        if shutil.which(tool):
            (bin / tool).symlink_to(shutil.which(tool))
    for name, script in programs.items():
        (bin / name).write_text(script)
        (bin / name).chmod(0o755)
    return str(bin)


@needs_node
def test_a_version_the_project_lacks_is_installed_for_the_run_and_removed(tmp_path: Path, monkeypatch):
    project = tmp_path / "film"
    project.mkdir()
    (project / "index.html").write_text(INDEX.replace('<audio id="vo" src="assets/vo.wav"', "<audio"))
    (project / "assets").mkdir()
    (project / "assets/clip.mp4").write_bytes(b"VIDEO-BYTES")
    (project / "assets/still.png").write_bytes(b"PNG-BYTES")
    (project / "package.json").write_text(json.dumps({"devDependencies": {"hyperframes": "1.2.3"}}))
    packages = tmp_path / "packages"
    fake_packages(packages, "1.2.3")
    log = tmp_path / "pnpm.log"
    monkeypatch.setenv("PATH", a_path_with(tmp_path, {"pnpm": f"""#!/bin/sh
echo "$@" > {log}
/bin/cp -R {packages}/node_modules "$3/"
"""}))
    output = tmp_path / "film.html"
    assert main(["bundle", str(project), "-o", str(output), "--audio", "copy"]) == 0
    arguments = log.read_text().split()
    assert arguments[0] == "add" and arguments[-2:] == ["@hyperframes/core@1.2.3", "@hyperframes/player@1.2.3"]
    assert not Path(arguments[2]).exists(), "the temporary packages are removed"
    assert not (project / "node_modules").exists(), "nothing is installed in the project"
    assert "@hyperframes/player 1.2.3" in output.read_text()


@needs_node
@pytest.mark.parametrize("stop", [signal.SIGTERM, signal.SIGHUP, signal.SIGINT])
def test_a_stopped_watch_removes_its_temporary_packages(tmp_path: Path, stop: signal.Signals):
    project = tmp_path / "film"
    project.mkdir()
    (project / "index.html").write_text(INDEX)
    (project / "package.json").write_text(json.dumps({"dependencies": {"hyperframes": "1.2.3"}}))
    packages = tmp_path / "packages"
    fake_packages(packages, "1.2.3")
    log = tmp_path / "pnpm.log"
    path = a_path_with(tmp_path, {"pnpm": f"""#!/bin/sh
echo "$@" > {log}
/bin/cp -R {packages}/node_modules "$3/"
"""})
    watch = subprocess.Popen(
        [sys.executable, "-c", "import sys; from lumiere.cli.main import main; sys.exit(main(sys.argv[1:]))",
         "watch", str(project), "--port", "0"],
        stdout=subprocess.PIPE, text=True, env={"PATH": path},
    )
    assert watch.stdout.readline().startswith(f"watching {project} at http://127.0.0.1:")
    installed = Path(log.read_text().split()[2])
    assert installed.is_dir()
    watch.send_signal(stop)
    assert watch.wait(timeout=10) == 0
    assert not installed.exists()


@needs_node
def test_without_pnpm_or_npm_a_needed_install_refuses_in_one_line(tmp_path: Path, monkeypatch, capsys):
    (tmp_path / "index.html").write_text(INDEX)
    monkeypatch.setenv("PATH", a_path_with(tmp_path, {}))
    with pytest.raises(SystemExit) as exit:
        main(["bundle", str(tmp_path), "-o", str(tmp_path / "film.html"), "--audio", "copy",
              "--hyperframes", "1.2.3"])
    assert exit.value.code == 2
    assert "pnpm or npm: neither is on the PATH" in capsys.readouterr().err


# -- watch -------------------------------------------------------------------

@pytest.fixture
def served(project: Path):
    server = watch_server(project, Toolchain(project), 0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_address[1]}"
    server.shutdown()
    server.server_close()


def fetch(url: str, headers: dict[str, str] | None = None) -> tuple[int, dict[str, str], bytes]:
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=headers or {})) as response:
            return response.status, dict(response.headers), response.read()
    except urllib.error.HTTPError as failed:
        return failed.code, dict(failed.headers), failed.read()


@needs_node
def test_watch_bundles_the_project_again_on_every_reload(project: Path, served: str):
    files_before = sorted(path for path in project.rglob("*"))
    status, headers, body = fetch(served + "/")
    film = film_of(body.decode())
    assert status == 200 and headers["Cache-Control"] == "no-store"
    assert 'src="assets/vo.wav"' in film, "media stays a link to the project's file"
    (project / "index.html").write_text(INDEX.replace("Demo", "Edited"))
    assert "<title>Edited</title>" in fetch(served + "/")[2].decode()
    assert sorted(path for path in project.rglob("*")) == files_before, "watch writes nothing"


@needs_node
def test_watch_serves_project_files_by_byte_range(project: Path, served: str):
    status, headers, body = fetch(served + "/assets/clip.mp4", {"Range": "bytes=2-4"})
    assert (status, body, headers["Content-Range"]) == (206, b"DEO", "bytes 2-4/11")
    status, headers, body = fetch(served + "/assets/clip.mp4", {"Range": "bytes=-3"})
    assert (status, body) == (206, b"TES")
    status, headers, body = fetch(served + "/assets/clip.mp4")
    assert (status, body, headers["Accept-Ranges"]) == (200, b"VIDEO-BYTES", "bytes")
    status, headers, _ = fetch(served + "/assets/clip.mp4", {"Range": "bytes=20-30"})
    assert (status, headers["Content-Range"]) == (416, "bytes */11")
    with urllib.request.urlopen(urllib.request.Request(served + "/assets/clip.mp4", method="HEAD")) as head:
        assert (head.status, head.headers["Content-Length"], head.read()) == (200, "11", b"")


@needs_node
def test_watch_answers_only_this_machines_own_names(served: str):
    port = served.rsplit(":", 1)[1]
    assert fetch(served + "/assets/clip.mp4", {"Host": f"localhost:{port}"})[0] == 200
    assert fetch(served + "/assets/clip.mp4", {"Host": f"attacker.example:{port}"})[0] == 403
    assert fetch(served + "/", {"Host": "attacker.example"})[0] == 403


@needs_node
def test_watch_serves_nothing_outside_the_project(project: Path, served: str):
    (project.parent / "secret.txt").write_text("no")
    assert fetch(served + "/../secret.txt")[0] == 404
    assert fetch(served + "/%2e%2e/secret.txt")[0] == 404
    assert fetch(served + "/missing.wav")[0] == 404


@needs_node
def test_watch_shows_a_bundler_failure_on_the_page(project: Path, served: str):
    (project / "index.html").write_text("BREAK")
    status, _, body = fetch(served + "/")
    assert status == 500 and b"the composition does not parse" in body
