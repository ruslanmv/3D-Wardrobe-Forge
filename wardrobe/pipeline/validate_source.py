"""Stage 1 — fetch the source avatar and decide whether we may touch it.

Nothing downstream runs until this stage has established that the file is a
real VRM, that it is within size limits, that it matches the caller's hash if
one was given, and that its usage terms permit deriving a new model.
"""

from __future__ import annotations

import logging

import httpx

from wardrobe.domain.jobs import FailureReason, JobState
from wardrobe.errors import AttestationRequired, LicenseRejected, SourceRejected
from wardrobe.pipeline.context import PipelineContext
from wardrobe.policy import file_safety, licensing
from wardrobe.vrm.document import GltfDocument, UnsupportedAsset
from wardrobe.vrm.glb import GlbError
from wardrobe.vrm.inspect import NotAVrm, inspect_document

logger = logging.getLogger(__name__)


async def fetch_source(context: PipelineContext) -> bytes:
    """Read the source VRM from a URL or from object storage."""
    avatar = context.record.request.avatar
    settings = context.settings

    if avatar.storage_key:
        key = file_safety.validate_storage_key(avatar.storage_key)
        try:
            data = await context.store.get(key)
        except (OSError, KeyError) as exc:
            raise SourceRejected(
                f"stored avatar {key!r} could not be read", reason=FailureReason.SOURCE_UNREACHABLE
            ) from exc
        file_safety.check_size(len(data), settings)
        return data

    url = file_safety.require_source_url(str(avatar.url), settings)
    limit = settings.max_avatar_bytes
    chunks: list[bytes] = []
    total = 0

    try:
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(settings.fetch_timeout_s),
            follow_redirects=False,  # a redirect could escape the SSRF checks
        ) as client, client.stream("GET", url) as response:
                if response.status_code >= 400:
                    raise SourceRejected(
                        f"source avatar returned HTTP {response.status_code}",
                        reason=FailureReason.SOURCE_UNREACHABLE,
                    )
                declared = response.headers.get("content-length")
                if declared and declared.isdigit():
                    file_safety.check_size(int(declared), settings)

                async for chunk in response.aiter_bytes():
                    total += len(chunk)
                    if total > limit:
                        raise SourceRejected(
                            f"source avatar exceeds the {limit} byte limit",
                            reason=FailureReason.SOURCE_TOO_LARGE,
                        )
                    chunks.append(chunk)
    except httpx.HTTPError as exc:
        raise SourceRejected(
            f"source avatar could not be fetched: {exc}", reason=FailureReason.SOURCE_UNREACHABLE
        ) from exc

    return b"".join(chunks)


async def run(context: PipelineContext) -> None:
    await context.emit(JobState.VALIDATING, "checking the source avatar")

    avatar = context.record.request.avatar
    data = await fetch_source(context)

    file_safety.check_size(len(data), context.settings)
    file_safety.sniff_vrm(data)
    context.source_sha256 = file_safety.verify_hash(data, avatar.sha256)

    try:
        document = GltfDocument.from_bytes(data)
    except GlbError as exc:
        raise SourceRejected(str(exc), reason=FailureReason.SOURCE_NOT_A_VRM) from exc
    except UnsupportedAsset as exc:
        raise SourceRejected(str(exc), reason=FailureReason.UNSUPPORTED_ASSET) from exc

    try:
        info = inspect_document(document)
    except NotAVrm as exc:
        raise SourceRejected(str(exc), reason=FailureReason.SOURCE_NOT_A_VRM) from exc

    # ---- licensing ----------------------------------------------------
    decision = licensing.evaluate(info.license, avatar.license, strict=context.settings.strict_licensing)
    if not decision.allowed:
        message = decision.message
        if decision.requires_attestation:
            raise AttestationRequired(message, detail=decision.evidence)
        raise LicenseRejected(message, detail=decision.evidence)

    # ---- keep a copy on disk for the Blender engine --------------------
    context.workdir.mkdir(parents=True, exist_ok=True)
    source_path = context.workdir / "source.vrm"
    source_path.write_bytes(data)

    context.source_bytes = data
    context.source_path = source_path
    context.document = document
    context.info = info

    await context.emit(
        JobState.VALIDATING,
        f"accepted {info.spec} source ({len(data)} bytes)",
        spec=str(info.spec),
        license=decision.message,
    )


__all__ = ["run", "fetch_source"]
