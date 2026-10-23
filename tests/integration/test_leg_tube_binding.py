"""PS1. Trousers bend at her knee; a skirt is not split between her legs.

Jeans anchor at her waist and hips, which gives the binding her thigh bones and no shin: in
HomePilot's Pose Studio every seated and kneeling preset left the trouser leg straight out
from her thigh while her shin went down through it. A garment with a tube round each leg now
also binds to the leg bones of what it covers; a skirt keeps the binding it had.
"""

from __future__ import annotations

import numpy as np
import pytest

from tests.conftest import job_request
from wardrobe.domain.jobs import CreateJobRequest
from wardrobe.engines import native
from wardrobe.vrm.build import CALIBRATION_BODIES, build_vrm


@pytest.fixture(scope="module")
def body() -> bytes:
    return build_vrm(CALIBRATION_BODIES[1], spec="VRM1")


async def _bound(orchestrator, store, body, monkeypatch, template_id: str, prompt: str):
    captured = []
    original = native.bind_mesh

    def capture(mesh, segments, **kw):
        original(mesh, segments, **kw)
        captured.append((mesh, list(segments)))

    monkeypatch.setattr(native, "bind_mesh", capture)
    await store.put("sources/legs.vrm", body)
    record = await orchestrator.run_now(
        CreateJobRequest.model_validate(job_request("sources/legs.vrm", prompt, template_id=template_id))
    )
    assert record.state == "completed", record.error
    return captured[-1]


async def test_jeans_below_the_knee_follow_the_shin(orchestrator, store, body, monkeypatch):
    mesh, segments = await _bound(
        orchestrator, store, body, monkeypatch, "jeans-straight-v1", "blue straight jeans"
    )
    names = [s.name for s in segments]
    assert {"leftLowerLeg", "rightLowerLeg"} <= set(names)
    knee = max(s.head[1] for s in segments if s.name.endswith("LowerLeg"))
    below = mesh.positions[:, 1] < knee - 0.05
    assert below.sum() > 50
    dominant = np.array(names)[mesh.joints[below, np.argmax(mesh.weights[below], axis=1)].astype(int)]
    # Most of the leg below her knee is carried by her shin, not by her thigh or her hips.
    assert np.mean(np.char.endswith(dominant.astype(str), "LowerLeg")) > 0.8


async def test_a_skirt_is_not_bound_to_her_shins(orchestrator, store, body, monkeypatch):
    _mesh, segments = await _bound(
        orchestrator, store, body, monkeypatch, "skirt-pencil-v1", "black pencil skirt"
    )
    assert not any(s.name.endswith("LowerLeg") for s in segments)


def test_only_close_short_dresses_and_skirts_are_bound_like_skin(template_catalog):
    """PS3. A bodycon mini follows her skin; a flared, pleated or long skirt still hangs."""
    from types import SimpleNamespace

    def plan_for(template_id):
        return SimpleNamespace(hem=template_catalog.get(template_id).hem)

    def bound_like_skin(template_id):
        return native.fitted_short(template_catalog.get(template_id), plan_for(template_id))

    assert bound_like_skin("dress-mini-bodycon-v1")
    assert bound_like_skin("skirt-glam-pencil-mini-v1")
    for hanging in (
        "skirt-pleated-mini-v1",
        "skirt-skater-mini-v1",
        "skirt-pencil-v1",
        "dress-maxi-sundress-v1",
        "dress-slip-midi-v1",
    ):
        assert not bound_like_skin(hanging), hanging


def test_no_underwear_template_or_guepiere_source_changed():
    import hashlib
    import json
    from pathlib import Path

    root = Path(__file__).resolve().parents[2]
    inventory = json.loads(
        (root / "assets/catalog/adult/underwear-inventory.json").read_text(encoding="utf-8")
    )
    for item in inventory["templates"]:
        assert hashlib.sha256((root / item["file"]).read_bytes()).hexdigest() == item["sha256"], item["id"]
