"""Stage 3c (BS1–BS3) — build the body surface the outfit is fitted to, when the job asks for one.

Runs after Base Body Prep and the stance bake (she is undressed where the outfit replaces her
clothes, and standing on her heels) and before any garment is generated, so every garment is
built and fitted against the same surface. A job without ``bodySurface`` returns at once:
nothing is read, nothing changes, the report has no ``bodySurface`` block.

In order, each step able to stop the job before anything is built:

1. **Profile** — looked up in the server's allowlist (``assets/body_surface``); unknown, or
   failing its provenance check, and the job is refused with ``body_surface_profile_unavailable``.
2. **Gate** — ``wardrobe.body_surface.gate``: the model's terms, the operator's switch and the
   adult declaration, for an adult profile. A collision-only profile needs none of them.
3. **Her skin** — read per position buffer (``surface.skin_parts``); none found and the job
   continues without a body surface, with a warning: fitting to her stored body is what it did
   before, and failing her outfit over an optional extra would be worse.
4. **Regions** — made into morph targets (``regions.build_regions``), each kept or dropped with
   its reason; a dropped region never fails the job.
5. **Collision body** — ``collision.build_state``.

The source bytes and her stored POSITION data are never modified here.
"""

from __future__ import annotations

from wardrobe.body_surface import gate
from wardrobe.body_surface.collision import build_state
from wardrobe.body_surface.library import library_at
from wardrobe.body_surface.regions import build_regions
from wardrobe.body_surface.surface import skin_parts
from wardrobe.domain.jobs import JobState
from wardrobe.errors import BodySurfaceNotPermitted, BodySurfaceUnavailable
from wardrobe.pipeline.context import PipelineContext


async def run(context: PipelineContext) -> None:
    request = context.record.request.body_surface
    if request is None or context.document is None or context.measurements is None:
        return
    library = library_at(str(context.settings.body_surface_root_path))
    profile = library.profiles.get(request.profile_id)
    if profile is None:
        raise BodySurfaceUnavailable(
            f"no body-surface profile {request.profile_id!r} on this server",
            detail={"profileId": request.profile_id, "available": sorted(library.profiles)},
        )
    decision = gate.evaluate(
        profile.capability, context.info.license if context.info is not None else None,
        operator_enabled=context.settings.wardrobe_adult_body_surface,
        depicts_adult=bool(context.record.request.avatar.depicts_adult),
    )
    if not decision.allowed:
        raise BodySurfaceNotPermitted(decision.message, detail={"profileId": profile.id,
                                                                "refusedBy": decision.refused_by})

    parts = skin_parts(context.document, context.measurements.bone_positions)
    if not parts:
        context.warn("body surface: no skinned skin found on this avatar; fitted to her stored body instead")
        context.fit_report.body_surface = {"profile": profile.id, "built": False, "reason": "no skin found"}
        return

    marks = None
    if profile.regions:
        from wardrobe.body_surface.anchors import measured_landmarks  # reads the shell fitter's helpers

        marks = measured_landmarks(context)
    if marks is not None:
        render, morphs, results = build_regions(parts, profile, marks, context.measurements.waist_width_m)
    else:
        render = {p.accessor: p.positions for p in parts}
        morphs, results = [], []
        if profile.regions:
            context.warn("body surface: her landmarks could not be measured; no region was made")
    for result in results:
        if not result.made:
            context.warn(f"body surface: {result.key} not made — {result.reason}")
    state = build_state(parts, render, morphs, results, profile, request.detail_level)
    context.body_surface = state
    context.fit_report.body_surface = {"built": True, **state.to_report()}
    await context.emit(
        JobState.PLANNING,
        f"body surface '{profile.id}': {sum(r.made for r in results)} region(s), collision body ready",
        profile=profile.id, regions=[r.key for r in results if r.made],
    )


__all__ = ["run"]
