"""The shell passes added for the haul: every one keeps the clearance guarantee."""

from __future__ import annotations

import numpy as np
import pytest

from wardrobe.engines.geometry_checks import (
    BodyRadialIndex,
    _surface_samples,
    apply_pleats,
    body_points,
    conform_to_body,
    measure_clearance,
    resolve_clearance,
    smooth_radial,
)
from wardrobe.geometry.procedural import Ring, loft
from wardrobe.vrm.document import GltfDocument

CLEARANCE = 0.005


def cylinder_body(radius: float = 0.12, height: float = 1.0, count: int = 4000) -> np.ndarray:
    """A dense upright cylinder of 'body' points around the Y axis."""
    rng = np.random.default_rng(7)
    angle = rng.uniform(-np.pi, np.pi, count)
    y = rng.uniform(0.0, height, count)
    return np.stack([np.cos(angle) * radius, y, np.sin(angle) * radius], axis=1)


def shell(radius: float, *, noise: float = 0.0, y0: float = 0.2, y1: float = 0.8, rows: int = 8) -> object:
    rings = [Ring(y0 + (y1 - y0) * i / (rows - 1), radius, radius) for i in range(rows)]
    mesh = loft(rings, segments=32)
    if noise:
        # A function of position, so coincident seam twins get the same nudge —
        # exactly as every real pass treats them.
        x, y, z = mesh.positions[:, 0], mesh.positions[:, 1], mesh.positions[:, 2]
        angle = np.round(np.arctan2(z, x), 5)
        scale = 1.0 + noise * np.sin(angle * 7.0 + y * 23.0)
        mesh.positions[:, 0] *= scale
        mesh.positions[:, 2] *= scale
    return mesh


def radii(mesh) -> np.ndarray:
    return np.hypot(mesh.positions[:, 0], mesh.positions[:, 2])


@pytest.fixture
def index() -> BodyRadialIndex:
    return BodyRadialIndex(cylinder_body())


def test_smoothing_evens_the_silhouette_and_gives_no_clearance_back(index):
    mesh = shell(0.12, noise=0.15)
    resolve_clearance(mesh, index, CLEARANCE)
    before = radii(mesh).std()
    smooth_radial(mesh, index, CLEARANCE)
    assert radii(mesh).std() < before
    assert measure_clearance(mesh, index, CLEARANCE).violations == 0


def test_smoothing_keeps_loft_seam_twins_together(index):
    """The loft duplicates its seam vertices; moved apart they open a crack."""
    mesh = shell(0.12, noise=0.15)
    resolve_clearance(mesh, index, CLEARANCE)
    smooth_radial(mesh, index, CLEARANCE)
    ring = 33  # segments + 1: the first and last vertex of each ring coincide
    first = mesh.positions[0::ring]
    last = mesh.positions[ring - 1 :: ring]
    np.testing.assert_allclose(first, last, atol=1e-6)


def test_conform_draws_a_loose_shell_onto_the_body(index):
    mesh = shell(0.2)
    conform_to_body(mesh, index, CLEARANCE, strength=1.0)
    gap = radii(mesh) - 0.12
    assert gap.mean() < 0.01
    resolve_clearance(mesh, index, CLEARANCE)
    assert measure_clearance(mesh, index, CLEARANCE).violations == 0


def test_conform_leaves_everything_below_min_y_alone(index):
    mesh = shell(0.2)
    low = mesh.positions[:, 1] < 0.5
    before = radii(mesh)[low].copy()
    conform_to_body(mesh, index, CLEARANCE, strength=1.0, min_y=0.5)
    np.testing.assert_allclose(radii(mesh)[low], before, atol=1e-6)


def test_zero_strength_is_a_no_op(index):
    mesh = shell(0.2)
    assert conform_to_body(mesh, index, CLEARANCE, strength=0.0) == 0


def test_pleats_fold_both_ways_and_only_below_the_line(index):
    """Zero-mean knife pleats: as much in as out, so the skirt stays the size its cut says."""
    mesh = shell(0.14)
    before = radii(mesh).copy()
    apply_pleats(mesh, index, count=12, from_y=0.5)
    after = radii(mesh)
    above = mesh.positions[:, 1] >= 0.5
    np.testing.assert_allclose(after[above], before[above], atol=1e-6)
    hem = mesh.positions[:, 1] < 0.25
    assert after[hem].std() > before[hem].std()  # the hem actually ripples
    assert (after[hem] < before[hem] - 1e-4).any() and (after[hem] > before[hem] + 1e-4).any()
    assert abs(float((after[hem] / before[hem]).mean()) - 1.0) < 0.01


def test_surface_samples_fill_what_vertices_leave_empty():
    """A coarse torso — rings 10 cm apart, 8 around — leaves most buckets empty; sampled, almost none."""
    coarse = loft([Ring(y / 10, 0.12, 0.12) for y in range(11)], segments=8)
    triangles = coarse.indices.reshape(-1, 3).astype(np.int64)
    points = coarse.positions.astype(np.float64)
    vertices_only = BodyRadialIndex(points)
    sampled = BodyRadialIndex(np.vstack([points, _surface_samples(points, triangles, 0.012)]))
    assert (vertices_only.radii == 0).sum() > 0
    assert (vertices_only.radii == 0).mean() > 0.5
    assert (sampled.radii == 0).mean() < 0.05


def test_body_points_include_surface_samples(vrm_bytes):
    document = GltfDocument.from_bytes(vrm_bytes)
    vertices = body_points(document, spacing=0)
    surface = body_points(document)
    assert surface.shape[0] > vertices.shape[0]


def two_legs(radius: float = 0.06, gap: float = 0.14, count: int = 6000) -> np.ndarray:
    """Two upright thighs side by side, the body's axis in the gap between them."""
    rng = np.random.default_rng(3)
    angle = rng.uniform(-np.pi, np.pi, count)
    side = np.where(rng.random(count) < 0.5, -1.0, 1.0)
    y = rng.uniform(0.0, 0.6, count)
    return np.stack([side * gap / 2 + np.cos(angle) * radius, y, np.sin(angle) * radius], axis=1)


def test_the_hull_spans_the_gap_between_the_legs():
    index = BodyRadialIndex(two_legs())
    behind = np.array([[0.0, 0.3, -0.2]])
    # Nothing is there — it is the hollow between the legs — and the fabric spans it.
    assert index.hull_radius_at(behind)[0] == pytest.approx(0.06, abs=0.012)
    assert index.body_radius_at(behind)[0] == pytest.approx(0.06, abs=0.012)


def test_conform_draws_a_skirt_onto_both_legs_not_just_beside_them():
    index = BodyRadialIndex(two_legs())
    mesh = shell(0.25, y0=0.1, y1=0.5)
    conform_to_body(mesh, index, CLEARANCE, strength=1.0)
    back = mesh.positions[mesh.positions[:, 2] < -0.01]
    assert back[:, 2].min() > -0.085  # 6 cm legs + clearance, not the 25 cm it was built at


def test_smoothing_leaves_a_hem_where_it_is():
    """A hem has neighbours above it only; it must not be dragged out to the row above."""
    index = BodyRadialIndex(cylinder_body(radius=0.1))
    rings = [Ring(0.2, 0.105, 0.105)] + [Ring(0.2 + 0.1 * i, 0.16, 0.16) for i in range(1, 6)]
    mesh = loft(rings, segments=32)
    hem = mesh.positions[:, 1] < 0.21
    before = radii(mesh)[hem].copy()
    smooth_radial(mesh, index, CLEARANCE)
    np.testing.assert_allclose(radii(mesh)[hem], before, atol=2e-3)


def test_body_points_and_bounds_ignore_what_no_primitive_draws(vrm_bytes):
    """VRoid primitives share one vertex buffer; a removed skirt's vertices must not count as her."""
    from tests.vroid_support import dress_like_vroid
    from wardrobe.vrm.garments import remove_slots

    document = GltfDocument.from_bytes(dress_like_vroid(vrm_bytes, slots=("Bottoms",)))
    body = [m for m in document.meshes if len(m["primitives"]) > 1][0]
    accessor = body["primitives"][0]["attributes"]["POSITION"]
    positions = document.read_accessor(accessor)
    # Point the Bottoms primitive at a far-away copy of the buffer's first triangle.
    bottoms = body["primitives"][-1]
    far = np.vstack([positions, positions[:3] + np.array([0.0, 0.0, 2.0], dtype=positions.dtype)])
    moved = document.add_accessor(far.astype(np.float32), include_bounds=True)
    triangle = document.add_accessor(np.arange(far.shape[0] - 3, far.shape[0], dtype=np.uint32).reshape(-1, 1))
    for primitive in body["primitives"]:
        primitive["attributes"]["POSITION"] = moved
    bottoms["indices"] = triangle
    assert body_points(document, spacing=0)[:, 2].max() > 1.5
    assert document.primitive_bounds()[1][2] > 1.5

    remove_slots(document, ["bottoms"])
    assert body_points(document, spacing=0)[:, 2].max() < 0.5
    assert document.primitive_bounds()[1][2] < 0.5


def leg_bones() -> dict:
    return {
        "leftUpperLeg": np.array([0.1, 0.9, 0.0]), "leftLowerLeg": np.array([0.1, 0.5, 0.0]),
        "leftFoot": np.array([0.1, 0.08, 0.0]),
        "rightUpperLeg": np.array([-0.1, 0.9, 0.0]), "rightLowerLeg": np.array([-0.1, 0.5, 0.0]),
        "rightFoot": np.array([-0.1, 0.08, 0.0]),
    }


def leg_surface(radius: float = 0.05) -> np.ndarray:
    rng = np.random.default_rng(5)
    count = 6000
    side = np.where(rng.random(count) < 0.5, 0.1, -0.1)
    angle = rng.uniform(-np.pi, np.pi, count)
    y = rng.uniform(0.1, 0.88, count)
    return np.stack([side + np.cos(angle) * radius, y, np.sin(angle) * radius], axis=1)


def leg_tube(radius: float):
    from wardrobe.geometry.procedural import sweep

    return sweep(np.array([[0.1, 0.85, 0.0], [0.1, 0.5, 0.0], [0.1, 0.15, 0.0]]), [radius] * 3, segments=16)


def tube_radius(mesh) -> np.ndarray:
    return np.hypot(mesh.positions[:, 0] - 0.1, mesh.positions[:, 2])


@pytest.mark.parametrize("strength", [0.0, 1.0])
def test_a_tube_inside_the_leg_is_always_pushed_out(strength):
    from wardrobe.engines.geometry_checks import conform_limbs

    mesh = leg_tube(0.03)
    conform_limbs(mesh, np.ones(mesh.vertex_count, bool), leg_surface(), leg_bones(), CLEARANCE, strength=strength)
    assert tube_radius(mesh).min() >= 0.05 + CLEARANCE - 0.004


def test_a_loose_tube_is_drawn_in_only_as_far_as_asked():
    from wardrobe.engines.geometry_checks import conform_limbs

    tight, loose = leg_tube(0.12), leg_tube(0.12)
    mask = np.ones(tight.vertex_count, bool)
    conform_limbs(tight, mask, leg_surface(), leg_bones(), CLEARANCE, strength=1.0)
    conform_limbs(loose, mask, leg_surface(), leg_bones(), CLEARANCE, strength=0.0)
    assert np.median(tube_radius(tight)) == pytest.approx(0.05 + CLEARANCE, abs=0.006)  # leggings
    assert np.median(tube_radius(loose)) == pytest.approx(0.12, abs=1e-3)  # trousers keep their cut


def test_stray_points_do_not_flare_a_leg():
    """A garment's hidden vertices well off the leg must not become the leg's radius."""
    from wardrobe.engines.geometry_checks import conform_limbs

    stray = leg_surface(radius=0.18)[:600]
    body = np.vstack([leg_surface(), stray])
    mesh = leg_tube(0.12)
    conform_limbs(mesh, np.ones(mesh.vertex_count, bool), body, leg_bones(), CLEARANCE, strength=1.0)
    assert tube_radius(mesh).max() < 0.05 * 1.4 + CLEARANCE + 0.01
