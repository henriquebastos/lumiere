"""Lumiere knows no video and assumes no layout.

Every command operates on the files it is given or the markup names. The
package must not name a video, reach for a repository root, read a `.env`
file, look in the working directory for a file nobody named, or assume a
folder such as `in/` or `out/`: where things live is the project's choice.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

PACKAGE = Path(__file__).resolve().parents[1] / "src/lumiere"

FORBIDDEN = {
    "a video directory": re.compile(r"videos/"),
    "a repository root": re.compile(r"repository root|repo root"),
    "a parent of the package": re.compile(r"parents\[[2-9]\]"),
    "a .env file": re.compile(r'"\.env"'),
    "the working directory": re.compile(r"Path\.cwd\(\)(?! if str\(sequence\) == STREAM)"),
    "a conventional folder": re.compile(r'"(in|out|narration|assets|takes)/?"'),
    "a conventional file name": re.compile(r'"(timeline|syllables|pronunciations|edit)\.json"'),
}


@pytest.mark.parametrize("reason", sorted(FORBIDDEN))
def test_the_package_never_points_outside_the_project_it_is_given(reason: str):
    pattern = FORBIDDEN[reason]
    offenders = [
        str(path.relative_to(PACKAGE))
        for path in PACKAGE.rglob("*.py")
        if pattern.search(path.read_text())
    ]
    assert offenders == [], f"{reason} is named in {offenders}"
