"""PB1. A look already made is not made again (docs/PREBUILT_WARDROBE.md).

In a conversation the person asked for lingerie and waited about three minutes, while the
same Forge job takes 6-10 s locally: the wait is the Space's queue and the download, not
the pipeline. So a request that was answered once is answered again from storage: the
completed job record is kept under a key of everything that shapes the look's bytes, and an
identical request returns a completed record pointing at the same look, on its first poll.

Only a request for one named template is cached: no tattoos, no layers. That is what Try-On,
the catalog and the prebuild ask for. The prompt is part of the key even with a template:
without an explicit colour the planner reads the colour (and finish, sheerness) from the words,
and falls back to grey — "red tee" and "tee" are different looks. A free prompt with no template
is never cached. The colour's hex is in the key too, so retuning a colour is a miss.

Each wardrobe also gets a list of its *fresh* prebuilt looks — made on her own body, not on top
of another look — at ``prebuilt/wardrobes/<wardrobe>.json``. That list is what the app reads to
know what she already has ready (``GET /v1/library/{slug}/prebuilt``), so she can put lingerie
on at once instead of saying she has none.

The key holds:

* the whole request except the prompt — avatar (URL, storage key, pinned hash, licence,
  declaration), colour, every option including ``private`` and ``wardrobeId``;
* the template's own content (a hash of its JSON), so editing a template is a miss;
* ``PIPELINE_VERSION``, bumped by hand in the same commit as any change that alters what the
  pipeline outputs. Hashing the code instead would rebuild every look for a comment.

``private`` and ``wardrobeId`` being in the key matters: a public request can never be
answered with a private look, and a hit is always a look already listed in the requester's
own wardrobe, so nothing has to be copied between wardrobes.

The policy is not here. Routes decide whether a request may run before it is submitted, so a
request refused today is refused even when an identical look exists from a time it was not.

Entries live in the object store (``prebuilt/<key>.json``), the same place as the looks, so
they outlive a restart and move with the bucket. A broken or missing entry is a miss, never
an error: the job simply runs.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
from datetime import UTC, datetime
from urllib.parse import urlsplit
from uuid import uuid4

from wardrobe.domain.garments import TemplateCatalog
from wardrobe.domain.jobs import CreateJobRequest, JobEvent, JobRecord, JobState
from wardrobe.pipeline.plan_outfit import COLORS
from wardrobe.storage.object_store import ObjectStore

logger = logging.getLogger(__name__)

#: Bump in the same commit as any change that alters a look's bytes for the same request
#: (fitting, assembly, materials, the base body). Every cached look is then a miss.
PIPELINE_VERSION = 1

PREFIX = "prebuilt"

#: AA. Template fields added after the dataset's keys were written, with the value every
#: template had before they existed. The key hashes the template's JSON, so a new field
#: (even one left at its default) would change the key of EVERY existing look: ~1900 looks
#: already in the dataset would stop being found, and a prebuild would make them all again.
#: A field here is left out of the hash while it holds this value, so an existing template
#: hashes byte-for-byte as before and a new card that sets it still hashes it. Add to this
#: list in the same commit as any new GarmentTemplate or FitPolicy field;
#: tests/unit/test_cache_key_stability.py fails until you do.
ADDED_TEMPLATE_FIELDS: dict[str, object] = {"replaces_clothing": False}
ADDED_FIT_FIELDS: dict[str, object] = {"slit": "", "finish": "", "pattern": "", "opacity": None}


def template_fingerprint(template) -> str:
    """sha256 of the template as the cache key sees it (see ADDED_TEMPLATE_FIELDS)."""
    exclude: dict = {
        name: True
        for name, default in ADDED_TEMPLATE_FIELDS.items()
        if getattr(template, name, default) == default
    }
    fit = {
        name: True
        for name, default in ADDED_FIT_FIELDS.items()
        if getattr(template.fit, name, default) == default
    }
    if fit:
        exclude["fit"] = fit
    dumped = template.model_dump_json(by_alias=True, exclude=exclude)
    return hashlib.sha256(dumped.encode("utf-8")).hexdigest()


def cache_key(request: CreateJobRequest, catalog: TemplateCatalog) -> str | None:
    """The key a request's look is stored under, or None when it is not cacheable."""
    outfit = request.outfit
    if outfit is None or request.body_art or request.body_art_remove:
        return None
    if not outfit.template_id or outfit.layers:
        return None
    template = catalog.get(outfit.template_id)
    if template is None:
        return None
    payload = request.model_dump(mode="json", by_alias=True, exclude_none=True)
    material = {
        "pipelineVersion": PIPELINE_VERSION,
        "template": template_fingerprint(template),
        "request": payload,
    }
    named = (outfit.color, request.options.foundation_color)
    hexes = {name: COLORS.get(name.lower()) for name in named if name}
    if hexes:
        material["colorHex"] = hexes
    canonical = json.dumps(material, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


#: RU1. Plan fields that come from the words rather than the garments: the display name, the
#: planner's own notes and how sure it was. Two prompts that plan to the same garments, in
#: the same colours and materials, make the same look; these never change its fitting.
PLAN_WORDS = {"name", "keywords", "notes", "confidence"}
#: Request fields the plan already holds (the planner reads them), left out so that a
#: template request and the same garment described in words meet under one key.
OUTFIT_PLANNED = {"prompt", "mode", "templateId", "color"}


def _plan_material(plan) -> dict:
    exclude: dict = dict.fromkeys(PLAN_WORDS, True)
    if plan.layers:
        exclude["layers"] = {"__all__": dict.fromkeys(PLAN_WORDS, True)}
    return plan.model_dump(mode="json", by_alias=True, exclude=exclude)


def plan_key(request: CreateJobRequest, catalog: TemplateCatalog) -> str | None:
    """RU1. The key of what the planner builds for this request, or None when it is not cacheable.

    ``cache_key`` keys a request by its words, so it covers one named template only, and a
    rephrasing ("black lace bralette" / "a black bralette in lace") or a dictionary outfit of
    two garments ("black fitted crop top + blue straight jeans") was built again every time:
    measured 84 s, then 55 s for the identical request, as a second look. This keys the
    *plan* instead — every garment's template, shape, colour, material, hosiery and set,
    plus each template's own content and the rest of the request (avatar, options, presets,
    reveal …) — so whatever plans to the same garments is the same look.

    Planning is the pipeline's own rule-based planner (``plan_outfit_stack``): deterministic and
    milliseconds. Body art and explicit layers stay uncached, as with ``cache_key``. A plan with
    a garment the catalogue does not hold, or a piece of the prompt it could not plan, has no
    key: that look is not the one asked for, and must not be handed to the next person.
    """
    from wardrobe.pipeline.plan_outfit_stack import plan_outfit_stack

    outfit = request.outfit
    if outfit is None or request.body_art or request.body_art_remove or outfit.layers:
        return None
    plan = plan_outfit_stack(outfit, catalog)
    if plan.unplanned:
        return None
    templates = {}
    for garment in plan.garments:
        template = catalog.get(garment.template_id) if garment.template_id else None
        if template is None:
            return None
        templates[garment.template_id] = template_fingerprint(template)
    payload = request.model_dump(mode="json", by_alias=True, exclude_none=True)
    payload["outfit"] = {k: v for k, v in payload["outfit"].items() if k not in OUTFIT_PLANNED}
    material = {
        "key": "plan-1",
        "pipelineVersion": PIPELINE_VERSION,
        "plan": _plan_material(plan),
        "templates": templates,
        "request": payload,
    }
    named = [request.options.foundation_color] if request.options.foundation_color else []
    hexes = {name: COLORS.get(name.lower()) for name in named}
    if hexes:
        material["colorHex"] = hexes
    canonical = json.dumps(material, sort_keys=True, separators=(",", ":"))
    return "plan-" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def keys_for(request: CreateJobRequest, catalog: TemplateCatalog) -> list[str]:
    """RU1. Every key a request's look is stored under: the original (words) key first, so each
    entry already in the dataset still answers, then the plan key."""
    keys: list[str] = []
    for make in (cache_key, plan_key):
        try:
            key = make(request, catalog)
        except Exception as exc:  # a key that cannot be made is a miss, never a refused job
            logger.warning("prebuilt %s unavailable: %s", make.__name__, exc)
            key = None
        if key and key not in keys:
            keys.append(key)
    return keys


def entry_key(key: str) -> str:
    return f"{PREFIX}/{key}.json"


def wardrobe_key(wardrobe_id: str) -> str:
    return f"{PREFIX}/wardrobes/{wardrobe_id}.json"


def is_fresh(request: CreateJobRequest) -> bool:
    """Made on her own body, not on top of a look (a library job with baseLookId sources a look)."""
    source = request.avatar.storage_key or ""
    return not source.startswith("looks/")


#: What makes two listed looks the same look (PB7 merges by it too). ``plan`` is None for every
#: one-template look, so entries written before RU1 compare exactly as they did.
LIST_FIELDS = ("templateId", "color", "foundationColor", "private", "plan")


def dictionary_id(request: CreateJobRequest) -> str | None:
    """RU1. The outfit dictionary entry this request is, when it is exactly one's request."""
    try:
        from wardrobe.pipeline.outfit_dictionary import OUTFITS
    except Exception:  # pragma: no cover - the dictionary is optional to the cache
        return None
    sent = request.outfit.model_dump(by_alias=True, exclude_none=True, exclude_defaults=True)
    for outfit in OUTFITS:
        if outfit.request().model_dump(by_alias=True, exclude_none=True, exclude_defaults=True) == sent:
            return outfit.id
    return None


#: One writer per process for the wardrobe lists: read-modify-write of a small JSON file.
#: The prebuild runs one Forge process, so this is enough; two processes could lose an entry,
#: which is a later miss, never a wrong look.
_LIST_LOCK = asyncio.Lock()


async def ready_looks(store: ObjectStore, wardrobe_id: str, *, include_private: bool) -> list[dict]:
    """The fresh prebuilt looks listed for a wardrobe; private ones only when asked for."""
    try:
        if not await store.exists(wardrobe_key(wardrobe_id)):
            return []
        listed = json.loads(await store.get(wardrobe_key(wardrobe_id)))
    except Exception as exc:
        logger.warning("prebuilt list for %s unreadable: %s", wardrobe_id, exc)
        return []
    looks = [item.copy() for item in listed.get("looks", []) if isinstance(item, dict)]
    visible = [item for item in looks if include_private or not item.get("private")]
    # Index entries can outlive a preview that CI never uploaded. Avoid advertising
    # known-missing generated previews, without altering legitimate external URLs.
    for item in visible:
        preview = item.get("previewUrl")
        look_id = item.get("lookId")
        if not isinstance(preview, str) or not isinstance(look_id, str):
            continue
        expected = f"looks/{look_id}/preview.webp"
        if urlsplit(preview).path.endswith(f"/v1/assets/{expected}"):
            try:
                present = await store.exists(expected)
            except Exception as exc:
                logger.warning("could not check preview for %s: %s", look_id, exc)
                continue
            if not present:
                item["previewUrl"] = None
    return visible


async def with_prebuilt(store: ObjectStore, wardrobe_id: str, manifest, *, include_private: bool):
    """Her wardrobe with every prebuilt look in it, whether or not this process made them.

    A Space keeps its wardrobe manifests in memory or on local disk; the prebuilt looks were
    made by CI and live in the dataset. Merged here, the app's existing read of her wardrobe
    (``GET /v1/wardrobes/{slug}``) lists all of them after any restart, with no app change.
    Returns None when there is neither a manifest nor a prebuilt look.
    """
    from wardrobe.domain.manifests import WardrobeLook, WardrobeManifest

    looks = await ready_looks(store, wardrobe_id, include_private=include_private)
    if manifest is None and not looks:
        return None
    merged = manifest.model_copy(deep=True) if manifest is not None else WardrobeManifest.empty(wardrobe_id)
    # Legacy local manifests may still advertise preview paths that were never
    # uploaded to HF. Correct those alongside fresh prebuilt index entries.
    for look in merged.looks:
        preview = look.preview_url
        if preview and urlsplit(preview).path.endswith(f"/v1/assets/looks/{look.id}/preview.webp"):
            try:
                present = await store.exists(f"looks/{look.id}/preview.webp")
            except Exception as exc:
                logger.warning("could not check preview for %s: %s", look.id, exc)
                continue
            if not present:
                look.preview_url = None
    have = {look.id for look in merged.looks}
    for item in looks:
        if item.get("lookId") in have or not item.get("vrmUrl"):
            continue
        merged.looks.append(
            WardrobeLook(
                id=item["lookId"],
                name=item.get("name") or item.get("templateId") or "Look",
                vrmUrl=item["vrmUrl"],
                previewUrl=item.get("previewUrl"),
                prompt=item.get("prompt"),
                fitPassed=item.get("fitPassed"),
                fitVerdict=item.get("fitVerdict"),
                private=bool(item.get("private")),
            )
        )
    return merged


async def _list_look(store: ObjectStore, record: JobRecord, key: str) -> None:
    request = record.request
    wardrobe_id = request.options.wardrobe_id or request.avatar.avatar_id
    if not wardrobe_id or not is_fresh(request) or record.look is None or request.outfit is None:
        return
    item = {
        "key": key,
        "templateId": request.outfit.template_id,
        "color": request.outfit.color,
        "foundationColor": request.options.foundation_color,
        "lookId": record.look.id,
        "name": record.look.name,
        "vrmUrl": record.look.vrm_url,
        "previewUrl": record.look.preview_url,
        "private": bool(request.options.private),
        "prompt": record.look.prompt,
        "fitPassed": record.fit_report.passed if record.fit_report else None,
        "fitVerdict": record.fit_report.verdict if record.fit_report else None,
        "builtAt": datetime.now(UTC).isoformat(),
    }
    if key.startswith("plan-") and not request.outfit.template_id:
        # RU1. An outfit of several garments has no one template: its plan key tells it apart
        # from every other such outfit (all of them share templateId None and color None).
        item["plan"] = key
        item["garments"] = [g.template_id for g in record.plan.garments] if record.plan else []
        outfit_id = dictionary_id(request)
        if outfit_id:
            item["outfitId"] = outfit_id
    async with _LIST_LOCK:
        listed: dict = {"wardrobeId": wardrobe_id, "looks": []}
        try:
            if await store.exists(wardrobe_key(wardrobe_id)):
                listed = json.loads(await store.get(wardrobe_key(wardrobe_id)))
        except Exception:
            listed = {"wardrobeId": wardrobe_id, "looks": []}
        same = tuple(item.get(f) for f in LIST_FIELDS)
        fields = LIST_FIELDS
        kept = [old for old in listed.get("looks", []) if tuple(old.get(f) for f in fields) != same]
        listed["looks"] = kept
        listed["looks"].append(item)
        listed["pipelineVersion"] = PIPELINE_VERSION
        await store.put(wardrobe_key(wardrobe_id), json.dumps(listed).encode("utf-8"),
                        content_type="application/json")


async def lookup(store: ObjectStore, key: str) -> JobRecord | None:
    """The completed record stored for this key, or None (absent, unreadable, or its look gone)."""
    try:
        if not await store.exists(entry_key(key)):
            return None
        entry = json.loads(await store.get(entry_key(key)))
        record = JobRecord.model_validate(entry["record"])
    except Exception as exc:  # a bad entry is a miss: the job runs and writes a good one
        logger.warning("prebuilt entry %s unreadable, treated as a miss: %s", key[:12], exc)
        return None
    if record.state != JobState.COMPLETED or record.look is None:
        return None
    look_key = f"looks/{record.look.id}/look.vrm"
    try:
        if not await store.exists(look_key):
            return None
    except Exception:
        return None
    return record


async def remember(store: ObjectStore, key: str, record: JobRecord, *, list_it: bool = True) -> None:
    """Keep a completed record under its key. Never raises: a cache that fails is a slower Forge."""
    if record.state != JobState.COMPLETED or record.look is None:
        return
    entry = {
        "key": key,
        "pipelineVersion": PIPELINE_VERSION,
        "builtAt": datetime.now(UTC).isoformat(),
        "jobId": record.id,
        "lookId": record.look.id,
        "templateId": record.request.outfit.template_id if record.request.outfit else None,
        "record": record.model_dump(mode="json", by_alias=True),
    }
    try:
        await store.put(entry_key(key), json.dumps(entry).encode("utf-8"), content_type="application/json")
        if list_it:
            await _list_look(store, record, key)
    except Exception as exc:
        logger.warning("could not remember prebuilt look %s: %s", key[:12], exc)


def answered(request: CreateJobRequest, cached: JobRecord) -> JobRecord:
    """A new completed record for this request, answered with the cached look.

    A new id, so two people never share a job; the cached look, plan and fit report, so the
    answer is exactly what the earlier job made. ``cache: prebuilt`` on the event says why it
    was instant.
    """
    now = datetime.now(UTC)
    record = JobRecord(
        id=f"job_{uuid4().hex}",
        state=JobState.COMPLETED,
        createdAt=now,
        updatedAt=now,
        request=request,
        analysis=cached.analysis,
        plan=cached.plan,
        look=cached.look,
        fitReport=cached.fit_report,
    )
    record.events.append(JobEvent(state=JobState.QUEUED, at=now, message="job accepted", progress=0.0))
    record.events.append(
        JobEvent(
            state=JobState.COMPLETED,
            at=now,
            message="look ready (prebuilt)",
            progress=1.0,
            detail={"cache": "prebuilt", "lookId": cached.look.id if cached.look else None},
        )
    )
    return record


__all__ = ["PIPELINE_VERSION", "LIST_FIELDS", "cache_key", "plan_key", "keys_for", "dictionary_id", "lookup",
           "remember", "answered", "entry_key", "wardrobe_key", "is_fresh", "ready_looks", "with_prebuilt"]
