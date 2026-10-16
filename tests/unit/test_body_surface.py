"""BS0–BS5. The body surface, piece by piece, on meshes built here.

What must hold (docs/BODY_SURFACE.md):

1. the geometry is right — signed distance, smoothing that does not shrink her, geodesic
   distance, an RBF that interpolates its landmarks, a blend that never moves what it holds;
2. the server's allowlist is the only door: provenance re-checked, licences allowlisted, the
   capability computed from regions so a profile cannot talk its way out of the adult gate;
3. the gate asks the model's terms first, then the operator, then the declaration;
4. a region is made seamlessly on a dense body, refused on a coarse one, keeps her measurements,
   and never tears a seam; the collision body contains her; the export is valid glTF;
5. XPBD resolves contact without stretching the fabric; masking never hides skin under sheer;
6. nothing changes for a job that asks for none.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pytest

from wardrobe.body_surface import gate
from wardrobe.body_surface import geometry as g
from wardrobe.body_surface.collision import build_envelope, build_state, signed_clearance
from wardrobe.body_surface.contract import BodyMaskPolicy, BodySurfaceRequest, Capability
from wardrobe.body_surface.export import export_morphs
from wardrobe.body_surface.library import BodySurfaceLibrary, LibraryError, load_template
from wardrobe.body_surface.masking import body_mask_policy, worker_mask_policy
from wardrobe.body_surface.regions import MorphTarget, build_regions, girths
from wardrobe.body_surface.surface import SkinPart, skin_parts
from wardrobe.body_surface.xpbd import relax
from wardrobe.domain.jobs import CreateJobRequest
from wardrobe.domain.looks import MaterialPlan
from wardrobe.engines.geometry_checks import body_points
from wardrobe.lingerie.landmarks import BodyLandmarks
from wardrobe.vrm.build import CALIBRATION_BODIES, build_vrm
from wardrobe.vrm.document import GltfDocument
from wardrobe.vrm.inspect import LicenseTerms, inspect_document
from wardrobe.vrm.measure import measure_body

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools" / "body_surface"))
import install_template  # noqa: E402

SHIPPED = BodySurfaceLibrary.from_directory(ROOT / "assets" / "body_surface")


# ---------------------------------------------------------------------------------------------
# meshes built here
# ---------------------------------------------------------------------------------------------
def sphere(r: float = 0.1, nu: int = 48, nv: int = 24) -> tuple[np.ndarray, np.ndarray]:
    pts = [[0, r, 0]]
    for i in range(1, nv):
        th = np.pi * i / nv
        for j in range(nu):
            ph = 2 * np.pi * j / nu
            pts.append([r * np.sin(th) * np.cos(ph), r * np.cos(th), r * np.sin(th) * np.sin(ph)])
    pts.append([0, -r, 0])
    tris = [[0, 1 + (j + 1) % nu, 1 + j] for j in range(nu)]
    for i in range(nv - 2):
        for j in range(nu):
            a, b = 1 + i * nu + j, 1 + i * nu + (j + 1) % nu
            tris += [[a, b, a + nu], [b, b + nu, a + nu]]
    last, base = len(pts) - 1, 1 + (nv - 2) * nu
    tris += [[last, base + j, base + (j + 1) % nu] for j in range(nu)]
    return np.array(pts, dtype=np.float64), np.array(tris, dtype=np.int64)


def torso(radius: float = 0.13, edge: float = 0.01, seam_angle: float = np.pi / 2) -> tuple[np.ndarray, np.ndarray]:
    """An open cylinder 'torso' facing +z, with a duplicated seam column at ``seam_angle``.

    The seam is where a VRoid skin keeps two copies of its vertices; at π/2 it runs straight
    down her front, through the navel region, which is the case that must not tear.
    """
    nu = int(round(2 * np.pi * radius / edge))
    ys = np.arange(0.80, 1.30 + 1e-9, edge)
    angles = seam_angle + 2 * np.pi * np.arange(nu + 1) / nu  # nu+1 columns: the last copies the first
    pts = np.array([[radius * np.cos(a), y, radius * np.sin(a)] for y in ys for a in angles])
    cols = nu + 1
    tris = []
    for i in range(len(ys) - 1):
        for j in range(nu):
            a, b = i * cols + j, i * cols + j + 1
            tris += [[a, a + cols, b], [b, a + cols, b + cols]]
    return pts, np.array(tris, dtype=np.int64)


def marks(radius: float = 0.13) -> BodyLandmarks:
    return BodyLandmarks(
        forward=1.0, centre_x=0.0, crotch_y=0.83, full_hip_y=0.92, high_hip_y=0.98, waist_y=1.05,
        underbust_y={"left": 1.15, "right": 1.15}, centre_front=[[0.8, radius, -radius], [1.3, radius, -radius]],
        sources={"bust": "formula"},
    )


def part(pts: np.ndarray, tris: np.ndarray) -> SkinPart:
    return SkinPart(accessor=0, primitives=[(0, 0)], positions=pts, triangles=tris, material=0)


# ---------------------------------------------------------------------------------------------
# 1. geometry
# ---------------------------------------------------------------------------------------------
def test_signed_distance_and_closest_point_on_a_sphere():
    p, t = sphere()
    grid = g.TriangleGrid(p, t, reach=0.03)
    d = grid.signed_distance(np.array([[0.12, 0, 0], [0.09, 0, 0], [0, 0.105, 0], [0.5, 0, 0]]))
    assert d[0] == pytest.approx(0.02, abs=5e-4) and d[1] == pytest.approx(-0.01, abs=5e-4)
    assert d[2] == pytest.approx(0.005, abs=5e-4) and np.isinf(d[3])


def test_taubin_removes_detail_without_shrinking():
    p, t = sphere()
    noisy = p * (1 + 0.02 * np.cos(np.arange(len(p)) * 1.7))[:, None]
    smooth = g.taubin_smooth(noisy, t, 10)
    assert np.linalg.norm(smooth, axis=1).std() < np.linalg.norm(noisy, axis=1).std() / 2
    assert np.linalg.norm(smooth, axis=1).mean() == pytest.approx(0.1, rel=0.01)


def test_geodesic_distance_runs_along_the_surface():
    p, t = sphere()
    d = g.geodesic_distance(p, g.neighbours(len(p), t), {0: 0.0}, limit=0.3)
    equator = 1 + 11 * 48  # ring 12 of 24: the equator
    assert d[equator] == pytest.approx(np.pi * 0.1 / 2, rel=0.03)
    assert np.linalg.norm(p[equator] - p[0]) < d[equator]  # a chord is shorter than the surface


def test_wendland_is_compact_and_smooth():
    assert g.wendland(np.array([0.0]))[0] == 1.0
    assert g.wendland(np.array([1.0, 1.5]))[0] == 0.0 and g.wendland(np.array([1.5]))[0] == 0.0
    r = np.linspace(0, 1, 200)
    assert np.all(np.diff(g.wendland(r)) <= 1e-12)


def test_rbf_warp_interpolates_its_landmarks():
    src = np.array([[0, 0], [1, 0], [0, 1], [1, 1], [0.5, 0.5]], dtype=float)
    dst = np.array([[0, 0], [2, 0], [0, 2], [2, 2], [1.1, 1.0]])
    assert np.allclose(g.RbfWarp2D(src, dst)(src), dst, atol=1e-8)
    assert np.allclose(g.RbfWarp2D(src[:1], dst[:1] + 0.3)(src[:1]), dst[:1] + 0.3)


def test_laplacian_blend_never_moves_what_it_holds():
    p, t = sphere()
    ring = g.neighbours(len(p), t)
    desired = np.zeros_like(p)
    desired[:60] = 0.01
    out = g.laplacian_blend(desired, ring, np.arange(100), smoothness=2.0)
    assert np.abs(out[100:]).max() == 0.0 and np.abs(out[:100]).max() > 0.005


def test_surface_samples_carry_their_barycentrics():
    p, t = sphere()
    points, tri, bary = g.surface_samples(p, t, 0.005)
    assert np.allclose(g.place(p, t, tri, bary), points) and np.allclose(bary.sum(axis=1), 1)


def test_weld_merges_seam_copies():
    pts, tris = torso()
    owner, welded, wtri = g.weld(pts, tris)
    assert welded.shape[0] < pts.shape[0] and np.allclose(welded[owner], pts)


def test_a_tape_measure_round_a_circle():
    a = np.linspace(0, 2 * np.pi, 400, endpoint=False)
    assert g.convex_perimeter(np.c_[np.cos(a), np.sin(a)]) == pytest.approx(2 * np.pi, rel=1e-3)


# ---------------------------------------------------------------------------------------------
# 2. the allowlist
# ---------------------------------------------------------------------------------------------
def test_the_shipped_library_loads_whole():
    assert SHIPPED.rejected == {}
    caps = {p.id: p.capability for p in SHIPPED.profiles.values()}
    assert caps == {"collision-reference": Capability.BODY_COLLISION, "collision-close-fit": Capability.BODY_COLLISION,
                    "navel-reference": Capability.BODY_SURFACE}
    assert not any(p.capability is Capability.ADULT_BODY_SURFACE for p in SHIPPED.profiles.values())


def test_public_listing_names_no_template_field_or_provenance():
    text = json.dumps(SHIPPED.public())
    assert "field" not in text and "sha256" not in text and "templates/" not in text and "provenance" not in text


def _bump(templates: Path, *, region: str = "test", anchor: str = "navel", license_id: str = "CC0-1.0") -> Path:
    axis = np.linspace(-1, 1, 9)
    u, v = np.meshgrid(axis, axis)
    field = np.zeros((9, 9, 3))
    field[:, :, 0] = 0.002 * np.clip(1 - (u ** 2 + v ** 2), 0, 1) ** 2
    field[0, :] = field[-1, :] = field[:, 0] = field[:, -1] = 0
    return install_template.install(field, template_id=f"{region.lower()}/v1", region=region, anchor=anchor,
                                    radius_m=0.04, license_id=license_id, source="test", author="test",
                                    landmarks={"centre": {"uv": [0, 0]}}, reference_waist_m=0.26,
                                    templates_dir=templates)


def _profile(root: Path, profile_id: str, region: str, template_id: str, capability: str = "body_collision"):
    (root / "profiles").mkdir(parents=True, exist_ok=True)
    (root / "profiles" / f"{profile_id}.json").write_text(json.dumps({
        "schema": "wardrobe.bodySurface.v1", "profileId": profile_id, "capability": capability,
        "regions": {region: {"templateId": template_id}}}))


def test_an_intimate_region_makes_a_profile_adult_whatever_it_claims(tmp_path):
    _bump(tmp_path / "templates", region="chestDetail")
    _profile(tmp_path, "claims-collision", "chestDetail", "chestdetail/v1", capability="body_collision")
    library = BodySurfaceLibrary.from_directory(tmp_path)
    assert library.profiles["claims-collision"].capability is Capability.ADULT_BODY_SURFACE


def test_a_template_edited_after_install_is_refused(tmp_path):
    path = _bump(tmp_path / "templates")
    data = json.loads(path.read_text())
    data["field"][4][4][0] = 0.003
    path.write_text(json.dumps(data))
    with pytest.raises(LibraryError, match="sha256"):
        load_template(path)
    _profile(tmp_path, "uses-it", "test", "test/v1")
    library = BodySurfaceLibrary.from_directory(tmp_path)
    assert "uses-it" not in library.profiles and any("sha256" in r for r in library.rejected.values())


def test_licences_and_scans_are_checked(tmp_path):
    with pytest.raises(SystemExit, match="not allowed"):
        _bump(tmp_path / "templates", license_id="SMPL-X-research")
    path = _bump(tmp_path / "templates")
    data = json.loads(path.read_text())
    data["provenance"]["containsRealPersonScan"] = True
    path.write_text(json.dumps(data))
    with pytest.raises(LibraryError, match="RealPersonScan"):
        load_template(path)


def test_a_profile_may_never_allow_prompt_override(tmp_path):
    (tmp_path / "profiles").mkdir()
    (tmp_path / "profiles" / "bad.json").write_text(json.dumps({
        "schema": "wardrobe.bodySurface.v1", "profileId": "bad", "authorization": {"allowPromptOverride": True}}))
    assert "bad" not in BodySurfaceLibrary.from_directory(tmp_path).profiles


@pytest.mark.parametrize("profile_id", ["../etc/passwd", "https://x.y/t.json", "a b", "UPPER", "a/b/c"])
def test_a_request_names_a_profile_id_and_nothing_else(profile_id):
    with pytest.raises(ValueError):
        BodySurfaceRequest.model_validate({"profileId": profile_id})
    with pytest.raises(ValueError):
        BodySurfaceRequest.model_validate({"profileId": "collision-reference", "templateId": "x"})


def test_jobs_default_to_no_body_surface_and_no_relaxation():
    request = CreateJobRequest.model_validate({"avatar": {"storageKey": "k"}, "outfit": {"prompt": "red dress"}})
    assert request.body_surface is None and request.options.cloth_relaxation == "none"


# ---------------------------------------------------------------------------------------------
# 3. the gate
# ---------------------------------------------------------------------------------------------
VRM0_NO = LicenseTerms(raw={"sexualUssageName": "Disallow"})
VRM1_NO = LicenseTerms(raw={"allowExcessivelySexualUsage": False})
VRM1_YES = LicenseTerms(raw={"allowExcessivelySexualUsage": True})


@pytest.mark.parametrize("terms, enabled, adult, refused_by", [
    (VRM0_NO, True, True, "model-terms"),
    (VRM1_NO, True, True, "model-terms"),
    (VRM1_YES, False, True, "operator-disabled"),
    (VRM1_YES, True, False, "adult-declaration"),
    (VRM0_NO, False, False, "model-terms"),  # the author's no comes first
    (VRM1_YES, True, True, None),
])
def test_the_adult_gate_asks_in_order(terms, enabled, adult, refused_by):
    decision = gate.evaluate(Capability.ADULT_BODY_SURFACE, terms, operator_enabled=enabled, depicts_adult=adult)
    assert decision.allowed is (refused_by is None) and decision.refused_by == refused_by


def test_collision_and_non_intimate_profiles_need_no_adult_gate():
    for capability in (Capability.BODY_COLLISION, Capability.BODY_SURFACE):
        assert gate.evaluate(capability, VRM0_NO, operator_enabled=False, depicts_adult=False).allowed


# ---------------------------------------------------------------------------------------------
# 4. regions, the collision body, the export
# ---------------------------------------------------------------------------------------------
@pytest.fixture(scope="module")
def navel_on_a_dense_torso():
    pts, tris = torso()
    skin = part(pts, tris)
    render, morphs, results = build_regions([skin], SHIPPED.profiles["navel-reference"], marks(), 0.26)
    return skin, render, morphs, results


def test_a_region_is_made_on_a_dense_body(navel_on_a_dense_torso):
    skin, render, morphs, results = navel_on_a_dense_torso
    (result,) = results
    assert result.made and result.vertices >= 20 and result.registration_mm < 1e-6
    (morph,) = morphs
    assert morph.name == "BodyNavel" and not morph.problems()
    delta = render[0] - skin.positions
    normals = g.vertex_normals(skin.positions, skin.triangles)
    moved = np.linalg.norm(delta, axis=1) > 1e-6
    assert np.einsum("ij,ij->i", delta[moved], normals[moved]).mean() < 0  # a hollow: into her
    assert 1.0 < np.linalg.norm(delta, axis=1).max() * 1000 < 4.0


def test_a_region_stays_inside_its_support_and_keeps_her_measurements(navel_on_a_dense_torso):
    skin, render, _, results = navel_on_a_dense_torso
    moved = np.linalg.norm(render[0] - skin.positions, axis=1) > 1e-7
    anchor = np.array([0.0, 1.05 - 0.3 * 0.07, 0.13])
    assert np.linalg.norm(skin.positions[moved] - anchor, axis=1).max() < 0.036 * 1.1
    assert all(change < 0.005 for change in results[0].measurements.values())


def test_a_region_never_tears_a_seam(navel_on_a_dense_torso):
    skin, render, _, _ = navel_on_a_dense_torso
    owner, _, _ = g.weld(skin.positions, skin.triangles)
    for group in np.unique(owner):
        copies = np.flatnonzero(owner == group)
        if copies.size > 1:
            assert np.allclose(render[0][copies], render[0][copies[0]])


def test_a_coarse_body_refuses_a_region_it_cannot_express():
    pts, tris = torso(edge=0.04)
    _, morphs, results = build_regions([part(pts, tris)], SHIPPED.profiles["navel-reference"], marks(), 0.26)
    assert not morphs and not results[0].made and "normal map" in results[0].reason


def test_the_collision_body_contains_her_and_bridges_the_hollow(navel_on_a_dense_torso):
    skin, render, morphs, results = navel_on_a_dense_torso
    profile = SHIPPED.profiles["navel-reference"]
    state = build_state([skin], render, morphs, results, profile, "render")
    normals = g.vertex_normals(skin.positions, skin.triangles)
    used = skin.used
    out_of_render = np.einsum("ij,ij->i", (state.collision[0] - render[0])[used], normals[used])
    assert out_of_render.min() > 0  # never inside what she looks like
    # The hollow is kept only at its collisionDetail share (0.1): cloth bridges a navel.
    deepest = np.argmax(np.linalg.norm(render[0] - skin.positions, axis=1))
    kept = np.dot(state.collision[0][deepest] - skin.positions[deepest], normals[deepest])
    assert kept > np.dot(render[0][deepest] - skin.positions[deepest], normals[deepest]) * 0.2
    assert state.to_report()["morphTargetsValid"]


def test_the_envelope_closes_seams_instead_of_cracking_them():
    pts, tris = torso(seam_angle=np.pi / 2)
    envelope, _ = build_envelope(part(pts, tris), pts, margin_m=0.001, cutoff_m=0.003)
    owner, _, _ = g.weld(pts, tris)
    for group in np.unique(owner):
        copies = np.flatnonzero(owner == group)
        if copies.size > 1:
            assert np.allclose(envelope[copies], envelope[copies[0]])


def test_signed_clearance_reports_more_than_a_minimum():
    p, t = sphere()
    grid = g.TriangleGrid(p, t, reach=0.03)
    shell, shell_t = sphere(0.103)
    shell[shell[:, 0] > 0.09] *= 0.098 / 0.103
    report = signed_clearance(grid, shell, shell_t)
    assert report["minimumSignedDistanceMm"] < -1 and report["samplesBelowMinus1Mm"] > 0
    assert 0 < report["shareBelowMinus0_5Mm"] < 0.2


def test_morph_export_is_valid_gltf_and_leaves_positions_alone():
    document = GltfDocument.from_bytes(build_vrm(CALIBRATION_BODIES[1], spec="VRM1"))
    measurements = measure_body(document, inspect_document(document))
    (skin,) = skin_parts(document, measurements.bone_positions)
    before = document.read_accessor(skin.accessor).tobytes()
    moved = skin.used[:5]
    morph = MorphTarget("BodyTest", skin.accessor, skin.positions.shape[0], moved.astype(np.uint32),
                        np.full((5, 3), 0.001, dtype=np.float32), default_weight=0.5)
    state = build_state([skin], {skin.accessor: skin.positions}, [morph], [], SHIPPED.profiles["collision-reference"],
                        "render")
    assert export_morphs(document, state) == ["BodyTest"]
    reread = GltfDocument.from_bytes(document.to_bytes())
    mesh = next(m for m in reread.meshes if "BodyTest" in (m.get("extras") or {}).get("targetNames", []))
    counts = {len(p.get("targets", [])) for p in mesh["primitives"]}
    assert len(counts) == 1 and len(mesh["weights"]) == counts.pop() and mesh["weights"][-1] == 0.5
    target = mesh["primitives"][0]["targets"][-1]["POSITION"]
    accessor = reread.gltf["accessors"][target]
    assert accessor["count"] == reread.gltf["accessors"][skin.accessor]["count"] and "min" in accessor
    assert np.allclose(reread.read_accessor(target)[moved], 0.001)
    assert reread.read_accessor(skin.accessor).tobytes() == before  # her POSITION data untouched
    assert inspect_document(reread).humanoid_bones  # still a valid humanoid


def test_garment_fitting_exports_nothing():
    document = GltfDocument.from_bytes(build_vrm(CALIBRATION_BODIES[1], spec="VRM1"))
    measurements = measure_body(document, inspect_document(document))
    (skin,) = skin_parts(document, measurements.bone_positions)
    morph = MorphTarget("BodyTest", skin.accessor, skin.positions.shape[0], np.array([0], np.uint32),
                        np.ones((1, 3), np.float32) * 0.001)
    state = build_state([skin], {skin.accessor: skin.positions}, [morph], [], SHIPPED.profiles["collision-reference"],
                        "garment-fitting")
    before = document.to_bytes()
    assert export_morphs(document, state) == [] and document.to_bytes() == before


def test_girths_are_taken_at_her_landmarks():
    pts, tris = torso()
    found = girths(pts, marks(), centre_x=0.0)
    assert found["waist"] == pytest.approx(2 * np.pi * 0.13, rel=0.01)
    assert "thigh" not in found  # her thigh slab (crotch − 5 cm) is below this torso: not measured


# ---------------------------------------------------------------------------------------------
# 5. cloth and masking
# ---------------------------------------------------------------------------------------------
def test_xpbd_resolves_contact_and_keeps_the_fabric():
    body, body_t = sphere(0.1, 64, 32)
    shell, shell_t = sphere(0.104)
    dented = shell.copy()
    dented[shell[:, 0] > 0.08] *= 0.095 / 0.104
    out, report = relax(dented, shell_t, g.TriangleGrid(body, body_t, reach=0.01))
    # Cloth thickness is 1 mm; an iterative solve ends within a tenth of it.
    assert report.contact_before_mm < -4 and report.contact_after_mm >= 0.9
    assert report.max_strain < 0.15 and out.shape == dented.shape


def test_xpbd_leaves_a_clear_garment_where_it_is():
    body, body_t = sphere(0.1, 64, 32)
    shell, shell_t = sphere(0.104)
    out, report = relax(shell, shell_t, g.TriangleGrid(body, body_t, reach=0.01))
    assert report.moved_vertices == 0 and np.array_equal(out, shell)


@pytest.mark.parametrize("alpha, opacity, policy", [
    ("opaque", 1.0, BodyMaskPolicy.OPAQUE_ONLY), ("opaque", 0.6, BodyMaskPolicy.NEVER),
    ("blend", 1.0, BodyMaskPolicy.NEVER), ("mask", 1.0, BodyMaskPolicy.ALPHA_AWARE),
])
def test_masking_reads_the_material_not_the_category(alpha, opacity, policy):
    material = MaterialPlan.model_validate({"alphaMode": alpha, "opacity": opacity})
    assert body_mask_policy(material) is policy
    assert worker_mask_policy(material) == ("none" if material.exposes_body else "body-only")


# ---------------------------------------------------------------------------------------------
# 6. nothing changes without it
# ---------------------------------------------------------------------------------------------
def test_body_points_without_positions_are_what_they_were():
    document = GltfDocument.from_bytes(build_vrm(CALIBRATION_BODIES[1], spec="VRM1"))
    plain = body_points(document)
    assert np.array_equal(body_points(document, positions=None), plain)
    measurements = measure_body(document, inspect_document(document))
    (skin,) = skin_parts(document, measurements.bone_positions)
    moved = body_points(document, positions={skin.accessor: skin.positions + [0, 0.01, 0]})
    assert moved.shape == plain.shape and not np.array_equal(moved, plain)
