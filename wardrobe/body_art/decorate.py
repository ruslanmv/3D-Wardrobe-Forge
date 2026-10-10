"""BA4. Decide each requested tattoo on the finished outfit, then add the ones her clothes leave room for.

Clothes first (docs/BODY_ART_PLAN.md §0). This runs on the assembled VRM, after every
garment is planned, replaced, built and fitted, and it never changes one: a tattoo the
outfit would hide is not made, and an explicit request does not override clothing —
"jacket + trousers + upper-back tattoo" keeps the jacket and says why the tattoo is not
there. Each item is decided on its own, in this order:

1. the design exists and is drawn for that placement (the API refused it otherwise);
2. the gate, exactly as garments are gated: a ``swimwear`` or ``intimate`` placement
   needs the model's own terms and an operator's declaration that the avatar depicts an
   adult. Adulthood is never inferred from how an avatar looks;
3. exposure: at least 90% of the tattoo's footprint visible on the finished outfit;
4. projection: it lands on her skin without stretching.

An item that fails any of them is reported, not raised: the outfit is the job, and the
job completes.
"""

from __future__ import annotations

from dataclasses import dataclass

from wardrobe.body_art.catalog import BodyArtCatalog
from wardrobe.body_art.contract import PLACEMENTS, BodyArtRequest
from wardrobe.body_art.exposure import Exposure, exposure, read_body
from wardrobe.body_art.materials import add_decal, remove_decals
from wardrobe.body_art.placement import PlacementError
from wardrobe.body_art.project import Decal, ProjectionError, build_decal
from wardrobe.body_art.raster import artwork_texture, coverage
from wardrobe.policy import intimate
from wardrobe.vrm.document import GltfDocument
from wardrobe.vrm.inspect import VrmInfo

#: Which garment category's gate a rated placement goes through.
GATE_CATEGORY = {"swimwear": "swimwear", "intimate": "underwear"}
#: Long side of a decal's texture.
TEXTURE_SIZE = 1024


@dataclass
class Outcome:
    request: BodyArtRequest
    rating: str
    applied: bool = False
    reason: str | None = None
    exposure: Exposure | None = None
    decal: Decal | None = None
    node: int | None = None
    #: BA6. Carried from the look this job builds on, not asked for in this job.
    inherited: bool = False
    #: BA6. Inherited, still visible, and its decal still drawn: left exactly as it was.
    kept: bool = False

    @property
    def state(self) -> str:
        """The recipe's state on the look this job makes (lifecycle.INHERITED_STATES travel on)."""
        if self.applied:
            return "applied"
        if not self.inherited:
            return "not-applied"  # asked for and refused: never added to a later look unasked
        if self.exposure is not None and not self.exposure.applies:
            return "covered"
        return "held"  # once on her skin, kept for later, not drawn now for another reason

    @property
    def sentence(self) -> str:
        """What the report says about it, in words."""
        name = PLACEMENTS[self.request.placement].name
        if self.kept:
            return f"{name} tattoo kept"
        if self.applied:
            return f"{name} tattoo {'re-applied' if self.inherited else 'applied'}"
        if self.inherited and self.state == "covered":
            return f"{name} tattoo is under the outfit; it comes back on a look that shows it"
        if self.inherited:
            return f"{name} tattoo not shown on this look — {self.reason}"
        return f"{name} tattoo not applied — {self.reason}"

    def report(self) -> dict:
        entry = {
            "design": self.request.design,
            "placement": self.request.placement,
            "rating": self.rating,
            "applied": self.applied,
            "state": self.state,
            "inherited": self.inherited,
            "reason": self.reason,
            "message": self.sentence,
        }
        if self.exposure is not None:
            entry.update(
                {
                    "visible": round(self.exposure.visible, 3),
                    "underHair": round(self.exposure.under_hair, 3),
                    "coveredBy": self.exposure.covered_by,
                }
            )
        if self.decal is not None:
            entry.update(self.decal.report())
        return entry


def decide(
    document: GltfDocument,
    items: list[BodyArtRequest],
    catalog: BodyArtCatalog,
    *,
    depicts_adult: bool,
    terms,
    inherited: list[BodyArtRequest] = (),
    live: set[str] = frozenset(),
) -> list[Outcome]:
    """Every item's fate on this finished document. Reads it; changes nothing.

    ``inherited`` are the recipes of the look this job builds on (BA6, ``lifecycle``),
    decided exactly as requests are — gate, exposure, projection — so a tattoo carried
    onto a new outfit is held to the same rules as one asked for on it. ``live`` are the
    placements already drawn: an inherited tattoo still visible there is kept, not rebuilt.
    """
    outcomes: list[Outcome] = []
    body = surfaces = None
    marked = [(item, False) for item in items] + [(item, True) for item in inherited]
    #: Placements a new tattoo in this job is drawn at: an inherited one there gives way.
    replaced: set[str] = set()
    for item, carried in marked:
        if carried and item.placement in replaced:
            continue
        problem = catalog.check(item.design, item.placement)
        if problem is not None:
            outcomes.append(
                Outcome(item, PLACEMENTS[item.placement].rating, reason=problem, inherited=carried)
            )
            continue
        rating = catalog.rating(item.design, item.placement)
        outcome = Outcome(item, rating, inherited=carried)
        outcomes.append(outcome)
        if rating in GATE_CATEGORY:
            decision = intimate.evaluate(
                GATE_CATEGORY[rating],
                terms,
                depicts_adult=depicts_adult,
                requires_adult=True,
                reason=f"{rating} body art",
            )
            if not decision.allowed:
                outcome.reason = decision.message
                continue
        if body is None:
            try:
                surfaces, body = read_body(document)
            except PlacementError as exc:
                outcome.reason = str(exc)
                body = False
                continue
        if body is False:
            outcome.reason = "her skin could not be found on this avatar"
            continue
        design = catalog.get(item.design)
        measured, fp = exposure(surfaces, body, item.placement, design.aspect, item)
        outcome.exposure = measured
        if not measured.applies:
            outcome.reason = measured.reason
            continue
        if carried and item.placement in live:
            outcome.applied = outcome.kept = True
            continue
        ink = coverage(catalog.artwork_path(design), 256)
        try:
            outcome.decal = build_decal(body, fp, ink)
            if not carried:
                replaced.add(item.placement)
        except ProjectionError as exc:
            outcome.reason = str(exc)
    return outcomes


def apply(
    document: GltfDocument,
    info: VrmInfo,
    outcomes: list[Outcome],
    catalog: BodyArtCatalog,
    remove: list[str],
) -> list[str]:
    """Add every decided decal; take off Forge body art it replaces or the request removes.

    Returns the placements whose earlier Forge tattoo was taken off.
    """
    replacing = {o.request.placement for o in outcomes if o.decal is not None}
    # BA6. An inherited tattoo the new outfit hides is dropped from the geometry (I3); its
    # recipe stays below, so a later look that shows the spot puts it back.
    hidden = {o.request.placement for o in outcomes if o.inherited and not o.applied}
    removed = remove_decals(document, set(remove) | replacing | hidden)
    for outcome in outcomes:
        if outcome.decal is None:
            continue
        item = outcome.request
        design = catalog.get(item.design)
        png, scale, offset = artwork_texture(catalog.artwork_path(design), TEXTURE_SIZE)
        tag = {
            "kind": "bodyArt",
            "design": item.design,
            "placement": item.placement,
            "rating": outcome.rating,
            "version": 1,
        }
        outcome.node = add_decal(
            document,
            info,
            outcome.decal,
            texture_png=png,
            uv_scale=scale,
            uv_offset=offset,
            ink_srgb=item.ink_rgb(),
            opacity=item.opacity,
            name=f"{item.placement} {item.design}",
            tag=tag,
        )
        outcome.applied = True
    extras = document.gltf.setdefault("extras", {}).setdefault("wardrobeForge", {})
    extras["bodyArt"] = [
        {
            **o.request.model_dump(by_alias=True),
            "rating": o.rating,
            "applied": o.applied,
            "state": o.state,
            "reason": o.reason,
        }
        for o in outcomes
    ]
    if removed:
        extras["bodyArtRemoved"] = sorted(set(removed))
    return removed


__all__ = ["GATE_CATEGORY", "Outcome", "apply", "decide"]
