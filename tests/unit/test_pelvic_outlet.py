"""AN-A2–A7. Her pelvic outlet: a reviewed atlas's surface, fitted to every reference body.

What must hold (docs/ANATOMY_PELVIS.md):

1. the source is what it says: CC BY 4.0, the pinned file, attributed, its changes listed, and the
   derived file is the one recorded;
2. every size carries a fit made on its own surface, and a fit made on another is refused;
3. the fit keeps her: one closed manifold without self-intersection, her crotch where it was, every
   calibrated dimension inside its acceptance bound, left and right alike;
4. it is the anatomy and not the plateau: the bridge between her thighs narrows to a mound;
5. the rig carries it: standing, striding and standing wide nothing crosses; in deep flexion the
   crossings stay within the stated bound;
6. the contact region and the VRM say what the surface is and where it came from.
"""

from __future__ import annotations

import hashlib
import json
import sys
from functools import cache

import numpy as np
import pytest

from wardrobe.anatomy import measure as M
from wardrobe.anatomy import pelvis as P
from wardrobe.anatomy import reference as R
from wardrobe.anatomy import regions as G
from wardrobe.anatomy import rig
from wardrobe.anatomy import topology as TOP
from wardrobe.anatomy.contact import EXTERNAL_GENITAL_REGION
from wardrobe.anatomy.posecheck import PELVIC_CROSSING_LIMIT, PelvicRegion

SIZES = ("ref-f-median", "ref-f-petite", "ref-f-full", "ref-f-tall")
ANATOMY = R.ROOT / "assets" / "anatomy"


@cache
def template(size_id: str):
    return R.reference_body(size_id, pelvic_outlet=False)


@cache
def outlet(size_id: str):
    return R.reference_body(size_id)


# -- 1. source ------------------------------------------------------------------------------------
def test_source_is_a_cc_by_atlas_pinned_attributed_and_its_changes_listed():
    sys.path.insert(0, str(R.ROOT / "tools" / "anatomy"))
    import import_hra

    prov = P.provenance()
    assert prov["licence"] == "CC BY 4.0" and prov["licenceUrl"].endswith("/by/4.0/")
    assert prov["doi"].startswith("https://doi.org/10.48539/")
    assert prov["glbSha256"] == import_hra.GLB_SHA256
    assert hashlib.sha256((ANATOMY / "hra-pelvis.npz").read_bytes()).hexdigest() == prov["npzSha256"]
    # CC BY: credit, a link to the licence, and an indication of what was changed.
    assert "CC BY 4.0" in prov["attribution"] and "Browne" in prov["attribution"]
    assert any("cropped" in c for c in prov["changes"]) and any("fitted" in c for c in prov["changes"])
    assert prov["welded"]["closedManifold"]


def test_the_scan_region_is_what_the_fit_reads():
    V, F, breadth, depth = P.patch()
    assert V.shape[0] == P.provenance()["crop"]["vertices"]
    assert np.linalg.norm(V, axis=1).min() < 0.005  # the crotch point is the origin (on an edge, not a vertex)
    assert 0.3 < breadth < 0.5 and 0.15 < depth < 0.3


# -- 2. a fit per size, refused when stale -------------------------------------------------------
@pytest.mark.parametrize("size_id", SIZES)
def test_every_size_carries_a_fit_made_on_its_own_surface(size_id):
    record = R.reference_bodies()["bodies"][size_id]
    V, _, _ = R.build(record["modifiers"])
    out, status = P.apply(size_id, V)
    assert status == "applied"
    assert not np.array_equal(out, V)


def test_a_fit_made_on_another_surface_is_refused_not_applied():
    record = R.reference_bodies()["bodies"]["ref-f-median"]
    V, _, _ = R.build(record["modifiers"])
    V = V * 1.01  # a recalibrated body
    with pytest.warns(UserWarning, match="fit_pelvis"):
        out, status = P.apply("ref-f-median", V)
    assert status == "stale" and out is V
    with pytest.warns(UserWarning, match="fit_pelvis"):
        _, status = P.apply("no-such-size", V)
    assert status == "missing"


# -- 3. it keeps her --------------------------------------------------------------------------------
@pytest.mark.parametrize("size_id", SIZES)
def test_outlet_is_one_closed_manifold_without_self_intersection(size_id):
    V, T, _, m = outlet(size_id)
    report = TOP.check(V, T, self_intersection=False)
    assert report.closed_manifold and report.components == 1 and report.euler == 2
    near = np.linalg.norm(V - np.asarray(m.landmarks["crotch"]), axis=1) < P.FREE_RADIUS_M + 0.02
    tris = T[near[T].all(axis=1)]
    edges = np.unique(np.sort(np.concatenate([tris[:, [0, 1]], tris[:, [1, 2]], tris[:, [2, 0]]]), 1), axis=0)
    assert TOP.self_intersections(V, tris, edges)[0].size == 0


@pytest.mark.parametrize("size_id", SIZES)
def test_outlet_keeps_her_crotch_and_her_size(size_id):
    before, after = template(size_id)[3], outlet(size_id)[3]
    assert np.allclose(before.landmarks["crotch"], after.landmarks["crotch"], atol=1e-4)
    t, bound = R.targets(size_id), R.acceptance(size_id)
    far = {k: round(after.values[k] - t[k], 1) for k in R.TOLERANCE if abs(after.values[k] - t[k]) > bound[k]}
    assert not far
    # The crotch tape runs through the region and is the dimension that moves; nothing else by a centimetre.
    moved = {k for k in R.TOLERANCE if abs(after.values[k] - before.values[k]) > 10.0}
    assert moved <= {"crotchlengthomphalion"}


@pytest.mark.parametrize("size_id", SIZES)
def test_outlet_is_left_right_symmetric(size_id):
    indices, delta, _ = P.stored()[size_id]
    moved = template(size_id)[0][indices]
    # Each moved vertex's mirror image is a moved vertex too (hm08 is symmetric), and its move mirrors.
    partner = np.empty(indices.size, dtype=np.int64)
    gap_to_mirror = np.empty(indices.size)
    for start in range(0, indices.size, 500):
        mirror = moved[start : start + 500] * [-1.0, 1.0, 1.0]
        d = np.linalg.norm(mirror[:, None, :] - moved[None, :, :], axis=2)
        partner[start : start + 500] = np.argmin(d, axis=1)
        gap_to_mirror[start : start + 500] = d.min(axis=1)
    assert np.median(gap_to_mirror) < 1e-4
    gap = np.linalg.norm(delta[partner] * [-1.0, 1.0, 1.0] - delta, axis=1)
    assert np.percentile(gap, 99) < 0.5e-3


# -- 4. a mound, not a plateau ------------------------------------------------------------------------
def bridge_width(V, T, crotch) -> float:
    """Across her crotch, how wide her surface is within 4 mm below to 12 mm above the crotch point."""
    widths = []
    for dz in (-0.01, 0.0, 0.01):
        pts = np.vstack(M.section_loops(V, T, 2, float(crotch[2]) + dz))
        q = pts[(np.abs(pts[:, 0]) < 0.06) & (pts[:, 1] > crotch[1] - 0.004) & (pts[:, 1] < crotch[1] + 0.012)]
        widths.append(float(np.ptp(q[:, 0])))
    return float(np.mean(widths))


@pytest.mark.parametrize("size_id", SIZES)
def test_the_plateau_between_her_thighs_becomes_a_mound(size_id):
    V0, T, _, m0 = template(size_id)
    V1, _, _, m1 = outlet(size_id)
    assert bridge_width(V0, T, np.asarray(m0.landmarks["crotch"])) > 0.025
    assert bridge_width(V1, T, np.asarray(m1.landmarks["crotch"])) < 0.015


# -- 5. the rig carries it --------------------------------------------------------------------------
def test_the_rig_carries_the_outlet_through_her_leg_poses():
    V, T, J, m = outlet("ref-f-median")
    region = PelvicRegion(V, T, np.asarray(m.landmarks["crotch"]))
    Vb, TJ = rig.t_pose(V, J)
    bind = rig.bone_positions(TJ)
    for pose in rig.LEG_POSES:
        report = region.report(rig.pose_surface(Vb, bind, rig.leg_pose(pose, J)))
        limit = PELVIC_CROSSING_LIMIT.get(pose, 0)
        assert report["crossings"]["total"] <= limit, (pose, report)


# -- 6. named and attributed ---------------------------------------------------------------------
def test_the_contact_region_holds_the_mound():
    V, T, J, m = outlet("ref-f-median")
    labels = G.region_labels(V, m.landmarks, J)
    crotch = np.asarray(m.landmarks["crotch"])
    drawn = P.weights(V, crotch, 1.0, 1.0) > 0.9
    drawn &= V[:, 1] >= crotch[1] - 0.005  # the mound and the mons, not the folds beside it
    assert (labels[drawn] == EXTERNAL_GENITAL_REGION).mean() > 0.9


def test_anatomy_is_stated_modelled_approximated_and_unsupported():
    assert set(R.ANATOMY) == {"modelled", "approximated", "unsupported"}
    assert "pelvicOutlet" in R.ANATOMY["modelled"] and "CC BY 4.0" in R.ANATOMY["modelled"]["pelvicOutlet"]
    assert "pelvicOutlet" in R.ANATOMY["approximated"]
    assert {"externalGenitalDetail", "nippleAreola", "softTissue"} <= set(R.ANATOMY["unsupported"])
    assert R.ANATOMY["unsupported"] == R.UNMODELLED
    assert R.reference_bodies()["anatomy"] == R.ANATOMY


def test_fit_report_records_every_size():
    report = json.loads((ANATOMY / "pelvic-outlet.json").read_text())
    for size_id in SIZES:
        fit = report[size_id]
        assert fit["topology"]["selfIntersections"] == 0 and fit["topology"]["boundaryEdges"] == 0
        assert fit["fit"]["weightedResidualMm"] < 0.5
    assert "CC BY 4.0" in report["source"]["attribution"]
