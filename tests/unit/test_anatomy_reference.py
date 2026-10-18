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

from wardrobe.anatomy import correctives as CR
from wardrobe.anatomy import creases as C
from wardrobe.anatomy import reference as R
from wardrobe.anatomy import regions as G
from wardrobe.anatomy import rig
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


def test_t_pose_is_the_bind_a_viewer_undoes_exactly():
    # SA2. The viewer's skinning, lowering the arms to the angle she was sculpted at, must give the
    # sculpt back. The old yes/no binding left a ridge over each shoulder there: 676 folds.
    V, T, J = body("ref-f-median", 1)
    P, PJ = t_pose(V, J)
    back = rig.pose_surface(P, rig.bone_positions(PJ), rig.sculpted_pose(J))
    assert np.abs(back - V).max() < 1e-9
    for side, sign in (("l", 1.0), ("r", -1.0)):
        assert PJ[f"joint-{side}-hand"][1] == pytest.approx(PJ[f"joint-{side}-shoulder"][1], abs=1e-6)
        assert sign * PJ[f"joint-{side}-hand"][0] > sign * J[f"joint-{side}-hand"][0]
    # Only what the arms carry moves: the rest of her is bound in the pose she was measured in.
    W = rig.dense_weights(V.shape[0])
    still = W[:, [rig.VRM_BONES.index(b) for s in ("left", "right") for b in rig.ARM_CHAIN[s]]].sum(axis=1) == 0
    assert still.sum() > V.shape[0] // 2 and np.abs(P[still] - V[still]).max() < 1e-9


def test_rig_is_makehumans_cc0_weights_on_the_vrm_bones():
    prov = json.loads((ANATOMY / "makehuman-rig-provenance.json").read_text())
    assert "CC0" in prov["licence"] and prov["codeUsed"].startswith("none")
    assert len(prov["commit"]) == 40 and all(len(h) == 64 for h in prov["files"].values())
    import hashlib

    assert hashlib.sha256((ANATOMY / "makehuman-rig.npz").read_bytes()).hexdigest() == prov["npzSha256"]
    # Each MakeHuman bone goes to the VRM bone on its head's joint, or to its parent's.
    assert rig.vrm_bone_of("upperarm01.L") == rig.vrm_bone_of("upperarm02.L") == "leftUpperArm"
    assert rig.vrm_bone_of("shoulder01.R") == rig.vrm_bone_of("clavicle.R") == "rightShoulder"
    assert rig.vrm_bone_of("spine01") == "upperChest" and rig.vrm_bone_of("finger3-2.L") == "leftHand"
    assert rig.vrm_bone_of("toe2-1.R") == "rightToes" and rig.vrm_bone_of("root") == "hips"
    names = [str(n) for n in rig._rig()["bone_names"]]
    for bone in names:
        target = rig.vrm_bone_of(bone)
        if bone.endswith(".L"):
            assert not target.startswith("right"), bone
        if bone.endswith(".R"):
            assert not target.startswith("left"), bone


@pytest.mark.parametrize("levels", [0, 1, 2])
def test_skin_weights_are_four_continuous_and_whole(levels):
    V, T, J = body("ref-f-median", levels)
    joints, weights = rig.skin(V.shape[0])
    assert joints.shape == weights.shape == (V.shape[0], 4)
    assert np.allclose(weights.sum(axis=1), 1.0) and weights.min() >= 0.0
    # Spread fingers once stayed bound to her trunk and drew strips out to the T-pose: her whole
    # forearm and hand are arm, and nothing of her legs is.
    W = rig.dense_weights(V.shape[0])
    for side, sign in (("left", 1.0), ("right", -1.0)):
        arm = W[:, [rig.VRM_BONES.index(b) for b in rig.ARM_CHAIN[side]]].sum(axis=1)
        s = side[0]
        beyond = (sign * V[:, 0] > sign * J[f"joint-{s}-elbow"][0]) & (V[:, 1] > 0.9)
        assert beyond.sum() > 50 and arm[beyond].min() > 0.999
        assert arm[V[:, 1] < 0.6].max() == 0.0


def _jump_added_by_the_cut(levels: int) -> tuple[float, float]:
    """The largest change across an edge that cutting to four influences adds to MakeHuman's weights,
    for the cut the rig makes and for keeping the four largest as they are."""
    V, T, _ = body("ref-f-median", levels)
    raw = rig.base_weights()
    for step in TM.subdivision(levels):
        out = np.zeros((step.count, raw.shape[1]))
        np.add.at(out, step.rows, raw[step.cols] * step.vals[:, None])
        raw = out
    top = np.argsort(-raw, axis=1)[:, :4]
    kept = np.take_along_axis(raw, top, axis=1)
    largest = np.zeros_like(raw)
    np.put_along_axis(largest, top, kept / kept.sum(axis=1, keepdims=True), axis=1)
    E = np.unique(np.sort(np.concatenate([T[:, [0, 1]], T[:, [1, 2]], T[:, [2, 0]]]), axis=1), axis=0)

    def jump(W):
        added = W - raw
        return float(np.abs(added[E[:, 0]] - added[E[:, 1]]).max())

    return jump(rig.dense_weights(V.shape[0])), jump(largest)


def test_cut_to_four_influences_is_continuous():
    # SA2. Keeping the four largest weights made a bone's weight jump from a few percent to nothing
    # between neighbours where five bones meet (the base of her neck), and the solved T-pose
    # kinked there: 88 folds. A continuous cut's jumps shrink as the mesh is refined; a
    # discontinuous one's do not.
    ours_1, largest_1 = _jump_added_by_the_cut(1)
    ours_2, largest_2 = _jump_added_by_the_cut(2)
    assert ours_2 < 0.7 * ours_1 and ours_2 < largest_2
    assert largest_2 > 0.9 * largest_1  # the discontinuity the old cut had, for contrast


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
    # AN-A2: the outer contour is now modelled (the pelvic outlet); finer detail is stated as not.
    assert set(R.UNMODELLED) == {"externalGenitalDetail", "nippleAreola", "softTissue"}
    assert "not built" in R.UNMODELLED["externalGenitalDetail"]
    assert "pelvicOutlet" in R.ANATOMY["modelled"] and "pelvicOutlet" in R.ANATOMY["approximated"]
    assert R.reference_bodies()["unmodelled"] == R.UNMODELLED


# -- 8. VRM --------------------------------------------------------------------------------------
@pytest.mark.slow
def test_reference_vrm_builds_and_states_what_it_is():
    from wardrobe.vrm.document import GltfDocument
    from wardrobe.vrm.inspect import inspect_document

    doc = GltfDocument.from_bytes(build_reference_vrm("ref-f-median", correctives=False))
    from wardrobe.vrm.inspect import VrmSpec

    assert inspect_document(doc).spec == VrmSpec.VRM1
    extras = doc.gltf["extras"]["wardrobeAnatomy"]
    assert extras["sizeId"] == "ref-f-median" and extras["unmodelled"] == R.UNMODELLED
    policy = json.loads((R.ROOT / "assets" / "calibration" / "policy.json").read_text())
    assert all(policy["bodies"][s]["depictsAdult"] for s in SIZES)


def test_reference_vrm_is_bound_with_the_rig_and_carries_correctives_sparse():
    from wardrobe.anatomy.posecheck import read_vrm
    from wardrobe.anatomy.vrm import _add_correctives
    from wardrobe.vrm.document import GltfDocument

    V, _, J, _ = R.reference_body("ref-f-median")  # with her pelvic outlet (AN-A2), as the VRM is
    doc = GltfDocument.from_bytes(build_reference_vrm("ref-f-median", correctives=False))
    bound, (joints, weights), _ = read_vrm(doc.to_bytes())
    P, _ = t_pose(V, J)
    assert np.abs(bound - P).max() < 1e-5  # float32
    ours_j, ours_w = rig.skin(V.shape[0])
    assert np.array_equal(joints, ours_j) and np.allclose(weights, ours_w, atol=1e-6)
    # A corrective moving a few vertices costs a few vertices: stored sparse, read back dense.
    delta = np.zeros_like(V, dtype=np.float32)
    delta[[10, 2000, 5000]] = [[0.001, 0.0, 0.0], [0.0, -0.002, 0.0], [0.0, 0.0, 0.003]]
    fake = CR.Corrective("corrective.leftArm.test", "leftUpperArm", (1.0, 0.0, 0.0), [[47, 0], [67.6, 1]],
                         [[0, 1]], delta)
    _add_correctives(doc, [fake])
    back = GltfDocument.from_bytes(doc.to_bytes())
    mesh = back.meshes[next(n for n in back.nodes if n.get("name") == "BodyMesh")["mesh"]]
    target = mesh["primitives"][0]["targets"][-1]["POSITION"]
    assert back.gltf["accessors"][target]["sparse"]["count"] == 3
    assert np.array_equal(back.read_accessor(target), delta)
    assert mesh["extras"]["targetNames"][-1] == "corrective.leftArm.test"


# -- 9. shoulders (SA1-SA3) ------------------------------------------------------------------------
@cache
def posed_setup(size_id: str):
    V, T, J = body(size_id)
    P, PJ = t_pose(V, J)
    return V, T, J, P, rig.bone_positions(PJ)


#: The most folds sharper than 60 degrees within 17 cm of the shoulders, per test pose, on any size,
#: under skinning alone: the four sizes measured 0, 40, 0, 2, 28, 28, 18 and 0 (tools/anatomy/
#: render_reference.py --metrics). The sculpt has none; the old yes/no binding had 600-790 in every
#: pose but the T. Where the armpit closes (lowered, swung back, raised in front of her) the
#: correctives take the contact; these limits are the skinning they start from.
FOLD_LIMIT = {
    "sculpted": 0, "t-pose": 0, "raised-sideways": 2, "elbow-bent": 2, "raised-forward": 30,
    "relaxed": 45, "lowered": 30, "rotated-back": 20,
}
#: Poses where the armpit closes and skinning alone lets the arm pass into her (front or back).
CLOSING = ("relaxed", "lowered", "rotated-back", "raised-forward")


@pytest.mark.slow
@pytest.mark.parametrize("size_id", SIZES)
def test_shoulders_hold_their_shape_in_every_test_pose(size_id):
    from wardrobe.anatomy.posecheck import ShoulderRegion

    V, T, J, P, bind = posed_setup(size_id)
    region = ShoulderRegion(V, T, J)
    for name in rig.TEST_POSES:
        closes = name in CLOSING
        report = region.report(rig.pose_surface(P, bind, rig.named_pose(name, J)), crossings=not closes)
        assert report["folds"] <= FOLD_LIMIT[name], (name, report["folds"])
        if not closes:
            assert report["crossings"]["total"] == 0, (name, report["crossings"])
        if name == "sculpted":
            assert report["deviationMm"]["max"] < 1e-6


def test_corrective_driver_is_off_where_skinning_is_right():
    # Driven at her sculpted angle, in the T-pose or raised sideways, no corrective may act: those
    # are the poses skinning gets right (the sculpt exactly), and a corrective there would only move her.
    V, _, J = body("ref-f-median", 0)
    fake = [
        CR.Corrective(f"corrective.{s}Arm.{k['name']}", f"{s}UpperArm", (sign, 0.0, 0.0),
                      [[float(np.degrees(rig.arm_angles(J)["left"])) if x == "sculpted" else x, y]
                       for x, y in k["keys"]], k["swingKeys"], np.zeros((1, 3), np.float32))
        for k in CR.KEYS for s, _, sign in CR.SIDES
    ]
    for name in ("sculpted", "t-pose", "raised-sideways"):
        pose = rig.named_pose(name, J)
        assert all(CR.driven_weight(c, pose) == 0.0 for c in fake), name
    # At each key exactly its own target is on, at full weight, on both sides.
    for key in CR.KEYS:
        pose = CR.key_pose(key["down"], key["swing"])
        on = {c.name: CR.driven_weight(c, pose) for c in fake}
        assert all(v == pytest.approx(1.0 if c.endswith("." + key["name"]) else 0.0, abs=1e-9)
                   for c, v in on.items()), (key["name"], on)


def test_studio_viewer_drives_what_the_vrm_declares():
    js = (R.ROOT / "apps" / "studio" / "js" / "viewer.js").read_text()
    for needle in ("extras?.wardrobeAnatomy?.correctives", "swingKeys", "'upperChest'", "morphTargetInfluences"):
        assert needle in js, needle


@pytest.mark.slow
@pytest.mark.parametrize("key", ["relaxed", "back"])
def test_corrective_resolves_the_armpit_at_its_key(key):
    from wardrobe.anatomy.posecheck import ShoulderRegion

    made, reports = CR.build("ref-f-median", names=(key,))
    assert reports[key]["crossings"] == 0
    assert reports[key]["maxControlDisplacementMm"] < CR.CAP_M * 1000
    V, T, J, P, bind = posed_setup("ref-f-median")
    spec = next(k for k in CR.KEYS if k["name"] == key)
    pose = CR.key_pose(spec["down"], spec["swing"])
    plain = ShoulderRegion(V, T, J, radius=CR.REGION_M).report(rig.pose_surface(P, bind, pose))
    driven = ShoulderRegion(V, T, J, radius=CR.REGION_M).report(
        rig.pose_surface(P, bind, pose, morph=CR.driven_morph(made, pose))
    )
    assert plain["crossings"]["armIntoTrunk"] > 50  # skinning alone lets the armpit pass through
    assert driven["crossings"]["total"] == 0
    assert driven["folds"] <= plain["folds"] + 10
    if key == "relaxed":
        # Between keys a corrective must never be worse than skinning. Held on past its key, the
        # relaxed corrective made two sizes worse with the arms lower (full: 572 -> 650 crossings).
        region = ShoulderRegion(V, T, J, radius=CR.REGION_M)
        for down in (75.0, 82.0):
            lower = CR.key_pose(down)
            plain_x = region.report(rig.pose_surface(P, bind, lower))["crossings"]["total"]
            driven_x = region.report(rig.pose_surface(P, bind, lower, morph=CR.driven_morph(made, lower)))
            assert driven_x["crossings"]["total"] <= plain_x, (down, driven_x["crossings"], plain_x)
