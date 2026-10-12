"""`lumiere skills` - install Lumiere's Agent Skills into a video project.

Skills belong to the video, not to the machine: an agent working in a project
finds them under `<project>/.agents/skills/`, next to the HyperFrames skills
that `npx hyperframes skills update` puts there. Lumiere ships its skills
inside the package, so `lumiere skills update` always installs the skills of
the Lumiere that is installed, and a project upgraded to a newer Lumiere
refreshes its skills the same way.
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from importlib import resources
from pathlib import Path

SKILLS_ROOT = ".agents/skills"


@dataclass(frozen=True)
class SkillsReport:
    """What `skills update` wrote."""

    project: Path
    installed: tuple[str, ...]


def packaged_skills() -> list[str]:
    """The names of the skills Lumiere ships."""
    root = resources.files("lumiere") / "skills"
    return sorted(
        entry.name for entry in root.iterdir()
        if entry.is_dir() and (entry / "SKILL.md").is_file()
    )


def update_skills(project: Path) -> SkillsReport:
    """Copy every packaged skill into `<project>/.agents/skills/<name>/`,
    replacing what was there. Other skills in the directory are untouched."""
    if not project.is_dir():
        raise ValueError(f"{project}: no such directory")
    target_root = project / SKILLS_ROOT
    target_root.mkdir(parents=True, exist_ok=True)
    installed = []
    for name in packaged_skills():
        source = resources.files("lumiere") / "skills" / name
        target = target_root / name
        if target.exists():
            shutil.rmtree(target)
        with resources.as_file(source) as source_path:
            shutil.copytree(source_path, target)
        installed.append(name)
    return SkillsReport(project=project, installed=tuple(installed))
