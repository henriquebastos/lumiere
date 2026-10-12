"""`lumiere feedback` - the producer's review reaching the agent.

Studio's storyboard board writes one batch file when a producer submits frame
comments, and treats it as pending until the agent deletes it. That deletion is
the whole acknowledgement protocol: the board re-reads the file on focus, so a
file that is gone means "applied", and a file that lingers means the agent
never saw it.

The file shape is HyperFrames' contract, not ours - it is written by their
Studio and documented in `hyperframes-core/references/storyboard-format.md`.
Parsing it tolerantly matters for the same reason theirs does: a half-written
file must read as "nothing pending", never as an error that stops a review.
"""

from __future__ import annotations

import json

import pytest

from lumiere.cli.feedback import acknowledge, pending, wait_for

BATCH = {
    "version": 1,
    "pass": "sketch",
    "submitted_at": "2026-08-13T12:04:00Z",
    "comments": [
        {
            "frame": 3,
            "src": "compositions/frames/03-harbor-named.html",
            "title": "Harbor, named",
            "text": "Swap the bar chart for a before/after slider.",
        },
        {"frame": 7, "text": "This one lands too late."},
    ],
}


@pytest.fixture
def project(tmp_path):
    path = tmp_path / ".hyperframes"
    path.mkdir()
    (path / "frame-comments.json").write_text(json.dumps(BATCH))
    return tmp_path


def test_pending_comments_name_the_frame_and_the_file_to_edit(project):
    """An agent needs the path, not just the frame number.

    The board knows which file a frame came from and writes it into the batch;
    passing it through means the revision starts from the right file rather
    than from a guess about numbering.
    """
    batch = pending(project)

    assert batch.pass_name == "sketch"
    assert [c.frame for c in batch.comments] == [3, 7]
    assert batch.comments[0].src == "compositions/frames/03-harbor-named.html"
    assert "before/after slider" in batch.comments[0].text


def test_no_file_means_nothing_is_pending(tmp_path):
    """The common case, and it must not look like a failure."""
    assert pending(tmp_path) is None


def test_a_half_written_file_reads_as_nothing_pending(project):
    """Studio writes this file while the agent may be reading it.

    Treating a torn read as an error would stop a review over a race that
    resolves itself a moment later.
    """
    (project / ".hyperframes" / "frame-comments.json").write_text('{"comm')

    assert pending(project) is None


def test_waiting_returns_a_batch_submitted_while_it_waits(tmp_path):
    """The half that closes the loop.

    Studio's own prompt is a button that copies a sentence for the producer to
    paste into a chat. Waiting on the file instead means a submission reaches
    whoever is revising without the producer having to relay it.
    """
    submitted = []

    def submit_on_second_poll(_seconds):
        submitted.append(1)
        if len(submitted) == 2:
            (tmp_path / ".hyperframes").mkdir()
            (tmp_path / ".hyperframes" / "frame-comments.json").write_text(
                json.dumps(BATCH)
            )

    batch = wait_for(tmp_path, attempts=5, sleep=submit_on_second_poll)

    assert batch is not None
    assert [c.frame for c in batch.comments] == [3, 7]


def test_waiting_gives_up_rather_than_blocking_forever(tmp_path):
    """A wait that never returns is a wedged agent, not a patient one."""
    assert wait_for(tmp_path, attempts=3, sleep=lambda _s: None) is None


def test_acknowledging_removes_the_file_because_that_is_the_receipt(project):
    """Studio decides the feedback was applied by the file being gone.

    Leaving it in place would show the producer their comments as still
    pending, and they would resubmit work the agent had already done.
    """
    assert pending(project) is not None

    acknowledge(project)

    assert pending(project) is None
    assert not (project / ".hyperframes" / "frame-comments.json").exists()
