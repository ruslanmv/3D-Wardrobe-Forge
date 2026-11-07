"""The leggings groin follows her groove, and the catalog fit still passes.

The public preview fits each pair onto the reference base after her slip shorts come off.
The front of the trunk is cut on her measured ray, inside the convex hull that bridges
from thigh to thigh. Scoring that hull called 41 vertices an intersection (12.5 mm
"inside") and withheld all three previews. The rows stay outside her skin, and the
radial index no longer measures them.
"""

from __future__ import annotations

import asyncio
import importlib.util
import math
from pathlib import Path

import numpy as np
import pytest

from wardrobe.domain.jobs import CreateJobRequest
from wardrobe.geometry.lower_panels import GROIN_HALF_ANGLE, build_leggings_panel
from wardrobe.geometry.mesh import concatenate
from wardrobe.geometry.procedural import FitParameters
from wardrobe.vrm.measure import BodyMeasurements

ROOT = Path(__file__).resolve().parents[2]
LIBRARY = ROOT / "assets" / "library"


def _body() -> BodyMeasurements:
    return BodyMeasurements(
        height_m=1.6, shoulder_width_m=0.34, chest_width_m=0.30, waist_width_m=0.26,
        hip_width_m=0.34, arm_length_m=0.55, leg_length_m=0.78, inseam_m=0.72, depth_m=0.20,
        bone_positions={
            "spine": (0.0, 1.00, 0.0),
            "hips": (0.0, 0.90, 0.0),
            "leftUpperLeg": (0.10, 0.88, 0.0),
            "rightUpperLeg": (-0.10, 0.88, 0.0),
            "leftFoot": (0.10, 0.06, 0.0),
            "rightFoot": (-0.10, 0.06, 0.0),
        },
    )


def _cloud() -> tuple[np.ndarray, np.ndarray]:
    """A trunk with a deep front groove, and two legs. Forward is +Z."""
    ys = np.linspace(0.78, 1.06, 36)
    angles = np.linspace(0.0, 2.0 * math.pi, 64, endpoint=False)
    yy, aa = np.meshgrid(ys, angles, indexing="ij")
    radius = np.full(yy.shape, 0.14)
    groove = (np.cos(aa) > math.cos(1.0)) & (yy < 0.92) & (yy > 0.79)
    radius = np.where(groove, 0.07, radius)
    trunk = np.stack([radius * np.sin(aa), yy, radius * np.cos(aa)], axis=-1).reshape(-1, 3)
    legs = []
    for sign in (1.0, -1.0):
        ly = np.linspace(0.12, 0.79, 28)
        la = np.linspace(0.0, 2.0 * math.pi, 24, endpoint=False)
        lyy, laa = np.meshgrid(ly, la, indexing="ij")
        lr = np.full(lyy.shape, 0.055)
        legs.append(np.stack([
            sign * 0.10 + lr * np.sin(laa), lyy, lr * np.cos(laa),
        ], axis=-1).reshape(-1, 3))
    return trunk, np.vstack(legs)


def test_the_front_groin_is_outside_the_groove_and_marked():
    trunk, legs = _cloud()
    clearance = 0.0025
    params = FitParameters(
        measurements=_body(), clearance_m=clearance,
        metadata={
            "forward": 1.0,
            "coverPoints": trunk,
            "legPoints": legs,
            "lowerBody": {"crotchY": 0.80, "centreX": 0.0},
        },
    )
    pieces = build_leggings_panel(params, plain=True)
    assert pieces, "the measured body should build a panel"
    mesh = concatenate(pieces)
    groin = np.asarray(mesh.metadata["groin"], dtype=bool)
    assert groin.shape == (mesh.vertex_count,) and groin.any()
    front = mesh.positions[groin]
    # The groove is the front. The back and the waist band stay on the radial check.
    assert float(front[:, 2].min()) > 0.02
    back = mesh.positions[:, 2] < -0.04
    assert not groin[back].any()
    cover = np.vstack([trunk, legs])
    gap = np.linalg.norm(front[:, None, :] - cover[None, :, :], axis=2).min(axis=1)
    assert float(gap.min()) > 0.001, "a groin vertex is inside her skin"

    y = float(np.median(front[:, 1]))
    band = mesh.positions[np.abs(mesh.positions[:, 1] - y) < 0.012]
    side = band[np.abs(band[:, 0]) > 0.08]
    assert side.shape[0] > 0
    front_r = float(np.median(np.hypot(front[:, 0], front[:, 2])))
    side_r = float(np.median(np.hypot(side[:, 0], side[:, 2])))
    assert front_r < side_r - 0.02, "the front still bridges the groove as a flat shield"
    assert math.cos(GROIN_HALF_ANGLE) < 1.0


def test_catalog_leggings_pass_on_the_reference_base():
    """The path render_templates uses: foundation first, then the template, shorts removed."""
    avatar = LIBRARY / "AvatarSample_A.vrm"
    if not avatar.is_file():
        pytest.skip("the avatar library is not fetched (make library)")

    spec = importlib.util.spec_from_file_location(
        "render_templates", ROOT / "tools" / "catalog" / "render_templates.py")
    render = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(render)

    async def run():
        import tempfile

        from wardrobe.config import Settings
        from wardrobe.domain.garments import TemplateCatalog
        from wardrobe.library import AvatarLibrary
        from wardrobe.pipeline.orchestrator import Orchestrator
        from wardrobe.queue.jobs import AsyncioJobQueue
        from wardrobe.storage.database import InMemoryJobRepository, InMemoryWardrobeRepository
        from wardrobe.storage.object_store import LocalObjectStore

        catalog = TemplateCatalog.from_directory(ROOT / "assets" / "garment_templates")
        library = AvatarLibrary.from_directory(LIBRARY)
        template = catalog.get("trousers-leggings-v1")
        style = render.load_style()
        profile = render.profile_for(template, style, "avatar-sample-a", None)
        entry = library.get(profile["avatar"])
        with tempfile.TemporaryDirectory() as tmp:
            settings = Settings(
                _env_file=None, wardrobe_storage_root=str(Path(tmp) / "store"),
                wardrobe_engine="native", strict_licensing=True,
            )
            store = LocalObjectStore(settings.storage_root_path, settings)
            orch = Orchestrator(
                settings=settings, store=store, jobs=InMemoryJobRepository(),
                wardrobes=InMemoryWardrobeRepository(), queue=AsyncioJobQueue(concurrency=1),
                catalog=catalog,
            )
            await library.seed(store)
            base = await render._reference_base(orch, store, entry, profile["base"], profile["name"])
            result = await orch.run_now(CreateJobRequest.model_validate({
                "avatar": base,
                "outfit": {"prompt": "black Leggings", "mode": "template",
                           "templateId": template.id, "color": "black"},
                "options": {"renderPreview": False, "engine": "native",
                            "baseBody": profile["baseBody"]},
            }))
            return result

    result = asyncio.run(run())
    report = result.fit_report
    assert report is not None and report.passed, report.checks if report else result.error
    assert str(report.clipping_check) == "passed"
