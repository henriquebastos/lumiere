"""`lumiere adopt` - add derived timing to a HyperFrames project.

Lumiere does not create video projects. HyperFrames does, and which kind it is
- explainer, product launch, slideshow, recut - is the producer's choice, made
by picking a workflow. What Lumiere adds afterwards is a timing spine: somewhere
for the recording, and a note in the project's own agent instructions saying
that seconds here are derived rather than typed.

Every project HyperFrames scaffolds already carries an `AGENTS.md`, so ours
appends to it. An earlier version shipped a competing copy in a template
directory, and it silently never arrived.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from lumiere.cli.adopt import LUMIERE_SECTION, adopt


@pytest.fixture
def project(tmp_path: Path) -> Path:
    """What `hyperframes init` leaves behind."""
    (tmp_path / "hyperframes.json").write_text("{}\n")
    (tmp_path / "index.html").write_text('<div id="stage"></div>\n')
    (tmp_path / "AGENTS.md").write_text(
        "# HyperFrames Composition Project\n\n## Skills — USE THESE FIRST\n"
    )
    return tmp_path



def test_the_projects_own_instructions_are_added_to_not_replaced(project):
    """HyperFrames' AGENTS.md routes the agent to the right workflow.

    Overwriting it would cost the project its workflow routing; shipping a
    competing file meant ours was skipped because theirs already existed. So
    append, and keep the note short enough to be worth reading.
    """
    adopt(project)

    text = (project / "AGENTS.md").read_text()
    assert "# HyperFrames Composition Project" in text  # theirs, intact
    assert "## Skills — USE THESE FIRST" in text
    assert LUMIERE_SECTION in text  # ours, after it


def test_adopting_twice_does_not_repeat_the_section(project):
    """Running it again on a project already using Lumiere is a no-op."""
    adopt(project)
    adopt(project)

    assert (project / "AGENTS.md").read_text().count(LUMIERE_SECTION) == 1


def test_a_directory_that_is_not_a_hyperframes_project_is_refused(tmp_path):
    """There is nothing to override.

    Lumiere adjusts timing inside a composition; without one there is no
    timeline to adjust, and creating the project is not Lumiere's job.
    """
    with pytest.raises(ValueError, match="hyperframes init"):
        adopt(tmp_path)
