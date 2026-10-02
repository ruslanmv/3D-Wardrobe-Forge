"""BA3. Projection: every design on every declared-adult body, moving exactly with her skin.

Run on the six generated bodies ``assets/calibration/policy.json`` declares adult — the four
calibration bodies and the two fashion-fit forms — never on a library character.
"""

from __future__ import annotations

import numpy as np
import pytest

from wardrobe.body_art.catalog import BodyArtCatalog
from wardrobe.body_art.contract import BodyArtRequest
from wardrobe.body_art.exposure import read_body
from wardrobe.body_art.placement import footprint
from wardrobe.body_art.poses import POSES, node_matrices, skin_points
from wardrobe.body_art.project import MAX_STRETCH, OFFSET_M, build_decal
from wardrobe.body_art.raster import _load, rasterise
from wardrobe.geometry.procedural import FitParameters
from wardrobe.policy.calibration import declared_adult
from wardrobe.vrm.build import CALIBRATION_BODIES, build_vrm
from wardrobe.vrm.document import GltfDocument
from wardrobe.vrm.fashion_body import FASHION_FIT_BODIES, build_fit_form
from wardrobe.vrm.inspect import inspect_document
from wardrobe.vrm.measure import measure_body

CATALOG = BodyArtCatalog.from_directory("assets/body_art")
BODIES = {b.name: (lambda b=b: build_vrm(b, spec="VRM1")) for b in CALIBRATION_BODIES}
BODIES.update({f.name: (lambda f=f: build_fit_form(f)) for f in FASHION_FIT_BODIES})


@pytest.fixture(scope="module", params=sorted(BODIES))
def body(request):
    assert declared_adult(request.param)
    document = GltfDocument.from_bytes(BODIES[request.param]())
    surfaces, frame = read_body(document)
    return request.param, document, surfaces, frame


def _coverage(design):
    return rasterise(_load(str(CATALOG.artwork_path(design))), 256)


def test_every_design_builds_on_every_body(body):
    _name, _document, _surfaces, frame = body
    for design in CATALOG.all():
        for placement in design.placements:
            decal = build_decal(frame, footprint(frame, placement, design.aspect), _coverage(design))
            assert decal.hit_rate >= 0.98 and decal.max_stretch <= MAX_STRETCH, (design.id, placement)
            assert np.allclose(decal.weights.sum(axis=1), 1.0, atol=1e-3)
            assert decal.indices.max() < decal.vertex_count
            assert np.unique(decal.indices).size == decal.vertex_count  # no vertex unused


@pytest.mark.parametrize("pose", sorted(POSES))
def test_the_ink_stays_on_her_skin_in_every_pose(body, pose):
    """Every decal vertex 0.5 mm ± 0.3 mm off the skin vertex it is a copy of, in every pose."""
    _name, document, surfaces, frame = body
    info = inspect_document(document)
    measurements = measure_body(document, info)
    forward = FitParameters(measurements=measurements, metadata={"forward": 1.0}).forward
    table = node_matrices(document, info, measurements, pose, forward)
    skin = surfaces.skin
    for design in CATALOG.all():
        placement = design.placements[0]
        decal = build_decal(frame, footprint(frame, placement, design.aspect), _coverage(design))
        joint_nodes = np.asarray(document.gltf["skins"][decal.skin]["joints"])
        posed_decal = skin_points(
            decal.positions.astype(np.float64), decal.joints, decal.weights, joint_nodes, table
        )
        source = decal.source_vertices
        posed_skin = skin_points(
            skin.positions[source], skin.joints[source], skin.weights[source], joint_nodes, table
        )
        gap = np.linalg.norm(posed_decal - posed_skin, axis=1)
        assert gap.max() < OFFSET_M + 0.0003 and gap.min() > OFFSET_M - 0.0003, (
            design.id,
            pose,
            gap.min(),
            gap.max(),
        )


def test_transforms_move_the_design_and_never_its_uvs(body):
    _name, _document, _surfaces, frame = body
    base = footprint(frame, "upper-back", 2.4)
    moved = footprint(
        frame,
        "upper-back",
        2.4,
        BodyArtRequest(design="tribal-wings-01", placement="upper-back", offsetV=-0.2, scale=0.8),
    )
    assert np.nanmean(moved.points[..., 1]) < np.nanmean(base.points[..., 1])  # lower
    assert moved.uv[0, 0].tolist() == [0.0, 0.0] and moved.uv[-1, -1].tolist() == [1.0, 1.0]
    mirrored = footprint(
        frame,
        "upper-back",
        2.4,
        BodyArtRequest(design="tribal-wings-01", placement="upper-back", mirror=True),
    )

    def side(fp):  # where the artwork's left column (u = 0) lies: < 0 her left, > 0 her right
        column = fp.points[:, 0]
        return float(np.nanmean((column - frame.axis(column[:, 1])) @ frame.right))

    assert side(base) < 0 < side(mirrored)
