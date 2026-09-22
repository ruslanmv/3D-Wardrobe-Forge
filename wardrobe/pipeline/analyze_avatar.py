"""Stage 2 — confirm the rig is humanoid and measure the body."""

from __future__ import annotations

from wardrobe.domain.avatars import AvatarAnalysis
from wardrobe.domain.jobs import JobState
from wardrobe.errors import NotHumanoid
from wardrobe.pipeline.context import PipelineContext
from wardrobe.vrm.inspect import validate_humanoid
from wardrobe.vrm.measure import MeasurementError, measure_body


async def run(context: PipelineContext) -> None:
    await context.emit(JobState.ANALYZING, "analysing humanoid body and skeleton")

    if context.document is None or context.info is None:
        raise NotHumanoid("source validation must run before analysis")

    document, info = context.document, context.info
    issues = validate_humanoid(document, info)

    fatal = [
        issue
        for issue in issues
        if "missing required humanoid bones" in issue or "does not exist" in issue
    ]
    if fatal:
        raise NotHumanoid(
            "the source model is not a usable humanoid: " + "; ".join(fatal),
            detail={"issues": issues},
        )

    for issue in issues:
        context.warn(issue)

    try:
        measurements = measure_body(document, info)
    except MeasurementError as exc:
        raise NotHumanoid(str(exc)) from exc

    low_confidence = [name for name, value in measurements.confidence.items() if value < 0.5]
    if low_confidence:
        context.warn(
            "measurements estimated with low confidence for: " + ", ".join(sorted(low_confidence))
        )

    context.measurements = measurements
    context.record.analysis = AvatarAnalysis(
        spec=str(info.spec),
        title=info.title,
        humanoidBones=dict(info.humanoid_bones),
        measurements=measurements.to_dict(),
        license=info.license.to_dict(),
        expressions=list(info.expressions),
        meshCount=info.mesh_count,
        materialCount=info.material_count,
        sha256=context.source_sha256,
        warnings=list(context.warnings),
    )

    await context.emit(
        JobState.ANALYZING,
        f"measured a {measurements.height_m:.2f}m humanoid with {len(info.humanoid_bones)} bones",
        heightM=round(measurements.height_m, 3),
        bones=len(info.humanoid_bones),
    )


__all__ = ["run"]
