"""An under-skirt liner is trousers with three openings, not an open crotch.

In a below-hem camera the old separate yoke and leg tubes had an unclosed
crotch. A fitted liner must have one connected fabric surface whose only
boundaries are its waistband and its two short leg hems.
"""

from __future__ import annotations

import numpy as np
import pytest

from wardrobe.engines.geometry_checks import body_points, lower_body_profile
from wardrobe.geometry.procedural import FitParameters, build_garment
from wardrobe.vrm.build import CALIBRATION_BODIES, build_vrm
from wardrobe.vrm.document import GltfDocument
from wardrobe.vrm.inspect import inspect_document
from wardrobe.vrm.measure import measure_body


@pytest.fixture(params=[body.name for body in CALIBRATION_BODIES])
def measured(request):
    avatar = next(body for body in CALIBRATION_BODIES if body.name == request.param)
    document = GltfDocument.from_bytes(build_vrm(avatar, spec="VRM1"))
    info = inspect_document(document)
    measurements = measure_body(document, info)
    whole = body_points(document)
    bones = measurements.bone_positions
    legs = whole[(whole[:, 1] < bones["leftUpperLeg"][1]) & (np.abs(whole[:, 0]) > 0.01)]
    lower = lower_body_profile(whole, legs, bones)
    assert lower is not None
    # The real fitter excludes arms from the torso outline and supplies leg
    # samples below the measured crotch rather than the hip-bone landmark.
    arms = np.abs(whole[:, 0]) > abs(bones["leftUpperArm"][0]) * 0.95
    meta = {
        "lowerBody": lower,
        "coverPoints": whole[~arms],
        "legPoints": legs[legs[:, 1] < lower["crotchY"] - 0.01],
        "rise": "low",
    }
    return FitParameters(measurements=measurements, metadata=meta)


def _boundary_loops(mesh):
    """Count the physical boundary loops, welding section/UV seam twins."""
    positions = np.rint(mesh.positions.astype(np.float64) / 1e-5).astype(np.int64)
    _, vertex = np.unique(positions, axis=0, return_inverse=True)
    faces = vertex[mesh.indices.reshape(-1, 3)]
    edges = np.sort(np.concatenate(
        [faces[:, [0, 1]], faces[:, [1, 2]], faces[:, [2, 0]]], axis=0
    ), axis=1)
    unique, counts = np.unique(edges, axis=0, return_counts=True)
    assert (counts <= 2).all(), "liner has non-manifold fabric intersections"
    boundary = unique[counts == 1]
    assert boundary.size, "liner has no open waistband or leg holes"
    neighbors = {}
    for a, b in boundary:
        neighbors.setdefault(int(a), set()).add(int(b))
        neighbors.setdefault(int(b), set()).add(int(a))
    assert all(len(n) == 2 for n in neighbors.values()), "liner has a torn/open crotch edge"
    visited = set()
    loops = 0
    for start in neighbors:
        if start in visited:
            continue
        loops += 1
        stack = [start]
        while stack:
            point = stack.pop()
            if point not in visited:
                visited.add(point)
                stack.extend(neighbors[point] - visited)
    return loops


def test_slip_shorts_have_a_connected_crotch_and_three_openings(measured):
    mesh = build_garment("slip-shorts", measured, silhouette="slim", hem="mini")
    assert mesh.metadata.get("panelBuilt") is True
    assert _boundary_loops(mesh) == 3  # waistband, left leg and right leg


def test_unmeasured_liner_still_covers_the_crotch(measured):
    # Fall back to a gusset, never the old shaped=False open yoke.
    bare = FitParameters(measurements=measured.measurements, metadata={"rise": "low"})
    mesh = build_garment("slip-shorts", bare, silhouette="slim", hem="mini")
    assert any("gusset" in name for name, _, _ in mesh.metadata["sections"])
