"""H2. ``briefsOver``: the briefs worn over the suspender straps, as a traditional set is.

The order is the mechanism. Each garment is fitted clear of the layers fitted before it,
so planning the briefs after the straps is what puts them over the straps; nothing in
the fit is special-cased. What must hold:

* off by default, and a plan without it is the plan it always was, to the byte;
* only the briefs move — a bra, the belt, the stockings, the skirt keep their places;
* fitted, every strap vertex under the briefs is inside them, and without the option
  the straps lie over the briefs, as before.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from tests.integration.test_hosiery_pipeline import ROOT, run
from wardrobe.domain.garments import TemplateCatalog
from wardrobe.domain.jobs import JobState
from wardrobe.domain.looks import OutfitRequest
from wardrobe.hosiery.planning import connector_artifact
from wardrobe.pipeline.plan_outfit_stack import plan_outfit_stack

CATALOG = TemplateCatalog.from_directory(ROOT / "assets" / "garment_templates")


def plan(prompt: str, **belt):
    request = OutfitRequest.model_validate({"prompt": prompt, "hosiery": {"type": "sheer"},
                                            "suspenderBelt": {"style": "classic", **belt}})
    return plan_outfit_stack(request, CATALOG)


def names(outfit) -> list[str]:
    return [g.name for g in outfit.garments]


def test_off_by_default_and_the_plan_is_unchanged():
    default, off = plan("black lace briefs + black mini skirt"), plan("black lace briefs + black mini skirt",
                                                                      briefsOver=False)
    assert names(default) == names(off)
    assert names(default).index("Black Lace Tailored Briefs") < names(default).index("Black Suspender Straps")
    # Absent from the design, so the connector (hashed from it) is the one every older look has.
    assert "briefsOver" not in default.hosiery.model_dump_json(by_alias=True, exclude_none=True)
    assert connector_artifact(default).id == connector_artifact(off).id


def test_only_the_briefs_move_to_just_after_the_straps():
    before = names(plan("black lace briefs + black lace bra + black mini skirt"))
    after = names(plan("black lace briefs + black lace bra + black mini skirt", briefsOver=True))
    assert after == [n for n in before if "Briefs" not in n][:4] + ["Black Lace Tailored Briefs"] + [
        "Black Pleated Mini Skirt"]
    assert after.index("Black Suspender Straps") + 1 == after.index("Black Lace Tailored Briefs")


@pytest.mark.parametrize("prompt", ["black thong", "black lace tanga", "black boyshorts"])
def test_any_bottom_that_covers_only_her_hips_is_a_brief(prompt):
    garments = plan(prompt, briefsOver=True).garments
    assert garments[-1].role != "connector" and garments[-2].role == "connector"


def test_without_briefs_it_says_so_and_changes_nothing():
    outfit = plan("black mini skirt", briefsOver=True)
    assert names(outfit) == names(plan("black mini skirt"))
    assert any("needs briefs" in note for note in outfit.notes)


# ----------------------------------------------------------------------
# fitted
# ----------------------------------------------------------------------
def strap_clearance(context) -> np.ndarray:
    """For each strap vertex under the briefs: how far the briefs are outside it, metres.

    Radial distance from her hips' vertical axis; "under" means a brief vertex within
    6 mm of height and 0.05 rad of angle.
    """
    built = {layer.plan.role: layer.mesh for layer in context.built if layer.plan.role == "connector"}
    brief = next(layer.mesh for layer in context.built if "Briefs" in layer.plan.name)
    hips = np.asarray(context.measurements.bone_positions["hips"])

    def cylindrical(points):
        d = np.asarray(points)[:, [0, 2]] - hips[[0, 2]]
        return np.hypot(d[:, 0], d[:, 1]), np.arctan2(d[:, 1], d[:, 0]), np.asarray(points)[:, 1]

    br, ba, by = cylindrical(brief.positions)
    sr, sa, sy = cylindrical(built["connector"].positions)
    gaps = []
    for r, a, y in zip(sr, sa, sy, strict=True):
        near = (np.abs(by - y) < 0.006) & (np.abs(np.angle(np.exp(1j * (ba - a)))) < 0.05)
        if near.sum() >= 2:
            gaps.append(float(np.median(br[near]) - r))
    return np.array(gaps)


@pytest.fixture(scope="module")
def fitted(tmp_path_factory):
    tmp: Path = tmp_path_factory.mktemp("briefs-over")
    out = {}
    for over in (False, True):
        outfit = {"prompt": "black lace briefs", "hosiery": {"type": "sheer"},
                  "suspenderBelt": {"style": "classic", "briefsOver": over}}
        out[over] = run(tmp / str(over), outfit)
    return out


def test_with_briefs_over_the_straps_lie_inside_the_briefs(fitted):
    record, _, context = fitted[True]
    assert record.state is JobState.COMPLETED, record.error
    assert [layer.plan.role for layer in context.built][-1] == "foundation"  # the briefs, last
    gaps = strap_clearance(context)
    assert len(gaps) >= 20, "the straps should pass under the briefs at the hips"
    assert gaps.min() > 0.0005, f"a strap vertex is {-gaps.min() * 1000:.1f} mm outside the briefs"


def test_without_it_the_straps_lie_over_the_briefs_as_before(fitted):
    record, _, context = fitted[False]
    assert record.state is JobState.COMPLETED, record.error
    gaps = strap_clearance(context)
    assert len(gaps) >= 20 and np.median(gaps) < 0.0
