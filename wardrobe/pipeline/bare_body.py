"""Private authored-body preparation. Never generates or completes geometry."""
import hashlib
import re

from wardrobe.body_surface.contract import Capability
from wardrobe.body_surface.gate import evaluate
from wardrobe.errors import BodyIncompleteForBare, BodySurfaceNotPermitted
from wardrobe.vrm.body_integrity import check_body
from wardrobe.vrm.garment_inventory import build_strip_plan, garment_inventory, remove_garments
from wardrobe.vrm.skin_restore import restore_skin


async def prepare(context):
    request = context.record.request
    decision = evaluate(Capability.ADULT_BODY_SURFACE, context.info.license,
                        operator_enabled=context.settings.wardrobe_adult_body_surface,
                        depicts_adult=bool(request.avatar.depicts_adult))
    if not decision.allowed:
        raise BodySurfaceNotPermitted(decision.message, detail={"refusedBy": decision.refused_by})
    if not request.options.private:
        raise BodySurfaceNotPermitted("bare output must be private")
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
    integrity = check_body(doc, context.measurements,
                           {"upper", "lower", "leftThigh", "rightThigh", "leftShin", "rightShin"},
                           bare=True)
    context.fit_report.base_body = {
        "mode": "bare", "complete": integrity.complete,
        "bodyPreparation": "passed" if integrity.complete else "refused", "layerOrder": "passed",
        "removedSlots": sorted({g.slot for g in inventory}),
        "integrity": integrity.to_dict(), "skinRestored": restored.to_dict() if restored else None,
        "authoredAccessorsUnchanged": len(fingerprints), "normalMapsPreserved": True,
        "protectedAnatomicalMaterials": sorted(protected),
        "keptAnatomicalMaterials": kept_anatomy,
    }
    if not integrity.complete:
        raise BodyIncompleteForBare("authored body is not closed in every required band",
                                    detail={"integrity": integrity.to_dict()})
    tagged = any(((n.get("extras") or {}).get("wardrobeForge") or {}).get("kind") == "garment"
                 for n in [*doc.nodes, *doc.meshes])
    remaining = [g for g in garment_inventory(doc) if not is_anatomy(g)]
    if remaining or tagged:
        raise BodyIncompleteForBare("detected clothing remains")
    doc.gltf.setdefault("extras", {}).setdefault("wardrobeForge", {}).update(
        bare=True, templateId="body-bare-v1")
