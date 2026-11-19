"""Private authored-body preparation. Never generates or completes geometry."""
import hashlib
import logging
import re

from wardrobe.body_surface.eligibility import assess, detail_clearance
from wardrobe.errors import BodyIncompleteForBare, BodySurfaceNotPermitted
from wardrobe.vrm import body_completion, body_detail
from wardrobe.vrm.body_integrity import check_body
from wardrobe.vrm.completion_join import measure_join
from wardrobe.vrm.garment_inventory import build_strip_plan, garment_inventory, remove_garments
from wardrobe.vrm.skin_restore import restoration_verdict, restore_skin, skin_census

logger = logging.getLogger(__name__)


async def prepare(context, *, dressed: bool = False):
    request = context.record.request
    # BE1. One eligibility contract: author licence, operator switch, adult declaration, a
    # design clearance bound to this exact file's SHA-256, and a private session. Before BE1 this
    # called the gate without the design question, so a declaration alone opened bare.
    eligibility = assess(terms=context.info.license,
                         operator_enabled=context.settings.wardrobe_adult_body_surface,
                         depicts_adult=bool(request.avatar.depicts_adult),
                         private=bool(request.options.private),
                         source_sha256=context.source_sha256,
                         review_root=context.settings.body_surface_root_path,
                         reference_root=context.settings.wardrobe_calibration_root)
    if not eligibility.allowed:
        raise BodySurfaceNotPermitted(eligibility.message, detail={"refusedBy": eligibility.refused_by,
                                                                   "eligibility": eligibility.to_dict()})
    # BD1. Asked first, before any work: painted detail needs a full review (or Forge's own body).
    preset = getattr(request.options, "bare_detail", None)
    detail_cleared = None
    if preset:
        detail_cleared = detail_clearance(context.settings.body_surface_root_path,
                                          context.settings.wardrobe_calibration_root, context.source_sha256)
        if detail_cleared is None:
            raise BodySurfaceNotPermitted(
                "body detail needs a full adult-design review of this exact file: clearly-adult, its "
                f"review packet, and at least {body_detail_evidence()} characters of evidence "
                "(adult-design-reviews.json), or Forge's synthetic adult reference",
                detail={"refusedBy": "detail-review", "eligibility": eligibility.to_dict()})
    doc = context.document
    # A prior BC1 look is not the avatar's authored body.
    for item in [*doc.meshes, *doc.nodes]:
        tag = (item.get("extras") or {}).get("wardrobeForge") or {}
        if "bodyProxy" in tag or tag.get("kind") == "bodyProxy":
            raise BodyIncompleteForBare("bodyProxy is not an authored body")
    # Author-labelled anatomy is never treated as painted clothing. Ambiguity refuses
    # rather than repainting that material; painted-skin QA still runs before publication.
    anatomy = re.compile(r"genital|vulva|penis|scrot|nipple|areola|anatom", re.I)
    protected = {i for i, m in enumerate(doc.materials)
                 if anatomy.search(m.get("name", "")) or (m.get("extras") or {}).get("authoredAnatomy")}
    # AF4. A primitive drawn with a material the author labelled anatomical is part of her body,
    # whatever a garment detector made of it (a dark, tight-fitting surface reads like briefs):
    # it is kept, not stripped and not a reason to refuse; the report lists what was kept, so a
    # mislabelled garment is visible in review. Identified by material, which does not move when
    # other primitives of the same mesh are taken off.
    def is_anatomy(garment) -> bool:
        material = doc.meshes[garment.mesh]["primitives"][garment.primitive].get("material")
        return material in protected

    detected = garment_inventory(doc)
    kept_anatomy = sorted({doc.meshes[g.mesh]["primitives"][g.primitive]["material"]
                           for g in detected if is_anatomy(g)})
    inventory = [g for g in detected if not is_anatomy(g)]
    plan = build_strip_plan(inventory, [], replace_all=True)
    if len(plan.remove) != len(inventory):
        raise BodyIncompleteForBare("not every detected garment can be removed")
    removed = {(g.mesh, g.primitive) for g in inventory}
    completion = _complete_if_asked(context, doc, inventory, removed)
    fingerprints = {}
    labelled_anatomy = set()
    for ni in doc.mesh_nodes():
        node = doc.nodes[ni]
        mesh = doc.meshes[node["mesh"]]
        if (anatomy.search(node.get("name", "") + mesh.get("name", ""))
                or (node.get("extras") or {}).get("authoredAnatomy")
                or (mesh.get("extras") or {}).get("authoredAnatomy")):
            labelled_anatomy.update((node["mesh"], pi) for pi in range(len(mesh["primitives"])))
            protected.update(p["material"] for p in mesh["primitives"] if "material" in p)
        for pi, primitive in enumerate(mesh["primitives"]):
            if (node["mesh"], pi) in removed:
                continue
            accessors = [*primitive.get("attributes", {}).values(), primitive.get("indices")]
            accessors += [a for target in primitive.get("targets", []) for a in target.values()]
            for accessor in accessors:
                if accessor is not None:
                    fingerprints[accessor] = hashlib.sha256(doc.read_accessor(accessor).tobytes()).hexdigest()
    # A whole node or mesh labelled anatomical that also holds detected garments is ambiguous at
    # the primitive level: refuse for manual review rather than strip anything of it.
    if labelled_anatomy & removed:
        raise BodyIncompleteForBare(
            "authored anatomy was classified as clothing; manual source review required")
    remove_garments(doc, list(plan.remove))
    restored = restore_skin(doc, context.measurements, set(), preserve_normals=True,
                            protected_materials=protected, include_feet=True)
    if any(hashlib.sha256(doc.read_accessor(a).tobytes()).hexdigest() != digest
           for a, digest in fingerprints.items()):
        raise BodyIncompleteForBare("authored body geometry changed during preparation")
    if completion and completion["applied"]:
        # BR2. How the patch meets her, measured on the finished body (her skin restored, her
        # garments off): the numbers a reviewer of a reconstructed file reads. A measurement that
        # cannot run says so; it never stops the look (it changes nothing in the file).
        try:
            completion["join"] = measure_join(doc, context.measurements, context.info)
        except Exception as exc:  # noqa: BLE001
            logger.warning("bare: join measurement failed: %s", exc)
            completion["join"] = {"error": f"{type(exc).__name__}: {exc}"[:200]}
    # SR2. Say which it was: restored, nothing to restore, or not verified — measured after.
    census = skin_census(doc, context.measurements, include_feet=True, protected_materials=protected)
    skin_verdict = restoration_verdict(restored, census)
    integrity = check_body(doc, context.measurements,
                           {"upper", "lower", "leftThigh", "rightThigh", "leftShin", "rightShin"},
                           bare=True)
    context.fit_report.base_body = {
        "mode": "bare-dressed" if dressed else "bare", "complete": integrity.complete,
        "bodyPreparation": "passed" if integrity.complete else "refused", "layerOrder": "passed",
        "removedSlots": sorted({g.slot for g in inventory}),
        "integrity": integrity.to_dict(), "skinRestored": restored.to_dict() if restored else None,
        "skinRestoration": skin_verdict, "skinCensusAfter": census,
        "authoredAccessorsUnchanged": len(fingerprints), "normalMapsPreserved": True,
        "protectedAnatomicalMaterials": sorted(protected),
        "keptAnatomicalMaterials": kept_anatomy,
        "eligibility": eligibility.to_dict(),
        "bodyCompletion": completion,
    }
    if not integrity.complete:
        raise BodyIncompleteForBare("authored body is not closed in every required band",
                                    detail={"integrity": integrity.to_dict()})
    # AF5. A garment still drawn: a tagged node that still holds a mesh, or a tagged mesh a node
    # still draws. remove_garments detaches a whole-mesh garment from its node (no renumbering),
    # so the node keeps its tag with nothing on it - counting the tag alone refused every look
    # Forge itself had dressed, as "detected clothing remains" (ref-f-median, tee and jeans).
    drawn = {n["mesh"] for n in doc.nodes if "mesh" in n}
    garment = lambda item: ((item.get("extras") or {}).get("wardrobeForge") or {}).get("kind") == "garment"  # noqa: E731
    tagged = any(garment(n) and "mesh" in n for n in doc.nodes) or any(
        garment(m) and i in drawn for i, m in enumerate(doc.meshes))
    remaining = [g for g in garment_inventory(doc) if not is_anatomy(g)]
    if remaining or tagged:
        raise BodyIncompleteForBare("detected clothing remains")
    # ES1. Dressed over bare: her body is bare under the outfit, but the look is not a bare look —
    # a client that takes "bare" for "nothing on" must not take this for one.
    tag = {"overBare": True} if dressed else {"bare": True, "templateId": "body-bare-v1"}
    if preset:
        # BD1. Last, after every check above saw her exactly as before: the census, the bands and
        # the clothing check would read painted anatomy as painted clothing.
        from wardrobe.vrm.inspect import VrmSpec

        forward = -1.0 if context.info.spec is VrmSpec.VRM0 else 1.0
        state = getattr(request.options, "bare_state", None)
        extras = tuple(getattr(request.options, "bare_extras", None) or ())
        painted = body_detail.paint_detail(doc, context.measurements, preset=preset, forward=forward,
                                           state=state, extras=extras)
        if painted is None:
            raise BodyIncompleteForBare("body detail could not be placed: no textured skin, or her "
                                        "chest and pelvis landmarks were not found",
                                        detail={"bodyDetail": preset})
        context.fit_report.base_body["bodyDetail"] = {**painted.to_dict(), "clearance": detail_cleared}
        tag.update(detail=preset)
        if state:
            tag.update(state=state)
        if extras:
            tag.update(extras=list(extras))
    if completion and completion["applied"]:
        # BR1. Said in the file itself: this body is not entirely hers. The patch is BC1's,
        # tagged bodyProxy on its own mesh, so a viewer or a reviewer can tell it apart.
        tag.update(reconstructed=True, reconstruction="bc1-proxy",
                   reconstructedRegions=completion["regions"])
    doc.gltf.setdefault("extras", {}).setdefault("wardrobeForge", {}).update(**tag)


BARE_REGIONS = {"upper", "lower", "leftThigh", "rightThigh", "leftShin", "rightShin"}


def body_detail_evidence() -> int:
    from wardrobe.body_surface.eligibility import DETAIL_EVIDENCE_CHARS

    return DETAIL_EVIDENCE_CHARS


def _complete_if_asked(context, doc, inventory, removed) -> dict | None:
    """BR1. Opt-in only: fill the bands her export deleted, before her garments come off.

    Authored-only stays the default and is untouched: without ``bodyCompletion: proxy`` this does
    nothing and an incomplete body is refused below, as before. With it, the operator's own switch
    must be on (a request cannot turn reconstruction on), and only the missing bands are filled,
    from the garments that covered them (BC1: a smoothed surface between her own skin edges,
    featureless by construction). Her authored accessors are fingerprinted afterwards exactly as
    for an authored-only body: the patch is a new mesh, never an edit of hers.
    """
    if context.record.request.options.body_completion != "proxy":
        return None
    if not getattr(context.settings, "wardrobe_bare_body_completion", False):
        raise BodySurfaceNotPermitted("bare body reconstruction is not enabled on this server "
                                      "(WARDROBE_BARE_BODY_COMPLETION)",
                                      detail={"refusedBy": "operator-completion-switch"})
    before = check_body(doc, context.measurements, BARE_REGIONS, without=removed, bare=True)
    missing = {region for region, check in before.regions.items() if not check.present}
    report = {"asked": True, "regions": sorted(missing), "before": before.to_dict(), "patch": None}
    if missing:
        report["patch"] = body_completion.complete_body(doc, context.measurements,
                                                        [g for g in inventory if g.regions & missing],
                                                        removed)
    report["applied"] = bool(missing) and report["patch"] is not None
    return report
