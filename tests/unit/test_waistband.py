"""S3. A skirt's waistband: copied from the fitted skirt, a fixed distance out, its own section.

A plain skirt was one smooth shell with nothing to say where it began, and a
matte pencil skirt read as a grey tube. These pin the band that fixes that: it
follows the skirt exactly (same heights, same shape, 3 mm out), closes to the
skirt above and below, and is a section assembly can draw a shade darker.
"""

from __future__ import annotations

import numpy as np
import pytest

from wardrobe.geometry.mesh import section_ranges
from wardrobe.geometry.procedural import FitParameters, build_skirt, skirt_shape
from wardrobe.geometry.waistband import (
    WAISTBAND_DEPTH_M,
    WAISTBAND_PROUD_M,
    WAISTBAND_SECTION,
    add_waistband,
    waistband_mask,
)
from wardrobe.vrm.build import CALIBRATION_BODIES, build_vrm
from wardrobe.vrm.document import GltfDocument
from wardrobe.vrm.inspect import inspect_document
from wardrobe.vrm.measure import measure_body


@pytest.fixture(scope="module")
def skirt():
    document = GltfDocument.from_bytes(build_vrm(CALIBRATION_BODIES[1], spec="VRM1"))
    params = FitParameters(measurements=measure_body(document, inspect_document(document)))
    mesh = build_skirt(params, y_top=params.waist_y, y_bottom=params.knee_y, shape=skirt_shape(params, "pencil", 1.0))
    mesh.compute_normals()
    return mesh


def _band(mesh):
    tris = mesh.indices.reshape(-1, 3)[waistband_mask(mesh)]
    return np.unique(tris.reshape(-1))


def test_the_band_is_its_own_section_after_the_skirt(skirt):
    banded = add_waistband(skirt, 0.0, 0.0)
    sections = section_ranges(banded)
    assert sections[0][1] == 0 and sections[0][2] == skirt.triangle_count  # the skirt, untouched
    assert sections[-1][0] == WAISTBAND_SECTION
    assert waistband_mask(banded).sum() == banded.triangle_count - skirt.triangle_count
    assert not banded.validate()
    assert np.allclose(banded.positions[: skirt.vertex_count], skirt.positions)  # the skirt did not move


def test_the_band_follows_the_top_rows_a_fixed_distance_out(skirt):
    banded = add_waistband(skirt, 0.0, 0.0)
    top = float(skirt.positions[:, 1].max())
    band = banded.positions[_band(banded)].astype(np.float64)
    assert band[:, 1].max() == pytest.approx(top, abs=1e-5)
    assert top - band[:, 1].min() <= WAISTBAND_DEPTH_M + 1e-5  # a waistband, not a yoke
    assert top - band[:, 1].min() >= 0.012
    # Every band vertex is either on the skirt (a lip's inner edge) or exactly proud of it.
    skirt_radius = {}
    for p in skirt.positions.astype(np.float64):
        skirt_radius.setdefault((round(p[1], 4), round(float(np.arctan2(p[2], p[0])), 3)), np.hypot(p[0], p[2]))
    offsets = []
    for p in band:
        r0 = skirt_radius.get((round(p[1], 4), round(float(np.arctan2(p[2], p[0])), 3)))
        if r0 is not None:
            offsets.append(np.hypot(p[0], p[2]) - r0)
    offsets = np.round(np.asarray(offsets), 5)
    assert set(np.unique(offsets)).issubset({0.0, round(WAISTBAND_PROUD_M, 5)})
    assert (offsets > 0).any() and (offsets == 0).any()


def test_the_lips_close_the_band_to_the_skirt_above_and_below(skirt):
    """No slot to see into: the band's top edge faces up, its lower edge down, where it reads as a ledge."""
    banded = add_waistband(skirt, 0.0, 0.0)
    tris = banded.indices.reshape(-1, 3)[waistband_mask(banded)].astype(np.int64)
    p = banded.positions.astype(np.float64)
    n = np.cross(p[tris[:, 1]] - p[tris[:, 0]], p[tris[:, 2]] - p[tris[:, 0]])
    n /= np.maximum(np.linalg.norm(n, axis=1, keepdims=True), 1e-12)
    flat = np.abs(n[:, 1]) > 0.9
    heights = p[tris[flat]][:, :, 1].mean(axis=1)
    top, bottom = heights.max(), heights.min()
    assert (n[flat][heights == top][:, 1] > 0).all()
    assert (n[flat][heights == bottom][:, 1] < 0).all()
    assert top - bottom > 0.012


def test_nothing_to_band_leaves_the_mesh_alone(skirt):
    from wardrobe.geometry.mesh import Mesh

    empty = Mesh(positions=np.zeros((0, 3), np.float32), indices=np.zeros(0, np.uint32))
    assert add_waistband(empty, 0.0, 0.0) is empty
    assert add_waistband(skirt, 0.0, 0.0, depth_m=0.001) is skirt  # one row: no band worth drawing


def test_the_skirt_handed_in_is_not_changed(skirt):
    metadata, normals = dict(skirt.metadata), skirt.normals.copy()
    add_waistband(skirt, 0.0, 0.0)
    assert skirt.metadata == metadata and np.array_equal(skirt.normals, normals)
