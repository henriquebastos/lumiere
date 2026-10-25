"""HyperFrames' own bundler and player, run through Node.

Lumiere does not bundle a film itself. `bundleToSingleHtml` from
`@hyperframes/core/compiler` inlines the runtime and every composition,
script, style, font, and image of a project into one page, and
`@hyperframes/player` plays that page. This module finds both packages at
the version the project uses and runs the bundler. Nothing is installed in
the project or on the machine: packages the project did not install go to a
temporary directory that is deleted afterwards.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
import tempfile
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

#: The two packages a bundle needs, always at one version.
PACKAGES = ("@hyperframes/core", "@hyperframes/player")
#: The Node script that runs the bundler.
HELPER = Path(__file__).with_name("hyperframes_bundle.mjs")
#: A version npm installs as written, such as 0.8.179; a range is not one.
EXACT_VERSION = re.compile(r"^\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?$")


class MissingTool(Exception):
    """A program or a version is missing: bad input, nothing was run."""


class ToolFailed(RuntimeError):
    """An install or the bundler ran and failed."""


def _last_line(output: str) -> str:
    lines = [line.strip() for line in output.splitlines() if line.strip()]
    return lines[-1] if lines else "no output"


def _manifest(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def project_version(project: Path) -> str | None:
    """The HyperFrames version a project uses: the installed `hyperframes`
    package, else an exact version its package.json asks for, else None."""
    installed = project / "node_modules" / "hyperframes" / "package.json"
    if installed.is_file():
        return _manifest(installed)["version"]
    declared = project / "package.json"
    if not declared.is_file():
        return None
    manifest = _manifest(declared)
    for section in ("dependencies", "devDependencies"):
        wanted = manifest.get(section, {}).get("hyperframes", "")
        if EXACT_VERSION.match(wanted):
            return wanted
    return None


def _installs_both(root: Path) -> bool:
    return all((root / "node_modules" / name / "package.json").is_file() for name in PACKAGES)


@dataclass(frozen=True)
class Toolchain:
    """A directory whose node_modules holds both packages."""

    root: Path

    def package(self, name: str) -> Path:
        return self.root / "node_modules" / name

    def version(self, name: str) -> str:
        return _manifest(self.package(name) / "package.json")["version"]

    def player_script(self) -> str:
        """The player's script build, which defines <hyperframes-player>."""
        player = self.package("@hyperframes/player")
        script = _manifest(player / "package.json")["exports"]["."]["script"]
        return (player / script).read_text(encoding="utf-8")

    def bundle(self, project: Path) -> str:
        """HyperFrames' single-file bundle of `project`, as HTML.

        The bundler's notes, such as an asset too large to inline, go to
        stderr: a bundle that still links a file must not pass in silence.
        """
        run = subprocess.run(
            ["node", str(HELPER), str(self.root), str(project.resolve())],
            capture_output=True, text=True, encoding="utf-8",
        )
        if run.returncode != 0:
            raise ToolFailed(f"{project}: the HyperFrames bundler failed: {_last_line(run.stderr)}")
        if run.stderr.strip():
            sys.stderr.write(run.stderr)
        return run.stdout


def _install(root: Path, version: str) -> None:
    specs = [f"{name}@{version}" for name in PACKAGES]
    if shutil.which("pnpm"):
        command = ["pnpm", "add", "--dir", str(root), "--config.strict-dep-builds=false", *specs]
    elif shutil.which("npm"):
        command = ["npm", "install", "--prefix", str(root), "--no-save", "--no-audit", "--no-fund", *specs]
    else:
        raise MissingTool("pnpm or npm: neither is on the PATH; installing HyperFrames needs one")
    run = subprocess.run(command, capture_output=True, text=True)
    if run.returncode != 0 or not _installs_both(root):
        raise ToolFailed(f"installing HyperFrames {version} failed: {_last_line(run.stderr or run.stdout)}")


@contextmanager
def toolchain(project: Path, version: str | None = None) -> Iterator[Toolchain]:
    """The packages to bundle `project` with.

    An explicit `version` is installed in a temporary directory. Without one,
    the project's own installed packages are used when it has both; else the
    version the project uses is installed temporarily. No version at all is
    bad input: a bundle from another version could differ from the render.
    """
    if shutil.which("node") is None:
        raise MissingTool("node: not on the PATH; the HyperFrames bundler needs Node.js")
    if version is None and _installs_both(project):
        yield Toolchain(project)
        return
    version = version or project_version(project)
    if version is None:
        raise MissingTool(
            f"{project}: no HyperFrames version found in node_modules or package.json; "
            "give --hyperframes VERSION, the version the film renders with"
        )
    with tempfile.TemporaryDirectory(prefix="lumiere-hyperframes-") as temporary:
        root = Path(temporary)
        _install(root, version)
        yield Toolchain(root)
