"""`lumiere skills update` - install the packaged skills into a video project.

Skills belong to the video, under `.agents/skills/`, beside the HyperFrames
skills that `npx hyperframes skills update` installs. Lumiere ships its own
inside the package so a project always gets the skills of the Lumiere it has.
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
