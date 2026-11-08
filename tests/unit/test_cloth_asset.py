"""The cloth asset records what a mesh can be simulated as. It does not invent seams."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from wardrobe.cloth.asset import ClothAssetRejected, compile_cloth_asset
from wardrobe.cloth.binary import decode_asset
from wardrobe.cloth.topology import simplify_particles
from wardrobe.geometry.mesh import Mesh
from wardrobe.geometry.procedural import FitParameters, build_garment
from wardrobe.vrm.build import CALIBRATION_BODIES, build_vrm
from wardrobe.vrm.document import GltfDocument
from wardrobe.vrm.inspect import inspect_document
from wardrobe.vrm.measure import measure_body

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def measurements():
    document = GltfDocument.from_bytes(build_vrm(CALIBRATION_BODIES[1], spec="VRM1"))
    return measure_body(document, inspect_document(document))


def _params(measurements, **style):
    return FitParameters(measurements=measurements, metadata=dict(style))


def test_a_skirt_is_a_cloth_asset_with_a_waist_and_only_real_seams(measurements):
    mesh = build_garment("skirt", _params(measurements), silhouette="straight", hem="mini")
    asset = compile_cloth_asset(mesh, kind="skirt", silhouette="straight", name="Red Skater Skirt")
    assert asset.profile == "cloth"
    assert asset.simulation == "xpbd"
    assert asset.reason == ""
    assert asset.particle_count <= asset.render_count
    assert len(asset.binding) == asset.render_count
    assert asset.stretch_compliance > 0 and asset.bend_compliance > asset.stretch_compliance
    y = mesh.positions[:, 1]
    assert min(asset.attachment[i] for i in range(len(y)) if y[i] > y.max() - 0.01) == 1
    assert max(asset.attachment[i] for i in range(len(y)) if y[i] < y.min() + 0.01) == 0
    for a, b in asset.seam_pairs:
        assert np.linalg.norm(mesh.positions[a] - mesh.positions[b]) < 1.1e-4
    assert asset.summary()["simulation"] == "xpbd"
    assert asset.summary()["seamPairs"] == len(asset.seam_pairs)


def test_a_pencil_is_hybrid_and_leggings_and_boots_are_not_cloth(measurements):
    pencil = compile_cloth_asset(
        build_garment("skirt", _params(measurements), silhouette="pencil", hem="knee"),
        kind="skirt", silhouette="pencil", name="Black Pencil Skirt",
    )
    assert pencil.profile == "hybrid-skirt" and pencil.bend_compliance < 1e-4
    leggings = compile_cloth_asset(
        build_garment("leggings", _params(measurements)), kind="leggings", name="Black Leggings",
    )
    assert leggings.profile == "corrective" and leggings.simulation == "skinning"
    boots = compile_cloth_asset(
        build_garment("boots", _params(measurements)), kind="boots", name="Ankle Boots",
    )
    assert boots.profile == "rigid" and boots.simulation == "rigid"


def test_a_nearby_gap_is_not_stitched_and_the_skirt_is_not_simulated():
    """Two panels 5 mm apart have no seam id. The asset says so and stays a skinning fallback."""
    left = np.array([[0, 0, 0], [0, 0.2, 0], [0.1, 0.2, 0], [0.1, 0, 0]], np.float32)
    right = left + np.array([0.105, 0, 0], np.float32)
    positions = np.vstack([left, right])
    indices = np.array([0, 1, 2, 0, 2, 3, 4, 6, 5, 4, 7, 6], np.uint32)
    mesh = Mesh(positions, indices)
    asset = compile_cloth_asset(mesh, kind="skirt", name="Open Skirt")
    assert asset.seam_pairs == ()
    assert asset.missing_seams > 0
    assert asset.simulation == "fallback-skinning"
    assert asset.reason == "open boundary has no authored seam"


def test_a_degenerate_triangle_is_rejected_and_does_not_become_cloth():
    positions = np.array([[0, 0, 0], [0, 0, 0], [0, 0.1, 0]], np.float32)
    mesh = Mesh(positions, np.array([0, 1, 2], np.uint32))
    with pytest.raises(ClothAssetRejected):
        compile_cloth_asset(mesh, kind="skirt")


def test_coincident_copies_are_one_particle_and_one_seam():
    positions = np.array([[0, 0, 0], [0.2, 0, 0], [0.2, 0.3, 0], [0, 0, 0]], np.float32)
    mesh = Mesh(positions, np.array([0, 1, 2, 3, 2, 1], np.uint32))
    asset = compile_cloth_asset(mesh, kind="skirt", name="Seamed Skirt")
    assert asset.render_count == 4
    assert asset.particle_count == 3
    assert asset.seam_pairs == ((0, 3),)
    assert asset.missing_seams == 0
    assert asset.simulation == "xpbd"


def test_category_wins_over_a_name_that_sounds_like_another_garment():
    positions = np.array([[0, 0, 0], [0.2, 0, 0], [0.2, 0.3, 0]], np.float32)
    mesh = Mesh(positions, np.array([0, 1, 2], np.uint32))
    asset = compile_cloth_asset(
        mesh, kind="top", category="top", name="Black Pencil Boot Skirt",
    )
    assert asset.profile == "skinning"
    assert asset.simulation == "skinning"


def test_a_waistband_section_is_the_attachment_not_the_tallest_vertex():
    """The geometric top is a hem in this fixture. The named waistband is what pins."""
    positions = np.array(
        [[0, 1.0, 0], [0.2, 1.0, 0], [0.1, 1.2, 0], [0, 0.0, 0], [0.2, 0.0, 0], [0.1, 0.2, 0]],
        np.float32,
    )
    indices = np.array([0, 1, 2, 3, 4, 5], np.uint32)
    mesh = Mesh(positions, indices, metadata={"sections": [("hem", 0, 1), ("skirt-waistband", 1, 1)]})
    asset = compile_cloth_asset(mesh, kind="skirt", category="skirt", name="Inverted Skirt")
    assert asset.attachment_source == "section"
    assert asset.attachment[2] == 0
    assert asset.attachment[5] == 1
    decoded = decode_asset(asset.blob)
    pinned = {index for index, weight in decoded["attachments"] if weight >= 0.5}
    assert pinned == {int(asset.binding[i]) for i, weight in enumerate(asset.attachment) if weight >= 0.5}


def test_authored_weights_are_copied_and_a_gap_is_still_not_a_seam():
    positions = np.array([[0, 0, 0], [0.2, 0, 0], [0.1, 0.2, 0]], np.float32)
    weights = np.array([1.0, 0.0, 0.25])
    mesh = Mesh(positions, np.array([0, 1, 2], np.uint32), metadata={"clothAttachment": weights})
    asset = compile_cloth_asset(mesh, kind="skirt", category="skirt")
    assert asset.attachment_source == "authored"
    assert asset.attachment == (1.0, 0.0, 0.25)
    decoded = decode_asset(asset.blob)
    assert decoded["schema"] == "wardrobe.cloth/1"
    assert len(decoded["stretch"]) == 3
    assert decoded["heightFallback"] is False
    assert asset.summary()["lods"][0] == {"name": "mobile-low", "particles": 0, "simulation": "skinning", "mesh": "none"}


def test_a_grid_keeps_its_boundary_when_the_interior_is_simplified():
    count = 8
    positions = np.array([[x, y, 0] for y in range(count) for x in range(count)], np.float64)
    triangles = []
    for y in range(count - 1):
        for x in range(count - 1):
            a = y * count + x
            triangles += [a, a + 1, a + count, a + 1, a + count + 1, a + count]
    triangles = np.array(triangles, np.int64).reshape(-1, 3)
    locked = np.zeros(len(positions), dtype=bool)
    coarse, coarse_tris, mapping = simplify_particles(positions, triangles, locked, budget=20)
    assert len(coarse) <= 20 or len(coarse) < len(positions)
    boundary = []
    for index, (x, y, _z) in enumerate(positions):
        if x in (0, count - 1) or y in (0, count - 1):
            boundary.append(index)
    for index in boundary:
        survivor = mapping[index]
        assert np.allclose(coarse[survivor], positions[index])
    assert mapping.min() >= 0 and mapping.max() < len(coarse)
    assert len(coarse_tris) > 0


def test_the_geometry_fingerprint_ignores_an_appended_cloth_buffer():
    from tests.body_art_support import differences, fingerprint
    from wardrobe.vrm.document import ARRAY_BUFFER, ELEMENT_ARRAY_BUFFER, GltfDocument

    document = GltfDocument({
        "asset": {"version": "2.0"},
        "scene": 0,
        "scenes": [{"nodes": [0]}],
        "nodes": [{"name": "Tee", "mesh": 0, "extras": {"wardrobeForge": {"kind": "garment", "lookId": "job"}}}],
        "materials": [{"name": "cotton"}],
    })
    position = document.add_accessor(np.array([[0, 0, 0], [0, 1, 0], [1, 0, 0]], np.float32), target=ARRAY_BUFFER)
    index = document.add_accessor(np.array([0, 1, 2], np.uint32), target=ELEMENT_ARRAY_BUFFER)
    document.gltf["meshes"] = [{"primitives": [{"attributes": {"POSITION": position}, "indices": index, "material": 0}]}]
    before = document.to_bytes()
    asset = compile_cloth_asset(
        Mesh(np.array([[0, 0, 0], [0, 1, 0], [1, 0, 0]], np.float32), np.array([0, 1, 2], np.uint32)),
        kind="top", category="top",
    )
    view = document.add_buffer_view(asset.blob)
    document.gltf["nodes"][0]["extras"]["wardrobeForge"]["clothAsset"] = {**asset.summary(), "bufferView": view}
    after = document.to_bytes()
    assert not differences(fingerprint(before), fingerprint(after))


def test_the_gallery_geometry_hash_ignores_cloth_metadata():
    import sys
    sys.path.insert(0, str(ROOT / "tools" / "gallery"))
    import geometry_hashes

    from wardrobe.vrm.document import ARRAY_BUFFER, ELEMENT_ARRAY_BUFFER, GltfDocument

    def build(extra):
        document = GltfDocument({
            "asset": {"version": "2.0"},
            "nodes": [{"name": "Black Tee", "mesh": 0, "extras": {"wardrobeForge": extra}}],
            "materials": [{"name": "cotton", "pbrMetallicRoughness": {"baseColorFactor": [0, 0, 0, 1]}}],
        })
        position = document.add_accessor(np.zeros((3, 3), np.float32), target=ARRAY_BUFFER)
        index = document.add_accessor(np.array([0, 1, 2], np.uint32), target=ELEMENT_ARRAY_BUFFER)
        document.gltf["meshes"] = [{"primitives": [{"attributes": {"POSITION": position}, "indices": index, "material": 0}]}]
        return document.to_bytes()

    plain = {"kind": "garment", "slot": "top", "lookId": "one"}
    tagged = {**plain, "lookId": "two", "clothAsset": {"schema": "wardrobe.cloth/1", "particles": 3}}
    assert geometry_hashes.garment_hashes(build(plain)) == geometry_hashes.garment_hashes(build(tagged))


# ----------------------------------------------------------------------
# SB1. shell bridges, boundary folds, and gaps that stay missing seams
# ----------------------------------------------------------------------
def _band(radius, y_top, y_bottom, segments=24, rows=2, closed=True, open_degrees=0.0):
    """A ring of quads (or an unsewn wrap when ``closed`` is False) between two heights."""
    sweep = 2 * np.pi - np.radians(open_degrees)
    columns = segments if closed else segments + 1
    positions = []
    for row in range(rows + 1):
        y = y_top + (y_bottom - y_top) * row / rows
        for column in range(columns):
            angle = sweep * column / segments
            positions.append([radius * np.cos(angle), y, radius * np.sin(angle)])
    triangles = []
    for row in range(rows):
        for column in range(segments):
            nxt = (column + 1) % columns if closed else column + 1
            a, b = row * columns + column, row * columns + nxt
            c, d = a + columns, b + columns
            triangles += [a, c, b, b, c, d]
    return np.array(positions, np.float32), np.array(triangles, np.uint32)


def _join(*parts):
    positions, indices, offset = [], [], 0
    for points, tris in parts:
        positions.append(points)
        indices.append(tris + offset)
        offset += len(points)
    return Mesh(np.vstack(positions), np.concatenate(indices).astype(np.uint32))


def test_a_one_millimetre_shell_offset_is_a_bridge_not_a_missing_seam():
    """The A-line bodice ends at hip_y and its skirt starts 1 mm below: two loops, one dress."""
    mesh = _join(_band(0.15, 1.10, 0.90), _band(0.15, 0.899, 0.60))
    before = mesh.positions.copy()
    asset = compile_cloth_asset(mesh, kind="dress", category="dress", name="Black A-line Dress")
    assert np.array_equal(mesh.positions, before)  # nothing moved
    assert asset.missing_seams == 0
    assert asset.simulation == "xpbd"
    assert asset.shell_bridges == 24
    assert asset.summary()["shellBridges"] == 24
    decoded = decode_asset(asset.blob)
    bridges = [(a, b, rest) for a, b, rest in decoded["stretch"] if rest < 0.0015]
    assert len(bridges) == 24
    for a, b, rest in bridges:
        assert abs(rest - 0.001) < 2e-5
        assert abs(np.linalg.norm(decoded["positions"][a] - decoded["positions"][b]) - rest) < 2e-5


def test_a_gap_between_two_loops_wider_than_a_shell_offset_is_still_missing():
    mesh = _join(_band(0.15, 1.10, 0.90), _band(0.15, 0.895, 0.60))  # 5 mm
    asset = compile_cloth_asset(mesh, kind="dress", category="dress", name="Two Piece")
    assert asset.shell_bridges == 0
    assert asset.missing_seams > 0
    assert asset.simulation == "fallback-skinning"


def test_an_unsewn_wrap_is_one_loop_and_still_a_missing_seam():
    """Both sides of a panel wrapped into a tube are on one loop. The walk between them is the whole hem."""
    points, tris = _band(0.15, 0.95, 0.60, segments=48, closed=False, open_degrees=0.8)  # ~2 mm apart
    asset = compile_cloth_asset(Mesh(points, tris), kind="skirt", category="skirt", name="Unsewn Wrap")
    assert asset.boundary_folds == 0
    assert asset.missing_seams > 0
    assert asset.simulation == "fallback-skinning"


def test_a_hem_folding_back_on_itself_is_a_fold_not_a_seam():
    """A knife pleat turns the hem under: the same loop passes 3 mm from itself after a short walk."""
    # Accordion strip: 30 mm forward, 20 mm back, 30 mm forward, each pass 3 mm deeper.
    path = [(0.0, 0.0), (0.03, 0.0), (0.03, 0.003), (0.01, 0.003), (0.01, 0.006), (0.04, 0.006),
            (0.04, 0.009), (0.02, 0.009), (0.02, 0.012), (0.05, 0.012)]
    dense = []
    for (x0, z0), (x1, z1) in zip(path[:-1], path[1:]):
        steps = max(1, int(round(np.hypot(x1 - x0, z1 - z0) / 0.005)))
        dense += [(x0 + (x1 - x0) * k / steps, z0 + (z1 - z0) * k / steps) for k in range(steps)]
    dense.append(path[-1])
    rows = [0.10, 0.07, 0.04]
    positions = np.array([[x, y, z] for y in rows for x, z in dense], np.float32)
    n = len(dense)
    tris = []
    for r in range(len(rows) - 1):
        for k in range(n - 1):
            a, b = r * n + k, r * n + k + 1
            tris += [a, a + n, b, b, a + n, b + n]
    asset = compile_cloth_asset(Mesh(positions, np.array(tris, np.uint32)), kind="skirt", category="skirt",
                                name="Pleat Strip")
    assert asset.boundary_folds > 0
    assert asset.missing_seams == 0
    assert asset.shell_bridges == 0  # a fold is left free to open; it is never bridged
    assert asset.simulation == "xpbd"


def test_a_dress_pins_its_bodice_not_its_neckline(measurements):
    """PA1. The A-line has no waistband: the bodice section is the attachment, so the skirt hangs from the hip."""
    mesh = build_garment("dress", _params(measurements), silhouette="a-line", hem="knee")
    asset = compile_cloth_asset(mesh, kind="dress", category="dress", name="Black A-line Dress")
    assert asset.attachment_source == "section"
    assert asset.simulation == "xpbd" and asset.missing_seams == 0 and asset.shell_bridges > 0
    indices = np.asarray(mesh.indices, np.int64)
    from wardrobe.geometry.mesh import section_ranges
    spans = {name: np.unique(indices[first * 3:(first + count) * 3]) for name, first, count in section_ranges(mesh)}
    weights = np.asarray(asset.attachment)
    assert np.all(weights[spans["dress-bodice"]] == 1.0)
    skirt_only = np.setdiff1d(spans["dress-skirt"], spans["dress-bodice"])
    assert np.all(weights[skirt_only] == 0.0)  # the whole skirt is free, down from the hip join
