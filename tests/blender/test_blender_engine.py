"""Blender engine tests.

These are skipped unless a Blender binary is on PATH, and are what the
``blender-integration`` workflow runs. Everything else in the suite is
deliberately Blender-free.
"""

from __future__ import annotations

import shutil

import pytest

from tests.conftest import job_request
from wardrobe.config import Settings
from wardrobe.domain.jobs import CreateJobRequest, JobState
from wardrobe.engines import BlenderEngine, NativeEngine, create_engine
from wardrobe.vrm.document import GltfDocument
from wardrobe.vrm.inspect import REQUIRED_HUMANOID_BONES, inspect_document, validate_humanoid

blender_available = shutil.which(Settings().blender_bin) is not None
requires_blender = pytest.mark.skipif(not blender_available, reason="Blender is not installed")


# ----------------------------------------------------------------------
# selection logic (runs everywhere)
# ----------------------------------------------------------------------
def test_explicit_engine_selection(settings: Settings):
    assert isinstance(create_engine("native", settings), NativeEngine)
    assert isinstance(create_engine("blender", settings), BlenderEngine)


def test_auto_falls_back_to_native_without_blender(settings: Settings):
    engine = create_engine("auto", settings.model_copy(update={"blender_bin": "definitely-not-blender"}))
    assert isinstance(engine, NativeEngine)


def test_unknown_engine_is_an_error(settings: Settings):
    with pytest.raises(ValueError, match="unknown fitting engine"):
        create_engine("houdini", settings)


def test_availability_matches_the_environment(settings: Settings):
    assert BlenderEngine.available(settings) == blender_available
    assert NativeEngine.available(settings) is True


# ----------------------------------------------------------------------
# real Blender runs
# ----------------------------------------------------------------------
@requires_blender
async def test_blender_engine_produces_a_valid_vrm(orchestrator, store, settings, vrm_bytes):
    key = "sources/blender.vrm"
    await store.put(key, vrm_bytes)

    orchestrator.settings = settings.model_copy(update={"wardrobe_engine": "blender"})
    record = await orchestrator.run_now(
        CreateJobRequest.model_validate(
            job_request(key, "elegant burgundy evening dress", engine="blender", render_preview=True)
        )
    )

    assert record.state is JobState.COMPLETED, record.error
    assert record.fit_report.engine == "blender"

    output = await orchestrator.store.get(f"looks/{record.look.id}/look.vrm")
    document = GltfDocument.from_bytes(output)
    info = inspect_document(document)

    assert set(info.humanoid_bones) >= REQUIRED_HUMANOID_BONES
    assert validate_humanoid(document, info) == []
    assert record.fit_report.weights_valid
    assert record.fit_report.pose_tests.get("passed") is True


@requires_blender
async def test_blender_masks_covered_body_polygons(orchestrator, store, settings, vrm_bytes):
    """The capability the native engine does not have."""
    key = "sources/mask.vrm"
    await store.put(key, vrm_bytes)

    orchestrator.settings = settings.model_copy(update={"wardrobe_engine": "blender"})
    record = await orchestrator.run_now(
        CreateJobRequest.model_validate(job_request(key, "a long black dress", engine="blender"))
    )

    assert record.state is JobState.COMPLETED, record.error
    assert record.fit_report.coverage.get("masked") is True
    assert record.fit_report.coverage.get("coveredVertices", 0) > 0
