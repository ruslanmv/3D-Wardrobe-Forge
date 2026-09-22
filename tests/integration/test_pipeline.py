"""The orchestrator end to end, including every rejection path."""

from __future__ import annotations

from tests.conftest import job_request
from wardrobe.domain.jobs import CreateJobRequest, FailureReason, JobState
from wardrobe.vrm.build import BodyProportions, build_vrm
from wardrobe.vrm.document import GltfDocument
from wardrobe.vrm.inspect import inspect_document


async def run(orchestrator, payload: dict):
    return await orchestrator.run_now(CreateJobRequest.model_validate(payload))


# ----------------------------------------------------------------------
# happy path
# ----------------------------------------------------------------------
async def test_template_job_completes(orchestrator, stored_avatar):
    record = await run(orchestrator, job_request(stored_avatar, "elegant burgundy evening dress"))

    assert record.state is JobState.COMPLETED
    assert record.look is not None
    assert record.look.vrm_url.endswith("look.vrm")
    assert record.fit_report.passed


async def test_progress_events_are_recorded_in_order(orchestrator, stored_avatar):
    record = await run(orchestrator, job_request(stored_avatar, "black cocktail dress"))
    states = [event.state for event in record.events]

    for expected in (
        JobState.QUEUED,
        JobState.VALIDATING,
        JobState.ANALYZING,
        JobState.PLANNING,
        JobState.GENERATING,
        JobState.FITTING,
        JobState.SKINNING,
        JobState.CLIPPING,
        JobState.EXPORTING,
        JobState.VALIDATING_OUTPUT,
        JobState.COMPLETED,
    ):
        assert expected in states, f"missing state {expected}"

    assert states.index(JobState.FITTING) < states.index(JobState.EXPORTING)
    assert record.events[-1].progress == 1.0


async def test_artifacts_are_stored(orchestrator, stored_avatar):
    record = await run(
        orchestrator, job_request(stored_avatar, "a red dress", render_preview=True)
    )
    look_key = f"looks/{record.look.id}"

    assert await orchestrator.store.exists(f"{look_key}/look.vrm")
    assert await orchestrator.store.exists(f"{look_key}/fit-report.json")
    assert await orchestrator.store.exists(f"{look_key}/preview.webp")


async def test_wardrobe_manifest_accumulates_looks(orchestrator, stored_avatar):
    await run(orchestrator, job_request(stored_avatar, "a red dress", avatar_id="mira"))
    await run(orchestrator, job_request(stored_avatar, "a blue skirt", avatar_id="mira"))

    manifest = await orchestrator.wardrobes.get("mira")
    assert manifest is not None
    generated = [look for look in manifest.looks if look.type == "vrmVariant"]
    assert len(generated) == 2
    assert manifest.get("original") is not None


async def test_analysis_is_attached(orchestrator, stored_avatar):
    record = await run(orchestrator, job_request(stored_avatar, "a green dress"))
    assert record.analysis is not None
    assert record.analysis.spec == "VRM1"
    assert record.analysis.measurements["heightM"] > 1.0


async def test_source_avatar_is_still_intact_afterwards(orchestrator, stored_avatar, vrm_bytes):
    """'original avatar remains recoverable' from the acceptance criteria."""
    await run(orchestrator, job_request(stored_avatar, "a dress"))
    assert await orchestrator.store.get(stored_avatar) == vrm_bytes


# ----------------------------------------------------------------------
# rejections
# ----------------------------------------------------------------------
async def test_model_forbidding_modification_is_rejected(orchestrator, store):
    data = build_vrm(BodyProportions(name="locked", modification="prohibited"), spec="VRM1")
    await store.put("sources/locked.vrm", data)

    record = await run(orchestrator, job_request("sources/locked.vrm", "a dress"))
    assert record.state is JobState.REJECTED
    assert record.reason is FailureReason.MODIFICATION_NOT_PERMITTED


async def test_unknown_terms_require_attestation(orchestrator, store, vrm_bytes):
    document = GltfDocument.from_bytes(vrm_bytes)
    document.gltf["extensions"]["VRMC_vrm"]["meta"]["modification"] = "something-else"
    await store.put("sources/unknown.vrm", document.to_bytes())

    record = await run(orchestrator, job_request("sources/unknown.vrm", "a dress"))
    assert record.state is JobState.REJECTED
    assert record.reason is FailureReason.LICENSE_ATTESTATION_REQUIRED


async def test_attestation_unblocks_unknown_terms(orchestrator, store, vrm_bytes):
    document = GltfDocument.from_bytes(vrm_bytes)
    document.gltf["extensions"]["VRMC_vrm"]["meta"]["modification"] = "something-else"
    await store.put("sources/unknown.vrm", document.to_bytes())

    payload = job_request("sources/unknown.vrm", "a dress")
    payload["avatar"]["license"] = {"userAttestsModificationAllowed": True}

    record = await run(orchestrator, payload)
    assert record.state is JobState.COMPLETED


async def test_non_vrm_file_is_rejected(orchestrator, store):
    await store.put("sources/notes.txt", b"this is not a model at all")
    record = await run(orchestrator, job_request("sources/notes.txt", "a dress"))

    assert record.state is JobState.REJECTED
    assert record.reason is FailureReason.SOURCE_NOT_A_VRM


async def test_glb_without_vrm_extension_is_rejected(orchestrator, store, vrm_bytes):
    document = GltfDocument.from_bytes(vrm_bytes)
    document.gltf.pop("extensions")
    document.gltf.pop("extensionsRequired", None)
    await store.put("sources/plain.glb", document.to_bytes())

    record = await run(orchestrator, job_request("sources/plain.glb", "a dress"))
    assert record.reason is FailureReason.SOURCE_NOT_A_VRM


async def test_non_humanoid_rig_is_rejected(orchestrator, store, vrm_bytes):
    document = GltfDocument.from_bytes(vrm_bytes)
    bones = document.gltf["extensions"]["VRMC_vrm"]["humanoid"]["humanBones"]
    for bone in ("leftHand", "rightHand", "leftFoot"):
        bones.pop(bone, None)
    await store.put("sources/partial.vrm", document.to_bytes())

    record = await run(orchestrator, job_request("sources/partial.vrm", "a dress"))
    assert record.state is JobState.REJECTED
    assert record.reason is FailureReason.SOURCE_NOT_HUMANOID


async def test_hash_mismatch_is_rejected(orchestrator, stored_avatar):
    payload = job_request(stored_avatar, "a dress")
    payload["avatar"]["sha256"] = "0" * 64

    record = await run(orchestrator, payload)
    assert record.reason is FailureReason.HASH_MISMATCH


async def test_generated_mode_without_a_provider_is_reported(orchestrator, stored_avatar):
    record = await run(orchestrator, job_request(stored_avatar, "a dress", mode="generated"))
    assert record.state is JobState.FAILED
    assert record.reason is FailureReason.PROVIDER_ERROR


async def test_missing_source_is_rejected(orchestrator):
    record = await run(orchestrator, job_request("sources/does-not-exist.vrm", "a dress"))
    assert record.reason is FailureReason.SOURCE_UNREACHABLE


# ----------------------------------------------------------------------
# queue
# ----------------------------------------------------------------------
async def test_submit_runs_through_the_queue(orchestrator, stored_avatar):
    await orchestrator.start()
    try:
        record = await orchestrator.submit(
            CreateJobRequest.model_validate(job_request(stored_avatar, "a navy blazer"))
        )
        assert record.state is JobState.QUEUED

        await orchestrator.queue.drain(timeout=60)
        finished = await orchestrator.get(record.id)
        assert finished.state is JobState.COMPLETED
    finally:
        await orchestrator.stop()


async def test_events_are_published_to_subscribers(orchestrator, stored_avatar):
    record = await run(orchestrator, job_request(stored_avatar, "a dress"))
    published = orchestrator.broker.history(record.id)
    assert [event.state for event in published][-1] is JobState.COMPLETED


# ----------------------------------------------------------------------
# output integrity
# ----------------------------------------------------------------------
async def test_output_vrm_is_loadable_and_gained_a_garment(orchestrator, stored_avatar, vrm_bytes):
    record = await run(orchestrator, job_request(stored_avatar, "a long black dress"))
    output = await orchestrator.store.get(f"looks/{record.look.id}/look.vrm")

    source_info = inspect_document(GltfDocument.from_bytes(vrm_bytes))
    result = GltfDocument.from_bytes(output)
    result_info = inspect_document(result)

    assert result_info.spec == source_info.spec
    assert set(source_info.humanoid_bones) <= set(result_info.humanoid_bones)
    assert result_info.mesh_count == source_info.mesh_count + 1
    assert result.gltf["extras"]["wardrobeForge"]["lookId"] == record.look.id
