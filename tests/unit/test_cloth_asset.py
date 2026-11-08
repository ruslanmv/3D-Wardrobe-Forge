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
