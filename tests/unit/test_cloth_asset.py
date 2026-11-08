"""The cloth asset records what a mesh can be simulated as. It does not invent seams."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from wardrobe.cloth.asset import ClothAssetRejected, compile_cloth_asset
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
