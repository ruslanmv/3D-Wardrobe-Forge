"""Stage 3c (DC1) — stand her in the shoes the outfit puts on: feet turned down, lifted onto heels.

Runs after the base body is prepared (her own shoes are off, if they are coming off) and
before anything is built, so every garment of the outfit is fitted to her as she will
stand: a mini dress's hem is where it will be, an over-the-knee boot's shaft is round
her leg as it will be. ``wardrobe.vrm.stance`` does the work and says why.

Only an outfit with shoes in it changes her stance, to what those shoes ask (flat for
shoes without a ``boot`` block). An outfit without shoes leaves it alone: a dress put on
a look that has boots keeps her on their heels, because the boots are still on her.
"""

from __future__ import annotations

from wardrobe.domain.jobs import JobState
from wardrobe.geometry.boots import INSOLE_M
from wardrobe.pipeline.context import PipelineContext
from wardrobe.vrm import stance
from wardrobe.vrm.inspect import VrmSpec
from wardrobe.vrm.measure import MeasurementError, measure_body


def shoe_spec(context: PipelineContext) -> dict | None:
    """The ``boot`` block of the outfit's shoes ({} for shoes without one), or None for no shoes."""
    for plan in context.plan.garments:
        template = context.catalog.get(plan.template_id) if plan.template_id else None
        category = template.category if template is not None else plan.category
        if category == "shoes":
            return dict(template.boot or {}) if template is not None else {}
    return None


def _forward(context: PipelineContext) -> float:
    bones = context.measurements.bone_positions
    for side in ("left", "right"):
        foot, toes = bones.get(f"{side}Foot"), bones.get(f"{side}Toes")
        if foot is not None and toes is not None and abs(float(toes[2]) - float(foot[2])) > 1e-4:
            return 1.0 if float(toes[2]) > float(foot[2]) else -1.0
    return -1.0 if context.info.spec is VrmSpec.VRM0 else 1.0


async def run(context: PipelineContext) -> None:
    if context.plan is None or context.document is None or context.info is None:
        return
    if context.measurements is None:
        return
    spec = shoe_spec(context)
    if spec is None:
        return
    forward = _forward(context)
    heel_m = float(spec.get("heelMm") or 0.0) / 1000.0
    platform_m = float(spec.get("platformMm") or 0.0) / 1000.0
    if heel_m > 0.0 or platform_m > 0.0:
        # Her foot rests on the insole, not on the sole: the boot has a floor under her.
        heel_m, platform_m = heel_m + INSOLE_M, platform_m + INSOLE_M
    target = stance.stance_for(
        context.document, context.info, heel_m=heel_m, platform_m=platform_m, forward=forward
    )
    if target is None:
        context.warn(
            "these shoes have a heel, but the rig has no foot and toe bones to stand her on it: "
            "she stands flat in them"
        )
        return
    previous = stance.apply(context.document, context.info, target, forward=forward)
    if target.flat and previous.flat:
        return  # flat shoes on flat feet: the job and its report are what they always were
    context.fit_report.stance = {**target.to_dict(), "previous": previous.to_dict()}
    if previous == target:
        return
    try:
        context.measurements = measure_body(context.document, context.info)
    except MeasurementError as exc:  # pragma: no cover - the bones are all still there
        context.warn(f"re-measuring her on her heels failed ({exc}); using the flat measurements")
    await context.emit(
        JobState.PLANNING, f"standing her on {target.heel_m * 1000:.0f} mm heels", stance=target.to_dict()
    )


__all__ = ["run", "shoe_spec"]
