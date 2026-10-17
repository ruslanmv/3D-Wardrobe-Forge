"""RB1–RB5, CB1–CB2. The anatomical reference bodies and the one contact model.

What must hold (docs/ANATOMY_REFERENCE.md):

1. the sources are what they say: CC0 template files hashed and marked, no genital helper geometry,
   ANSUR II women aged 21+, sizes inside the sample (Mahalanobis on the drivers);
2. the template is built right: Catmull-Clark keeps the template's vertices first and closes a
   closed mesh; a body stands on the floor;
3. every size reproduces its record, and is within twice its tolerance on every calibrated
   dimension; the record states which are outside tolerance;
4. a body is one closed manifold of genus 0 with no self-intersection, at rest and T-posed;
5. its landmark vertices agree with detection by the measurer's rules on that body;
6. it has the creases a garment must bridge (gluteal and inframammary folds);
7. the contact body is exact, and its sign agrees with the winding number and with cross-sections;
   it refuses a body without one inside; it labels the region whose anatomy is not modelled;
8. the VRM builds, is T-posed, and says what was not modelled.
"""

from __future__ import annotations

import json
from functools import cache, lru_cache

import numpy as np
import pytest

from wardrobe.anatomy import creases as C
from wardrobe.anatomy import reference as R
from wardrobe.anatomy import regions as G
from wardrobe.anatomy import template as TM
from wardrobe.anatomy import topology as TOP
from wardrobe.anatomy.contact import EXTERNAL_GENITAL_REGION, ContactBody, clearance, closest_on_triangles
from wardrobe.anatomy.vrm import build_reference_vrm, t_pose

SIZES = ("ref-f-median", "ref-f-petite", "ref-f-full", "ref-f-tall")
ANATOMY = R.ROOT / "assets" / "anatomy"


@cache
def body(size_id: str, levels: int = R.LEVELS):
    record = R.reference_bodies()["bodies"][size_id]
    V, T, J = R.build(record["modifiers"], levels)
    return V, T, J


@cache
def measured(size_id: str):
    V, T, J = body(size_id)
    return R.measure_body(V, T, J)


# -- 1. sources --------------------------------------------------------------------------------
def test_template_provenance_is_cc0_and_hashed():
    prov = json.loads((ANATOMY / "makehuman-provenance.json").read_text())
    assert "CC0" in prov["licence"] and prov["codeUsed"].startswith("none")
    assert len(prov["commit"]) == 40
    assert all(len(h) == 64 for h in prov["files"].values())
    import hashlib

    assert hashlib.sha256((ANATOMY / "makehuman-hm08.npz").read_bytes()).hexdigest() == prov["npzSha256"]


def test_no_genital_or_nipple_geometry_is_imported():
    prov = json.loads((ANATOMY / "makehuman-provenance.json").read_text())
    names = list(prov["files"]) + list(prov["jointNames"])
    assert not [n for n in names if "genital" in n or "nipple" in n or "areola" in n]
    assert "helper-genital" in prov["dropped"]
    data = np.load(ANATOMY / "makehuman-hm08.npz")
    assert not [n for n in data["target_names"].tolist() if "genital" in n or "nipple" in n]
    assert int(data["body_count"]) == 13380


def test_sizes_come_from_adult_survey_subjects_inside_the_sample():
    sizes = json.loads((ANATOMY / "reference-sizes.json").read_text())
    assert sizes["source"]["filter"] == "Age >= 21" and sizes["source"]["subjectsUsed"] == 1728
    assert len(sizes["source"]["sha256"]) == 64
    for size_id in SIZES:
        assert sizes["sizes"][size_id]["driverMahalanobis"] <= 3.0
    assert sizes["breastSource"]["licence"] == "CC BY 4.0"


# -- 2. template ---------------------------------------------------------------------------------
def test_catmull_clark_closes_a_cube_and_keeps_its_vertices_first():
    cube = np.array([[x, y, z] for x in (0, 1) for y in (0, 1) for z in (0, 1)], dtype=float)
    quads = np.array([[0, 1, 3, 2], [4, 6, 7, 5], [0, 4, 5, 1], [2, 3, 7, 6], [0, 2, 6, 4], [1, 5, 7, 3]])
    step = TM.catmull_clark(quads, cube.shape[0])
    V = step.apply(cube)
    assert V.shape[0] == 8 + 12 + 6 and step.faces.shape == (24, 4)
    report = TOP.check(V, TM.triangles(step.faces))
    assert report.closed_manifold and report.components == 1 and report.euler == 2
    # The original corners are smoothed inward, toward the centre, but stay first.
    assert np.all(np.linalg.norm(V[:8] - 0.5, axis=1) < np.linalg.norm(cube - 0.5, axis=1))


@pytest.mark.parametrize("levels", [0, 1, 2])
def test_a_body_stands_on_the_floor(levels):
    V, _, J = R.build({}, levels)
    assert abs(float(V[:, 1].min())) < 1e-9
    assert float(J["joint-l-ankle"][1]) > 0.0 and float(J["joint-l-knee"][1]) > 0.4


# -- 3. sizes ------------------------------------------------------------------------------------
@pytest.mark.parametrize("size_id", SIZES)
def test_body_reproduces_its_record(size_id):
    record = R.reference_bodies()["bodies"][size_id]
    m = measured(size_id).values
    for k, v in record["measured"].items():
        assert m[k] == pytest.approx(v, abs=0.05), k


@pytest.mark.parametrize("size_id", SIZES)
def test_body_is_accepted_and_its_misses_are_declared(size_id):
    record = R.reference_bodies()["bodies"][size_id]
    assert record["outsideTolerance"] == R.outside_tolerance(record), "the record must state its misses"
    m, t, bound = measured(size_id).values, R.targets(size_id), R.acceptance(size_id)
    far = {k: round(m[k] - t[k], 1) for k in R.TOLERANCE if abs(m[k] - t[k]) > bound[k]}
    assert not far
    # The drivers have no spread to hide in: they are held to twice their tolerance.
    for k in ("stature", "chestcircumference", "waistcircumference", "buttockcircumference"):
        assert bound[k] == 2 * R.TOLERANCE[k]


# -- 4. topology ---------------------------------------------------------------------------------
@pytest.mark.parametrize("size_id", SIZES)
def test_reference_surface_is_one_closed_manifold(size_id):
    V, T, _ = body(size_id)
    report = TOP.check(V, T, self_intersection=False)
    assert report.closed_manifold and report.components == 1 and report.euler == 2
    assert report.volume_l > 40.0


def test_median_body_has_no_self_intersection_at_rest_or_t_posed():
    V, T, J = body("ref-f-median", 1)
    assert TOP.check(V, T).self_intersections == 0
    P, _ = t_pose(V, J)
    assert TOP.check(P, T).self_intersections == 0


def test_t_pose_moves_only_the_arms():
    V, T, J = body("ref-f-median", 1)
    P, PJ = t_pose(V, J)
    moved = np.linalg.norm(P - V, axis=1) > 1e-9
    assert moved.any()
    for side, sign in (("l", 1.0), ("r", -1.0)):
        assert PJ[f"joint-{side}-hand"][1] == pytest.approx(PJ[f"joint-{side}-shoulder"][1], abs=1e-6)
        assert sign * PJ[f"joint-{side}-hand"][0] > sign * J[f"joint-{side}-hand"][0]
    # Her trunk stays put: nothing inside the arm's fade-in band moved.
    from wardrobe.anatomy.vrm import ARM_INSET_FADE_M, ARM_INSET_M

    inner = np.abs(V[:, 0]) < float(J["joint-l-shoulder"][0]) - ARM_INSET_M - ARM_INSET_FADE_M / 2
    assert not moved[inner].any()


@pytest.mark.parametrize("size_id", SIZES)
def test_whole_arm_and_hand_turn_with_the_arm(size_id):
    # Spread fingers once got part of the arm's turn and the rest stayed bound to her trunk: in a
    # viewer that lowered the arms they drew strips out to the T-pose.
    from wardrobe.anatomy.vrm import arm_weight

    V, _, J = body(size_id, 1)
    for side, sign in (("l", 1.0), ("r", -1.0)):
        beyond = (sign * V[:, 0] > sign * J[f"joint-{side}-shoulder"][0] + 0.12) & (V[:, 1] > 0.9)
        assert beyond.sum() > 1000
        assert np.all(arm_weight(V, J, side)[beyond] == 1.0)
    # ... and nothing of her legs is taken for an arm.
    from wardrobe.anatomy.vrm import arm_mask

    assert not arm_mask(V, J)[V[:, 1] < 0.6].any()


# -- 5. landmarks --------------------------------------------------------------------------------
#: How close a measuring vertex must be to detection on each body (mm). The crotch is held on its
#: height only — the dimension taken there: the crotch's underside is flat front to back, and its
#: "lowest point" slides along it by centimetres between sizes while its height moves by one or two
#: millimetres. The buttock point's "most posterior" is a flat region too, and is held more loosely.
LANDMARK_AGREEMENT_MM = {
    "omphalion": 10.0,
    "buttockPoint": 15.0,
    "bustPointLeft": 10.0,
    "bustPointRight": 10.0,
}
CROTCH_HEIGHT_AGREEMENT_MM = 5.0


@pytest.mark.parametrize("size_id", SIZES)
def test_landmark_vertices_agree_with_detection(size_id):
    V, T, J = body(size_id)
    detected = R.detect_landmarks(V, T, J)
    vertices = R.landmark_vertices()
    for name, limit in LANDMARK_AGREEMENT_MM.items():
        assert np.linalg.norm(V[vertices[name]] - detected[name]) * 1000 <= limit, name
    assert abs(V[vertices["crotch"], 1] - detected["crotch"][1]) * 1000 <= CROTCH_HEIGHT_AGREEMENT_MM


# -- 6. creases ----------------------------------------------------------------------------------
@pytest.mark.parametrize("size_id", SIZES)
def test_body_has_the_folds_a_garment_must_bridge(size_id):
    # Absolute, not against the old fit form: on a form whose leg tube runs up through its trunk's
    # floor, the same measure reads the step between the pieces (58 mm), which is not a fold.
    V, T, J = body(size_id)
    found = C.creases(V, T, measured(size_id).landmarks, J)
    assert found["glutealFold"]["depthMm"] >= 10.0
    assert found["inframammaryFold"]["depthMm"] >= 5.0


def test_concavity_of_a_known_profile():
    h = np.linspace(0, 0.2, 101)
    z = np.where(np.abs(h - 0.1) < 0.02, -0.01, 0.0)  # a 10 mm notch in a straight front
    depth, at = C.concavity(h, z, front=True)
    assert depth == pytest.approx(0.01) and abs(at - 0.1) <= 0.02
    assert C.concavity(h, -((h - 0.1) ** 2), front=True)[0] == pytest.approx(0.0, abs=1e-12)  # convex


# -- 7. contact ----------------------------------------------------------------------------------
@lru_cache(maxsize=1)
def contact():
    V, T, J = body("ref-f-median", 1)
    landmarks = {k: V[i] for k, i in R.landmark_vertices().items()}
    return ContactBody(V, T, labels=G.region_labels(V, landmarks, J)), V, T.reshape(-1, 3), landmarks


def _near_points(n, seed=7):
    cb, V, T, _ = contact()
    rng = np.random.default_rng(seed)
    tri = rng.integers(0, T.shape[0], n)
    p = np.einsum("ij,ijk->ik", rng.dirichlet([1, 1, 1], n), V[T[tri]])
    return p + cb.face_normal[tri] * rng.uniform(-0.015, 0.015, n)[:, None]


def test_contact_distance_is_exact():
    cb, V, T, _ = contact()
    p = _near_points(25)
    q = cb.query(p)
    a, b, c = (V[T[:, k]] for k in range(3))
    for i in range(p.shape[0]):
        cp, _ = closest_on_triangles(np.repeat(p[i][None], T.shape[0], axis=0), a, b, c)
        assert abs(q.distance[i]) == pytest.approx(float(np.linalg.norm(cp - p[i], axis=1).min()), abs=1e-9)


def test_contact_sign_agrees_with_winding_number():
    cb, *_ = contact()
    p = _near_points(40, seed=11)
    d = cb.signed_distance(p)
    keep = np.abs(d) > 2e-4
    w = cb.winding_number(p[keep])
    assert np.array_equal(w > 0.5, d[keep] < 0)


@pytest.mark.parametrize("landmark", ["crotch", "omphalion", "bustPointLeft"])
def test_contact_sign_agrees_with_cross_sections(landmark):
    cb, V, _, lm = contact()
    y = float(lm[landmark][1]) - (0.03 if landmark == "crotch" else 0.0)
    rng = np.random.default_rng(3)
    lo, hi = V.min(axis=0), V.max(axis=0)
    pts = np.column_stack(
        [rng.uniform(lo[0], hi[0], 3000), np.full(3000, y), rng.uniform(lo[2], hi[2], 3000)]
    )
    d = cb.signed_distance(pts)
    near = np.isfinite(d) & (np.abs(d) > 2e-4)
    assert near.sum() > 100
    assert np.array_equal(cb.section_inside(pts[near], 1, y - 1e-6), d[near] < 0)


def test_contact_offset_is_a_separate_collision_surface():
    V, T, _ = body("ref-f-median", 1)
    p = _near_points(50, seed=5)
    plain = ContactBody(V, T).signed_distance(p)
    offset = ContactBody(V, T, offset_m=0.002).signed_distance(p)
    ok = np.isfinite(plain)
    assert np.allclose(offset[ok], plain[ok] - 0.002)


def test_contact_body_refuses_the_old_fit_form():
    from wardrobe.vrm.fashion_body import build_fit_form_mesh, fit_form, positions_for

    form = fit_form("fit-form-a-misses")
    mesh = build_fit_form_mesh(form, positions_for(form))
    with pytest.raises(ValueError, match="one closed manifold"):
        ContactBody(np.asarray(mesh.positions), np.asarray(mesh.indices).reshape(-1, 3))


def test_regions_partition_her_and_name_the_unmodelled_one():
    cb, V, _, lm = contact()
    names, counts = np.unique(cb.labels, return_counts=True)
    assert set(names) == set(G.REGIONS) and counts.sum() == V.shape[0]
    genital = V[cb.labels == EXTERNAL_GENITAL_REGION]
    assert np.abs(genital[:, 0]).max() < G.GENITAL_HALF_WIDTH_M
    assert genital[:, 1].min() >= lm["crotch"][1] - 0.006 and genital[:, 1].max() < lm["omphalion"][1]
    # A sheet laid under her crotch reports contact in that region, by name.
    x, z = np.meshgrid(np.linspace(-0.02, 0.02, 9), np.linspace(-0.01, 0.03, 9))
    sheet = np.column_stack(
        [x.ravel(), np.full(x.size, lm["crotch"][1] - 0.004), z.ravel() + lm["crotch"][2]]
    )
    quads = np.array([[i * 9 + j, i * 9 + j + 1, (i + 1) * 9 + j + 1] for i in range(8) for j in range(8)])
    report = clearance(cb, sheet, quads, spacing=0.003)
    assert EXTERNAL_GENITAL_REGION in report["byRegion"]


def test_unmodelled_anatomy_is_stated():
    assert set(R.UNMODELLED) == {"externalGenitalAnatomy", "nippleAreola", "softTissue"}
    assert "Not modelled" in R.UNMODELLED["externalGenitalAnatomy"]
    assert R.reference_bodies()["unmodelled"] == R.UNMODELLED


# -- 8. VRM --------------------------------------------------------------------------------------
@pytest.mark.slow
def test_reference_vrm_builds_and_states_what_it_is():
    from wardrobe.vrm.document import GltfDocument
    from wardrobe.vrm.inspect import inspect_document

    doc = GltfDocument.from_bytes(build_reference_vrm("ref-f-median"))
    from wardrobe.vrm.inspect import VrmSpec

    assert inspect_document(doc).spec == VrmSpec.VRM1
    extras = doc.gltf["extras"]["wardrobeAnatomy"]
    assert extras["sizeId"] == "ref-f-median" and extras["unmodelled"] == R.UNMODELLED
    policy = json.loads((R.ROOT / "assets" / "calibration" / "policy.json").read_text())
    assert all(policy["bodies"][s]["depictsAdult"] for s in SIZES)
