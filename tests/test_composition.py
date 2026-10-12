"""Reading anchors out of composition markup and writing seconds back in.

These functions are the boundary between Lumiere's model and the file a
producer actually edits, but they are still pure: markup in, markup out. The
composition is hand-authored and also edited by Studio, so patching must change
the attribute values it owns and nothing else - not whitespace, not attribute
order, not the parts of the file nobody asked about.
"""

from __future__ import annotations

from lumiere.core.anchor import Anchor, FilmAnchor
import pytest

from lumiere.core.compile import Timing, TimingPlan
from lumiere.core.composition import apply_plan, read_anchors


def test_an_element_declares_its_timing_as_words_in_the_markup():
    html = (
        '<div id="card" data-lumiere-start="word:Harbor" data-lumiere-end="word:fine"></div>'
    )

    [card] = read_anchors(html)

    assert card.id == "card"
    assert card.start == Anchor("Harbor")
    assert card.end == Anchor("fine")


def test_the_narration_track_declares_that_it_runs_the_length_of_the_film():
    """The audio track's `data-duration` is the literal that goes stale soonest.

    It is the length of the whole piece, so every cut invalidates it - and it
    has no word to be anchored to. Reading `film:` from the same attribute as
    `word:` keeps the markup uniform: one way to say when something happens.
    """
    html = (
        '<audio id="vo" class="clip" data-hf-id="hf-vo" src="assets/voice/master.mp3"\n'
        '       data-lumiere-start="film:start" data-lumiere-end="film:end"></audio>'
    )

    [track] = read_anchors(html)

    assert track.start == FilmAnchor("start")
    assert track.end == FilmAnchor("end")


def test_an_element_is_identified_by_the_handle_it_already_carries():
    """Nothing new is invented: real compositions already identify everything.

    A frame clip has no `id`, but it does carry `data-composition-id`, which is
    unique and readable. `data-hf-id` is deliberately not consulted - it does
    not exist in authored source at all, because HyperFrames stamps it further
    down the pipeline.
    """
    html = (
        '<audio id="vo" data-lumiere-start="film:start"></audio>\n'
        '<div class="clip" data-composition-id="03-harbor-named" '
        'data-composition-src="frames/03.html" data-lumiere-start="word:Harbor"></div>'
    )

    track, frame = read_anchors(html)

    assert track.id == "vo"
    assert frame.id == "03-harbor-named"


def test_two_elements_sharing_a_handle_stop_the_build():
    """`data-composition-id` points at a frame file, not at this clip.

    Reprise the same frame later in the piece and both clips carry the same
    value, so the second one's seconds would overwrite the first's. Detectable,
    and the fix is one explicit `id`, so it is worth stopping for.
    """
    html = (
        '<div class="clip" data-composition-id="03-harbor-named" '
        'data-lumiere-start="word:Harbor"></div>\n'
        '<div class="clip" data-composition-id="03-harbor-named" '
        'data-lumiere-start="word:Harbor#2"></div>'
    )

    with pytest.raises(ValueError, match="03-harbor-named"):
        read_anchors(html)


def test_a_downstream_stamped_id_is_not_mistaken_for_a_handle():
    """`data-hf-id` ends in "id", and a loose attribute match accepts it.

    It must not count. HyperFrames stamps those downstream, so depending on one
    would make the build succeed on compiled output and fail on the authored
    file it is actually meant to patch.
    """
    html = '<div data-hf-id="hf-card" data-lumiere-start="word:Harbor"></div>'

    with pytest.raises(ValueError, match="no id"):
        read_anchors(html)


def test_an_anchored_element_with_no_handle_at_all_cannot_be_addressed():
    """The id is how a resolved time finds its way back to the element.

    Without one there is nothing to write the seconds onto, and continuing
    would leave the element on whatever literal timing it already carried -
    silently ignoring an anchor the author clearly meant.
    """
    html = '<div class="tile" data-lumiere-start="word:Harbor"></div>'

    with pytest.raises(ValueError, match="id"):
        read_anchors(html)


def test_patching_replaces_the_seconds_and_leaves_the_rest_of_the_file_alone():
    """The producer's file survives the build.

    Compositions are hand-authored and also written by Studio, so a build that
    reformatted them would either lose Studio's edits or produce a diff nobody
    can review. Only the two attributes this module owns may change.
    """
    html = (
        '<div id="root">\n'
        '  <div id="card" data-lumiere-start="word:Harbor"\n'
        '       data-start="9.990" data-duration="1.000" class="tile">Harbor</div>\n'
        "</div>\n"
    )
    plan = TimingPlan(times={"card": Timing(start=3.25, duration=2.5)})

    patched = apply_plan(html, plan)

    assert 'data-start="3.250"' in patched
    assert 'data-duration="2.500"' in patched
    # Everything the module does not own is byte-identical.
    assert patched.replace('data-start="3.250"', 'data-start="9.990"').replace(
        'data-duration="2.500"', 'data-duration="1.000"'
    ) == html


def test_a_freshly_anchored_element_gains_the_attributes_it_did_not_have():
    """Authoring is writing the anchor; the seconds arrive with the build.

    Requiring a placeholder `data-start` before the first build would mean
    typing a number by hand, which is the practice this replaces.
    """
    html = '<div id="card" data-lumiere-start="word:Harbor">Harbor</div>'
    plan = TimingPlan(times={"card": Timing(start=3.25, duration=2.5)})

    patched = apply_plan(html, plan)

    assert 'data-start="3.250"' in patched
    assert 'data-duration="2.500"' in patched
    assert patched.endswith(">Harbor</div>")


def test_adjacent_clips_sharing_a_boundary_serialize_to_the_same_millisecond():
    """Rounding start and duration independently can print clip A's end one
    millisecond past clip B's start — the renderer then sees an overlap that
    does not exist. Endpoints are rounded first; durations are derived."""
    from lumiere.core.compile import Timing, TimingPlan
    from lumiere.core.composition import apply_plan

    html = (
        '<div class="clip" id="a" data-lumiere-start="word:x" data-start="0" data-duration="0"></div>\n'
        '<div class="clip" id="b" data-lumiere-start="word:y" data-start="0" data-duration="0"></div>'
    )
    boundary = 76.33333333333333
    plan = TimingPlan(times={
        "a": Timing(start=75.22666666666667, duration=boundary - 75.22666666666667),
        "b": Timing(start=boundary, duration=1.0),
    })

    out = apply_plan(html, plan)

    import re
    starts = [float(m) for m in re.findall(r'data-start="([\d.]+)"', out)]
    durations = [float(m) for m in re.findall(r'data-duration="([\d.]+)"', out)]
    assert round(starts[0] + durations[0], 3) <= starts[1]
