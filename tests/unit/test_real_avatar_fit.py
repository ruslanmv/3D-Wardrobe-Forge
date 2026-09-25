"""What dressing the real VRoid avatars caught, pinned so it stays fixed.

The calibration mannequin has no hair, no fingers worth the name, legs well
apart and a chest no wider than its shoulders. The library avatars have all of
those, and each broke a fit the mannequin passed: garments pushed out to hair
and fingertips, trouser legs merged into a column, hip ledges, straps floating
round the shoulders, sleeves twice the arm, a dress showing the body at the
armpits. Synthetic cases here pin each mechanism; the tests at the bottom run
the real avatars when ``make library`` has fetched them, and skip otherwise.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from wardrobe.engines.geometry_checks import (
    BodyRadialIndex,
    _crotch_height,
    body_points,
    canonical_bone,
    lower_body_profile,
    nearest_body_bone,
    settle_faces,
)
from wardrobe.engines.shell import _keep_legs_apart, on_axis_mask
from wardrobe.geometry.mesh import Mesh
from wardrobe.geometry.procedural import FitParameters, Ring, build_garment, loft, sweep
from wardrobe.vrm.build import CALIBRATION_BODIES, build_vrm
from wardrobe.vrm.document import GltfDocument
from wardrobe.vrm.inspect import inspect_document
from wardrobe.vrm.measure import measure_body
from wardrobe.vrm.skinning import BoneSegment

LIBRARY = Path(__file__).resolve().parents[2] / "assets" / "library"


@pytest.fixture(scope="module")
def calibration():
    document = GltfDocument.from_bytes(build_vrm(CALIBRATION_BODIES[1], spec="VRM1"))
    info = inspect_document(document)
    return document, info, measure_body(document, info)


# ----------------------------------------------------------------------
# what counts as body
# ----------------------------------------------------------------------
def test_nothing_that_moves_with_her_head_is_body(calibration):
    """Hair to her thighs was read as hips; the head's vertices are left out entirely."""
    document, info, measurements = calibration
    neck = float(measurements.bone_positions["neck"][1])
    everything = body_points(document, include_head=True)
    body = body_points(document)
    assert everything[:, 1].max() > neck + 0.1  # the mannequin has a head
    assert body[:, 1].max() < neck + 0.05
    assert body.shape[0] < everything.shape[0]


@pytest.mark.parametrize(
    ("bone", "canonical"),
    [("leftIndexProximal", "leftHand"), ("rightThumbDistal", "rightHand"), ("leftToes", "leftFoot"),
     ("rightEye", "head"), ("jaw", "head"), ("spine", "spine")],
)
def test_fingers_toes_and_eyes_belong_to_hand_foot_and_head(bone, canonical):
    """Unmapped, each finger was a bone no exclusion list named: T-pose fingertips joined her torso."""
    assert canonical_bone(bone) == canonical


def _segment(name, head, tail):
    return BoneSegment(name=name, node=0, head=np.array(head, float), tail=np.array(tail, float))


def test_the_chest_wall_under_the_armpit_is_torso_not_arm():
    segments = [
        _segment("chest", (0, 1.05, 0), (0, 1.2, 0)),
        _segment("leftUpperArm", (0.08, 1.24, 0), (0.33, 1.24, 0)),
    ]
    arm = np.array([[0.2, 1.24 + 0.03 * np.cos(a), 0.03 * np.sin(a)] for a in np.linspace(0, 6.2, 40)])
    under_armpit = np.array([[0.095, 1.17, 0.0], [0.1, 1.16, 0.02]])  # wider than the joint, below it
    owner = nearest_body_bone(np.vstack([arm, under_armpit]), segments)
    assert (owner[: len(arm)] == 1).all()
    assert (owner[len(arm):] == 0).all()


# ----------------------------------------------------------------------
# legs
# ----------------------------------------------------------------------
def _pelvis_and_legs(crotch: float) -> np.ndarray:
    """A pelvis above ``crotch`` and two nearly touching legs below it, as points."""
    points = []
    for y in np.arange(crotch, crotch + 0.12, 0.004):
        for a in np.linspace(0, 2 * np.pi, 160, endpoint=False):
            points.append([0.13 * np.cos(a), y, 0.08 * np.sin(a)])
    for x in (-0.068, 0.068):  # 1.2 cm apart at the midline: thighs all but touching
        for y in np.arange(0.1, crotch, 0.004):
            for a in np.linspace(0, 2 * np.pi, 60, endpoint=False):
                points.append([x + 0.062 * np.cos(a), y, 0.062 * np.sin(a)])
    return np.array(points)


def test_the_crotch_is_where_the_midline_stops_being_pelvis_not_where_the_legs_part():
    """Thighs that touch leave the midline full below the crotch; its depth collapses at it."""
    points = _pelvis_and_legs(crotch=0.79)
    found = _crotch_height(points, 0.0, hip_y=0.86, knee_y=0.5)
    assert found == pytest.approx(0.79, abs=0.015)


@pytest.mark.parametrize("body", CALIBRATION_BODIES, ids=lambda b: b.name)
def test_a_blocky_low_poly_pelvis_still_has_its_crotch_found(body):
    """The mannequin's pelvis ends at its hip joints, with empty midline slices mid-pelvis.

    Measured at the joint the reference was empty and the fallback put the crotch
    6 cm too low: the yoke wrapped both legs and jeans grew flaps at the crotch.
    """
    document = GltfDocument.from_bytes(build_vrm(body, spec="VRM1"))
    bones = measure_body(document, inspect_document(document)).bone_positions
    hip, knee = float(bones["leftUpperLeg"][1]), float(bones["leftLowerLeg"][1])
    found = _crotch_height(body_points(document), 0.0, hip, knee)
    assert found is not None and abs(found - hip) < 0.02


def test_legs_are_measured_round_the_leg():
    points = _pelvis_and_legs(crotch=0.79)
    bones = {"leftUpperLeg": (0.07, 0.86, 0), "rightUpperLeg": (-0.07, 0.86, 0),
             "leftLowerLeg": (0.06, 0.5, 0), "rightLowerLeg": (-0.06, 0.5, 0),
             "leftFoot": (0.06, 0.1, 0), "rightFoot": (-0.06, 0.1, 0)}
    profile = lower_body_profile(points, points[points[:, 1] < 0.79], bones)
    assert profile is not None and profile["crotchY"] == pytest.approx(0.79, abs=0.015)
    radii = [ring[3] for ring in profile["legs"]["left"]]
    assert np.median(radii) == pytest.approx(0.062, abs=0.006)


def test_trouser_legs_never_cross_her_midline():
    bones = {"leftUpperLeg": (0.069, 0.86, 0), "rightUpperLeg": (-0.069, 0.86, 0)}
    legs = [sweep(np.array([[side * 0.05, 0.8, 0], [side * 0.04, 0.2, 0]]), [0.08, 0.07], segments=16)
            for side in (-1, 1)]
    mesh = legs[0]
    offset = mesh.vertex_count
    mesh = Mesh(positions=np.vstack([legs[0].positions, legs[1].positions]),
                indices=np.concatenate([legs[0].indices, legs[1].indices + offset]))
    _keep_legs_apart(mesh, np.ones(mesh.vertex_count, bool), bones)
    x = mesh.positions[:, 0]
    assert (x[:offset] <= -0.0029).all() and (x[offset:] >= 0.0029).all()


def test_a_leg_close_to_the_midline_is_still_a_leg():
    """Knock-kneed baggy legs 5.5 cm off centre were called torso and fitted as one bulge."""
    measurements = SimpleNamespace(bone_positions={"leftUpperLeg": (0.069, 0.86, 0),
                                                   "rightUpperLeg": (-0.069, 0.86, 0)})
    leg = sweep(np.array([[0.045, 0.8, 0], [0.045, 0.2, 0]]), [0.08, 0.08], segments=16)
    yoke = loft([Ring(0.8, 0.13, 0.09), Ring(1.0, 0.1, 0.08)], segments=24)
    mesh = Mesh(positions=np.vstack([yoke.positions, leg.positions]),
                indices=np.concatenate([yoke.indices, leg.indices + yoke.vertex_count]))
    mask = on_axis_mask(mesh, measurements)
    assert mask[: yoke.vertex_count].all()
    assert not mask[yoke.vertex_count:].any()


# ----------------------------------------------------------------------
# faces, straps, top edges
# ----------------------------------------------------------------------
def test_a_face_that_dips_into_the_body_between_its_corners_is_pushed_out():
    """Rows 3 cm apart: over a bust every corner clears the body and the flat face does not."""
    body = np.array([[0.1 * np.cos(a), y, 0.1 * np.sin(a)]
                     for y in np.arange(0.0, 0.3, 0.005) for a in np.linspace(0, 2 * np.pi, 64, endpoint=False)])
    body[:, [0, 2]] *= (1.0 + 0.2 * np.exp(-((body[:, 1] - 0.15) / 0.02) ** 2))[:, None]  # a ridge
    index = BodyRadialIndex(body)
    shell = loft([Ring(0.0, 0.106, 0.106), Ring(0.3, 0.106, 0.106)], segments=48)  # no row at the ridge
    before = settle_faces(Mesh(positions=shell.positions.copy(), indices=shell.indices), index, 0.004)
    assert before > 0


def test_a_sleeveless_top_edge_stops_at_her_armpit(calibration):
    _, _, measurements = calibration
    bare = FitParameters(measurements=measurements, metadata={"armpitY": 1.15})
    sleeved = FitParameters(measurements=measurements, metadata={"armpitY": 1.15}, sleeve_length="short")
    assert bare.top_edge(0.9) <= 1.15 - 0.005
    assert sleeved.top_edge(0.9) > bare.top_edge(0.9)


def test_straps_lie_on_her_measured_shoulders(calibration):
    """Formula straps rose 4 cm above the joint and crossed flat: a frame round her shoulders."""
    _, _, measurements = calibration
    xs = np.arange(-0.25, 0.25 + 1e-9, 0.01)
    ys = np.arange(1.0, 1.6, 0.01)
    shoulder = 1.30
    front = [[0.08 if y < shoulder - 0.02 * abs(x) * 10 else np.nan for y in ys] for x in xs]
    back = [[-0.06 if y < shoulder - 0.02 * abs(x) * 10 else np.nan for y in ys] for x in xs]
    top = [shoulder - 0.02 * abs(x) * 10 for x in xs]
    surface = {"x0": -0.25, "y0": 1.0, "step": 0.01, "forward": 1.0, "front": front, "back": back,
               "top": top, "neckTop": top}
    params = FitParameters(measurements=measurements, metadata={"upperBody": surface, "straps": "shoulder"})
    mesh = build_garment("slip-dress", params, hem="midi")
    straps = mesh.positions[mesh.positions[:, 1] > params.top_edge(0.3) + 0.02]
    assert straps.shape[0] > 0
    assert straps[:, 1].max() < shoulder + 0.02  # on the shoulder, not above it
    assert straps[:, 2].max() < 0.08 + 0.03 and straps[:, 2].min() > -0.06 - 0.03


# ----------------------------------------------------------------------
# the real avatars, when the library is on disk
# ----------------------------------------------------------------------
def _library_look(slug_file: str, prompt: str):
    from wardrobe.config import Settings
    from wardrobe.domain.garments import TemplateCatalog
    from wardrobe.domain.jobs import CreateJobRequest
    from wardrobe.library import AvatarLibrary
    from wardrobe.pipeline.orchestrator import Orchestrator
    from wardrobe.queue.jobs import AsyncioJobQueue
    from wardrobe.storage.database import InMemoryJobRepository, InMemoryWardrobeRepository
    from wardrobe.storage.object_store import LocalObjectStore

    if not (LIBRARY / slug_file).exists():
        pytest.skip("the avatar library is not fetched (make library)")

    async def run(tmp: Path):
        settings = Settings(wardrobe_storage_root=str(tmp), wardrobe_engine="native", strict_licensing=True)
        store = LocalObjectStore(settings.storage_root_path, settings)
        orchestrator = Orchestrator(
            settings=settings, store=store, jobs=InMemoryJobRepository(), wardrobes=InMemoryWardrobeRepository(),
            queue=AsyncioJobQueue(concurrency=1),
            catalog=TemplateCatalog.from_directory(LIBRARY.parent / "garment_templates"),
        )
        avatar = next(a for a in AvatarLibrary.from_directory(LIBRARY).avatars if a.file == slug_file)
        await store.put("sources/x.vrm", avatar.path.read_bytes())
        payload = {k: v for k, v in avatar.avatar_input().items() if k not in ("storageKey", "sha256")}
        request = CreateJobRequest.model_validate({
            "avatar": {"storageKey": "sources/x.vrm", **payload},
            "outfit": {"prompt": prompt, "mode": "template"},
            "options": {"renderPreview": False, "engine": "native"},
        })
        result = await orchestrator.run_now(request)
        assert result.look is not None, result.error
        return GltfDocument.from_bytes(await store.get(f"looks/{result.look.id}/look.vrm")), result

    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        return asyncio.run(run(Path(tmp)))


def _garment_points(document: GltfDocument, template_id: str) -> np.ndarray:
    points = []
    for node in document.nodes:
        tag = (node.get("extras") or {}).get("wardrobeForge") or {}
        if tag.get("templateId") == template_id and "mesh" in node:
            for primitive in document.meshes[node["mesh"]]["primitives"]:
                positions = document.read_accessor(primitive["attributes"]["POSITION"])[:, :3]
                used = np.unique(document.read_accessor(primitive["indices"]).reshape(-1))
                points.append(positions[used])
    return np.vstack(points)


def test_long_hair_does_not_push_a_dress_out():
    """Sample B's hair reaches her thighs; her dress grew wings and a bell round it."""
    document, result = _library_look("AvatarSample_B.vrm", "red bodycon mini dress")
    dress = _garment_points(document, "dress-mini-bodycon-v1")
    assert np.hypot(dress[:, 0], dress[:, 2]).max() < 0.2
    assert result.fit_report.passed


def test_real_jeans_have_two_legs_and_no_hip_ledge():
    document, _ = _library_look("AvatarSample_A.vrm", "black fitted crop top + blue straight jeans")
    jeans = _garment_points(document, "jeans-straight-v1")
    below = jeans[jeans[:, 1] < 0.7]
    assert (np.abs(below[:, 0]) >= 0.0029).all()  # two legs, apart at her midline
    slices = [jeans[np.abs(jeans[:, 1] - y) < 0.02] for y in np.arange(0.62, 1.0, 0.04)]
    widths = [np.abs(s[:, 0]).max() for s in slices if s.shape[0]]
    assert max(widths) < 0.17  # no ledge standing off her hips
