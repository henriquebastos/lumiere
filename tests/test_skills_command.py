"""`lumiere skills update` - install the packaged skills into a video project.

Skills belong to the video, under `.agents/skills/`, beside the project's
HyperFrames skills. Lumiere ships its own inside the package so a project
always gets the skills of the Lumiere it has.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from lumiere.cli.main import main
from lumiere.cli.skills import packaged_skills, update_skills


def test_lumiere_ships_its_skill():
    assert packaged_skills() == ["lumiere"]


def test_updating_installs_every_packaged_skill_with_its_references(tmp_path: Path):
    report = update_skills(tmp_path)

    assert report.installed == ("lumiere",)
    skill = tmp_path / ".agents/skills/lumiere"
    assert (skill / "SKILL.md").read_text().startswith("---\nname: lumiere\n")
    assert (skill / "references/anchoring.md").is_file()
    assert (skill / "references/driving-studio.md").is_file()


@pytest.mark.parametrize("filename", [
    "SKILL.md",
    "references/anchoring.md",
    "references/driving-studio.md",
])
def test_installed_instructions_do_not_use_npm_launchers(tmp_path: Path, filename: str):
    update_skills(tmp_path)

    instructions = (tmp_path / ".agents/skills/lumiere" / filename).read_text()
    assert "npx " not in instructions
    assert "npm i " not in instructions
    assert "pnpm dlx hyperframes " not in instructions


@pytest.mark.parametrize("filename", [
    "README.md",
    "SKILL.md",
    "references/driving-studio.md",
])
def test_command_guides_preserve_project_version_selection(tmp_path: Path, filename: str):
    update_skills(tmp_path)
    if filename == "README.md":
        path = Path(__file__).resolve().parents[1] / filename
    else:
        path = tmp_path / ".agents/skills/lumiere" / filename
    instructions = " ".join(path.read_text().split())

    assert "project scripts first" in instructions
    assert "installed local dependency" in instructions
    assert "no local dependency" in instructions
    assert "explicit version selector" in instructions
    assert "pnpm exec hyperframes" in instructions
    assert "pnpm dlx hyperframes@<version>" in instructions
    assert "Use `@latest` only when the project permits latest." in instructions
    assert "Do not replace a missing local installation with dlx." in instructions
    assert "pnpm dlx hyperframes " not in instructions


def test_anchor_review_routes_preview_to_the_version_aware_guide(tmp_path: Path):
    update_skills(tmp_path)
    instructions = (tmp_path / ".agents/skills/lumiere/references/anchoring.md").read_text()
    review = instructions.split("## Review\n", 1)[1].split("\n## ", 1)[0]

    assert "command selection" in review
    assert "driving-studio.md" in review
    assert "pnpm dlx" not in review


def test_updating_replaces_a_stale_copy_and_leaves_other_skills_alone(tmp_path: Path):
    stale = tmp_path / ".agents/skills/lumiere"
    stale.mkdir(parents=True)
    (stale / "SKILL.md").write_text("old\n")
    (stale / "leftover.md").write_text("gone after update\n")
    other = tmp_path / ".agents/skills/hyperframes/SKILL.md"
    other.parent.mkdir(parents=True)
    other.write_text("theirs\n")

    update_skills(tmp_path)

    assert "name: lumiere" in (stale / "SKILL.md").read_text()
    assert not (stale / "leftover.md").exists()
    assert other.read_text() == "theirs\n"


def test_the_command_reports_what_it_installed(tmp_path: Path, capsys):
    assert main(["skills", "update", str(tmp_path)]) == 0

    assert capsys.readouterr().out == "installed .agents/skills/lumiere\n"
    assert (tmp_path / ".agents/skills/lumiere/SKILL.md").is_file()


def test_a_missing_project_is_bad_input(tmp_path: Path, capsys):
    with pytest.raises(SystemExit) as exit_info:
        main(["skills", "update", str(tmp_path / "nowhere")])

    assert exit_info.value.code == 2
    assert "no such directory" in capsys.readouterr().err
