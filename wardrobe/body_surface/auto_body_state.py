"""CG6. Bare body-state files, built and imported by Forge itself: no command, no upload.

CG5 made the file without an artist (``tools/body_surface/build_body_state.py``), but someone
still had to run the tool, keep the output somewhere private and upload each file through the
Studio's import. Four characters, four uploads, and the step was easy to forget after a review.
Here Forge does the same thing on its own, at the two moments it can matter:

* at startup, for every library character (a restart after a review picks it up), and
* right after a ``clearly-adult`` finding is recorded in the Studio (``routes/reviews.py``).

For each character whose clothing is painted on or whose body has a missing band (CV1's
structure, ``character_gates.measure_body_state``) and who has no bare import yet for her pinned
bytes, it builds the file exactly as the tool does (``build_bare``: BR1's patch where a band is
missing, every garment off, painted skin restored) and puts it through the **same**
``body_state_import.check`` as an upload. Nothing is registered unless that check accepts it, so
every rule an upload meets still holds here, the review above all: before a person has recorded
``clearly-adult`` for her file the check refuses and nothing happens; a file that adds surface
(O's chest patch) still needs its own review of the built bytes, and until then it is refused too.
The refusal is logged and retried at the next trigger. Characters whose garments are real meshes
(A, B, C, Model Girl) need no file: Forge's bare look takes those off.

The import record says what made it (``importedBy: forge-auto (CG6)``) and the provenance names
the library's own licence record and source for her pinned file: Forge derived it from that file
under those terms, which is what the operator otherwise typed into the import form.

``WARDROBE_AUTO_BODY_STATES=false`` turns it off. It never raises into its caller.
"""

from __future__ import annotations

import asyncio
import logging
from types import SimpleNamespace

logger = logging.getLogger(__name__)

AUTHOR = "forge-auto (CG6)"
NEEDS_FILE = {"painted-on", "body-missing"}


def build_bare(document) -> dict:
    """Complete (only where a band is missing), take every garment off, restore painted skin.

    The order is ``bare_body.prepare``'s: the BC1 patch is shaped from the garments that covered
    the hole, so it is made before they are removed. Completion is asked for here because this is
    the operator's own build, on purpose; it is a no-op on a closed body (``applied`` false)."""
    from wardrobe.pipeline.bare_body import _complete_if_asked
    from wardrobe.vrm.garment_inventory import build_strip_plan, garment_inventory, remove_garments
    from wardrobe.vrm.inspect import inspect_document
    from wardrobe.vrm.measure import measure_body
    from wardrobe.vrm.skin_restore import restore_skin

    info = inspect_document(document)
    measurements = measure_body(document, info)
    inventory = garment_inventory(document)
    removed = {(g.mesh, g.primitive) for g in inventory}
    context = SimpleNamespace(
        measurements=measurements, settings=SimpleNamespace(wardrobe_bare_body_completion=True),
        record=SimpleNamespace(request=SimpleNamespace(options=SimpleNamespace(body_completion="proxy"))))
    completion = _complete_if_asked(context, document, inventory, removed)
    remove_garments(document, list(build_strip_plan(inventory, [], replace_all=True).remove))
    restore_skin(document, measurements, set(), preserve_normals=True, include_feet=True)
    tag = {"bare": True, "templateId": "body-bare-v1"}
    if completion and completion["applied"]:
        tag.update(reconstructed=True, reconstruction="bc1-proxy", reconstructedRegions=completion["regions"])
    document.gltf.setdefault("extras", {}).setdefault("wardrobeForge", {}).update(**tag)
    return {"garmentsRemoved": len(removed),
            "reconstructedRegions": completion["regions"] if completion and completion["applied"] else []}


def build_file(source: bytes) -> bytes:
    """The bare body-state bytes for one library file. Deterministic for a given source."""
    from wardrobe.vrm.document import GltfDocument

    document = GltfDocument.from_bytes(source)
    build_bare(document)
    return document.to_bytes()


def _prepare(avatar, settings) -> dict:
    """CPU part, on a worker thread: measure, build, check. Registers nothing."""
    from wardrobe.body_surface import body_state_import
    from wardrobe.body_surface.character_gates import _body_state, measure_body_state

    # The gate's own reading of her body (CG4), so this and the audit never disagree.
    kind = _body_state(measure_body_state(avatar.path))["state"]
    if kind not in NEEDS_FILE:
        return {"status": "not-needed", "body": kind}
    original = avatar.path.read_bytes()
    data = build_file(original)
    verdict = body_state_import.check(
        data, original, state="bare", source_sha256=avatar.sha256, declared_sha256=None,
        operator_enabled=settings.wardrobe_adult_body_surface, depicts_adult=bool(avatar.depicts_adult),
        review_root=settings.body_surface_root_path, reference_root=settings.wardrobe_calibration_root)
    return {"status": "built", "body": kind, "data": data, "verdict": verdict}


async def _already_imported(store, avatar) -> bool:
    from wardrobe.pipeline import prebuilt

    try:
        listed = await prebuilt.read_list(store, avatar.slug)
    except Exception:  # noqa: BLE001 - unreadable list: treat as none, the check decides again
        return False
    return any(item.get("origin") == "operator-import"
               and (item.get("wardrobeState") or item.get("state")) == "bare"
               and item.get("sourceSha256") == avatar.sha256
               for item in listed.get("looks", []))


async def ensure(avatar, settings, store) -> dict:
    """Make and import her bare body-state file if she needs one and the import check accepts it."""
    from wardrobe.pipeline import prebuilt

    slug = getattr(avatar, "slug", "?")
    try:
        if not getattr(settings, "wardrobe_auto_body_states", True):
            return {"slug": slug, "status": "off"}
        if avatar is None or not avatar.available:
            return {"slug": slug, "status": "unavailable"}
        if await _already_imported(store, avatar):
            return {"slug": slug, "status": "already-imported"}
        prepared = await asyncio.to_thread(_prepare, avatar, settings)
        if prepared["status"] != "built":
            return {"slug": slug, **prepared}
        verdict = prepared["verdict"]
        if not verdict.accepted:
            logger.info("auto body state for %s waits: %s", slug, verdict.message)
            return {"slug": slug, "status": "waiting", "reason": verdict.reason, "message": verdict.message}
        look_id = prebuilt.import_look_id(verdict.sha256)
        item = await prebuilt.register_import(
            store, slug, prepared["data"], verdict=verdict.to_dict(), state="bare",
            name=f"{avatar.name} (bare)", source_sha256=avatar.sha256, output_sha256=verdict.sha256,
            imported_by=AUTHOR,
            provenance={"licence": f"{avatar.license}; derived by Forge from the pinned library file "
                                   f"{avatar.sha256} (source {avatar.source})",
                        "rightsAttested": True, "derivedBy": "CG6 build_bare",
                        "uploadedBytes": len(prepared["data"])},
            vrm_url=settings.artifact_url(f"looks/{look_id}/look.vrm"),
            garments=verdict.checks.get("garments", {}).get("fromFile") or [])
        logger.info("auto body state %s imported for %s", look_id, slug)
        return {"slug": slug, "status": "imported", "lookId": item.get("lookId"), "sha256": verdict.sha256}
    except Exception as exc:  # noqa: BLE001 - fail soft: a character without a file, said in the log
        logger.warning("auto body state for %s failed: %s", slug, exc)
        return {"slug": slug, "status": "failed", "message": str(exc)}


async def ensure_all(library, settings, store) -> list[dict]:
    """Every available library character, one after another (each build is CPU-bound)."""
    results = []
    for avatar in library.available():
        results.append(await ensure(avatar, settings, store))
    done = [r["slug"] for r in results if r["status"] == "imported"]
    if done:
        logger.info("auto body states imported: %s", ", ".join(done))
    return results


__all__ = ["AUTHOR", "build_bare", "build_file", "ensure", "ensure_all"]
