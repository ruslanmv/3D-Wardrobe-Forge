"""Build genuine WebP clothing thumbnails with Forge and the Studio VRM viewer.

Each garment is fitted onto a reference base (the neutral foundation, her own clothes off),
in its own colour, and framed by category; preview-style.json says how.

Usage (after make library and browser dependencies):
    python tools/catalog/render_templates.py --avatar avatar-sample-a
    python tools/catalog/render_templates.py --avatar avatar-sample-a --ids top-crop-tee-v1 jeans-straight-v1
    python tools/catalog/render_templates.py --profile underwear --avatar fem-vroid

The default build is the public catalog and skips every restricted template. The
underwear profile is the adult catalog: only that category, written to
assets/catalog/adult/ (previews, build report), never into the public folder.

Previews are REAL generated looks fitted to a fixed sample avatar, NOT
isolated GLBs or promised universal garment assets. The catalog API only
advertises images that this script successfully created and that have been
included in the deployment. Adult-gated garments are rendered only for a category
preview-style.json gives a profile (underwear), on that profile's avatar, which the
operator must have declared adult in assets/library/policy.json; Forge refuses it on
any other. A garment that is adult-gated by itself (requiresAdult) is never rendered.

Requirements: Python Forge dependencies, Pillow; Node Playwright + Chromium
and the gallery's three.js CDN access. Does not run during API startup.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import re
import subprocess
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from wardrobe.config import Settings  # noqa: E402
from wardrobe.domain.garments import INTIMATE_CATEGORIES, TemplateCatalog  # noqa: E402
from wardrobe.domain.jobs import CreateJobRequest  # noqa: E402
from wardrobe.library import AvatarLibrary  # noqa: E402
from wardrobe.pipeline.orchestrator import Orchestrator  # noqa: E402
from wardrobe.pipeline.plan_outfit_stack import SET_PARTS  # noqa: E402
from wardrobe.queue.jobs import AsyncioJobQueue  # noqa: E402
from wardrobe.storage.database import InMemoryJobRepository, InMemoryWardrobeRepository  # noqa: E402
from wardrobe.storage.object_store import LocalObjectStore  # noqa: E402
from wardrobe.targets.pack import rating_for  # noqa: E402


def eligible(template, profile: str | None = None) -> bool:
    """The public build takes no restricted template; a profile build takes its own category only."""
    if template.requires_adult:
        return False
    if profile is None:
        return template.category not in INTIMATE_CATEGORIES
    return template.category == profile


def _profiles(style: dict) -> dict:
    return {k: v for k, v in style.get("profiles", {}).items() if isinstance(v, dict)}


def profile_for(template, style: dict, default_avatar: str, active: str | None = None) -> dict:
    """How this template is previewed: avatar, base, mode, framing, colours and accepted ratings.

    The default profile is the public one (her reference base, rating general). A category
    with a profile of its own overrides each of those fields it names.
    """
    own = _profiles(style).get(template.category, {}) if active == template.category else {}
    framing = own.get("framing")
    if framing is None:
        frame = style["framing"].get(template.category, [0.0, 1.0])
    else:
        matches = (f for pattern, f in framing.get("match", {}).items() if re.search(pattern, template.id))
        frame = next(matches, framing["default"])
    finish = own.get("finish")
    layer = own.get("layer", {})
    mode = layer["baseBody"] if layer and re.search(layer["match"], template.id) else own.get(
        "baseBody", "replace-outer")
    return {
        "name": template.category if own else "default",
        "avatar": own.get("avatar", default_avatar),
        "base": {"prompt": style["base"]["prompt"], "baseBody": "replace-outer", **own.get("base", {})},
        "baseBody": mode,
        "frame": frame,
        "colors": own.get("colors", style["colors"]),
        "ratings": own.get("ratings", ["general"]),
        "fabric": next((r["fabric"] for r in own.get("styling", {}).get("rules", [])
                        if re.search(r["match"], template.id)), None),
        "finish": finish if finish and re.search(finish["match"], template.id) else None,
        "presentation": own.get("presentation"),
    }


#: How previews look: base outfit, canvas, framing by category, colour rules (bump its
#: styleVersion to re-render everything). Read by this script only.
STYLE_PATH = ROOT / "tools" / "catalog" / "preview-style.json"


def load_style() -> dict:
    return json.loads(STYLE_PATH.read_text(encoding="utf-8"))


def color_for(template, catalog, colors: dict) -> str:
    """The colour a template is previewed in: a matching rule, else the category palette in
    order of template id. Fixed for every build, so a preview never changes colour by itself."""
    for rule in colors["rules"]:
        if re.search(rule["match"], template.id):
            return rule["color"]
    palette = colors["palette"]
    siblings = sorted(t.id for t in catalog if t.category == template.category)
    return palette[siblings.index(template.id) % len(palette)]


def cache_key(template, profile: dict, color: str, style: dict) -> dict:
    """What a preview was made from. Any field that differs from the last build re-renders it.

    A profile's build also records its base set and layering mode: the same bra fitted over
    a different base, or a guêpière switched from layering to replacing, is a different
    picture. The public build keeps the fields it always had, so its cache stays valid.
    """
    key = {"color": color, "framing": profile["frame"], "styleVersion": style["styleVersion"],
           "templateSha256": template_digest(template.id), "sampleAvatar": profile["avatar"]}
    if profile["name"] != "default":
        key.update(profile=profile["name"], baseBody=profile["baseBody"],
                   basePrompt=profile["base"]["prompt"])
        if profile.get("fabric"):
            key["fabric"] = profile["fabric"]
        if profile.get("finish"):
            key["styledWith"] = profile["finish"]["template"]
        if profile.get("presentation"):
            key["presentation"] = hashlib.sha256(
                json.dumps(profile["presentation"], sort_keys=True).encode()).hexdigest()[:12]
    return key


def template_digest(template_id: str) -> str:
    """SHA-256 of the template's own file: a changed template is re-rendered."""
    matches = sorted((ROOT / "assets" / "garment_templates").glob(f"*/{template_id}.json"))
    return hashlib.sha256(matches[0].read_bytes()).hexdigest() if matches else ""


def _previous(destination: Path) -> dict:
    report = destination.parent / "build-report.json"
    try:
        records = json.loads(report.read_text(encoding="utf-8")).get("records", [])
    except (OSError, ValueError):
        return {}
    return {r["id"]: r for r in records if "id" in r}


async def build(avatar_slug: str, ids: set[str], destination: Path, color_override: str | None,
                profile_name: str | None = None, size: tuple[int, int] | None = None) -> int:
    from PIL import Image, ImageStat

    from wardrobe.vrm.document import GltfDocument

    style = load_style()
    catalog = TemplateCatalog.from_directory(ROOT / "assets" / "garment_templates")
    unknown = ids - {t.id for t in catalog}
    if unknown:
        raise SystemExit(f"Unknown garment template IDs: {', '.join(sorted(unknown))}")
    if profile_name is not None:
        chosen = _profiles(style).get(profile_name)
        if chosen is None:
            raise SystemExit(f"No preview profile {profile_name!r} in preview-style.json")
        if chosen.get("avatar") != avatar_slug:
            raise SystemExit(f"The {profile_name} profile is rendered on {chosen.get('avatar')}, "
                             f"not {avatar_slug}")
    library = AvatarLibrary.from_directory(ROOT / "assets" / "library")
    entries = {}
    for slug in {avatar_slug}:
        entry = library.get(slug)
        if entry is None or entry.path is None:
            raise SystemExit(f"Missing sample avatar {slug}. Run make library first.")
        if (entry.presentation or "") != "feminine":
            raise SystemExit(
                "Use a vetted feminine sample for the reference catalog; do not mix body types."
            )
        if entry.license.strip() not in {"CC0", "CC0-1.0"}:
            raise SystemExit("Sample avatar license not approved for distribution of derivative previews.")
        if profile_name is not None and not entry.depicts_adult:
            # The same declaration a person's job needs: the build does not get a way round it.
            raise SystemExit(f"{slug} is not declared adult in assets/library/policy.json; "
                             f"the {profile_name} profile renders only on an avatar the operator declared")
        entries[slug] = entry

    destination.mkdir(parents=True, exist_ok=True)
    previous = _previous(destination)
    width, height = size or style["canvas"]
    records = []
    to_render: list[tuple[str, dict]] = []  # (template id, view)
    with tempfile.TemporaryDirectory(prefix="catalog-templates-") as tmp:
        work = Path(tmp)
        settings = Settings(_env_file=None, wardrobe_storage_root=str(work / "store"),
                            wardrobe_engine="native", strict_licensing=True)
        store = LocalObjectStore(settings.storage_root_path, settings)
        orch = Orchestrator(
            settings=settings, store=store,
            jobs=InMemoryJobRepository(), wardrobes=InMemoryWardrobeRepository(),
            queue=AsyncioJobQueue(concurrency=1), catalog=catalog,
        )
        await library.seed(store)
        bases: dict[str, dict] = {}  # profile name -> its base avatar, made when first needed

        for t in sorted(catalog, key=lambda v: (v.category, v.id)):
            if ids and t.id not in ids:
                continue
            if not eligible(t, profile_name):
                if profile_name is None:
                    records.append({"id": t.id, "status": "restricted-skipped"})
                continue
            profile = profile_for(t, style, avatar_slug, profile_name)
            withheld = _profiles(style).get(profile_name or "", {}).get("withheld", {}).get(t.id)
            if withheld:
                records.append({"id": t.id, "status": "withheld-quality", "reason": withheld})
                (destination / f"{t.id}.webp").unlink(missing_ok=True)
                continue
            color = color_override or color_for(t, catalog, profile["colors"])
            frame = profile["frame"]
            key = cache_key(t, profile, color, style)
            target = destination / (t.id + ".webp")
            before = previous.get(t.id, {})
            if target.is_file() and all(before.get(k) == v for k, v in key.items()):
                try:
                    with Image.open(target) as cached:
                        cached.verify()
                    qa = ("rating", "fitPassed", "garments", "clippingCheck", "warnings")
                    kept = {k: before[k] for k in qa if k in before}
                    records.append({"id": t.id, "status": "cached", **key, **kept})
                    continue
                except (OSError, ValueError):
                    target.unlink(missing_ok=True)
            try:
                if profile["name"] not in bases:
                    bases[profile["name"]] = await _reference_base(
                        orch, store, entries[profile["avatar"]], profile["base"], profile["name"])
                request = CreateJobRequest.model_validate({
                    "avatar": bases[profile["name"]],
                    "outfit": {
                        "prompt": " ".join(filter(None, (color, profile.get("fabric"), t.name))),
                        "mode": "template",
                        "templateId": t.id,
                        "color": color,
                    },
                    "options": {"renderPreview": False, "engine": "native", "baseBody": profile["baseBody"]},
                })
                result = await orch.run_now(request)
                ok = (
                    result.state == "completed"
                    and result.look is not None
                    and result.fit_report is not None
                    and result.fit_report.passed
                    and result.plan is not None
                    and rating_for(result.plan) in profile["ratings"]
                    and _planned_from(t.id, result.plan)
                )
                if not ok:
                    records.append({
                        "id": t.id, "status": "failed-or-ineligible", **key,
                        "jobState": str(result.state),
                        "fitPassed": bool(result.fit_report and result.fit_report.passed),
                        "reason": str(result.reason or result.error or "fit not verified"),
                    })
                    continue
                garments = _rendered(result.plan)
                product = [g["name"] for g in garments]
                if profile.get("finish"):
                    result = await _finish(orch, bases[profile["name"]], result, profile["finish"], color)
                    if result is None:
                        records.append({"id": t.id, "status": "failed-or-ineligible", **key,
                                        "reason": f"{profile['finish']['template']} did not fit over it"})
                        continue
                    garments += _rendered(result.plan)
                data = await store.get(f"looks/{result.look.id}/look.vrm")
                (work / f"g-{t.id}.vrm").write_bytes(data)
                stature = _height(GltfDocument.from_bytes(data))
                focus = [round(frame[0] * stature, 3), round(frame[1] * stature, 3)]
                styled = [g["name"] for g in garments]
                for view in presentation_views(t.id, profile, style, focus, (width, height), product, styled):
                    to_render.append((t.id, view))
                records.append({"id": t.id, "status": "pending-render", **key,
                                "rating": rating_for(result.plan), "fitPassed": True,
                                "garments": garments,
                                "clippingCheck": str(result.fit_report.clipping_check),
                                "warnings": [str(w)[:200] for w in result.fit_report.warnings][:6]})
            except Exception as exc:
                records.append({
                    "id": t.id, "status": "failed-or-ineligible", **key,
                    "reason": f"{type(exc).__name__}: {str(exc)[:200]}",
                })
                continue

        # The existing gallery renderer (tools/gallery/views.mjs) is the source of visual
        # truth. Render in bounded chunks so a corrupted VRM cannot discard 50 good images.
        by_id = {record["id"]: record for record in records}
        for start in range(0, len(to_render), 6):
            chunk = to_render[start:start + 6]
            (work / "views.json").write_text(json.dumps([view for _tid, view in chunk]))
            try:
                subprocess.run(["node", str(ROOT / "tools/gallery/views.mjs"), str(work)],
                               check=True, cwd=ROOT, timeout=720)
            except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
                ids = [tid for tid, _v in chunk]
                print(f"Gallery renderer failed for chunk {ids}: {exc}", file=sys.stderr)

            for tid, view in chunk:
                screenshot = work / view["out"]
                record = by_id[tid]
                variant = view.get("variant", "front")
                name = tid if variant == "front" else f"{tid}--{variant}"
                if variant != "front":
                    # A product view beside the thumbnail: its failure is reported, not fatal.
                    try:
                        with Image.open(screenshot) as original:
                            extra = original.convert("RGB")
                        if max(ImageStat.Stat(extra).stddev) < 8:
                            raise ValueError("nearly uniform")
                        extra.save(destination / f"{name}.webp", "WEBP", quality=86, method=6)
                        record.setdefault("views", []).append(variant)
                    except (OSError, ValueError) as exc:
                        record.setdefault("viewErrors", {})[variant] = str(exc)[:120]
                    continue
                if not screenshot.is_file():
                    record.update(status="render-failed", reason="gallery screenshot missing")
                    continue
                try:
                    with Image.open(screenshot) as original:
                        img = original.convert("RGB")
                    # Skip empty/blank browser screenshots; never publish
                    # an image unrelated to a real rendered avatar.
                    if max(ImageStat.Stat(img).stddev) < 8:
                        raise ValueError("screenshot is nearly uniform; model may not have rendered")
                    if img.size != (width, height):
                        img = img.resize((width, height), Image.Resampling.LANCZOS)
                    img.save(destination / f"{tid}.webp", "WEBP", quality=82, method=6)
                    record["status"] = "generated"
                    record.setdefault("views", []).insert(0, "front")
                except (OSError, ValueError) as exc:
                    (destination / f"{tid}.webp").unlink(missing_ok=True)
                    record.update(status="render-failed", reason=str(exc)[:200])

    # A preview whose template is no longer published is removed, never left to be served.
    published = {r["id"] for r in records if r["status"] in {"generated", "cached"}}
    if not ids:
        for stale in destination.glob("*.webp"):
            if stale.stem.split("--")[0] not in published:
                stale.unlink()

    summary = {
        "schemaVersion": 2,
        "generatedAt": datetime.now(UTC).replace(microsecond=0).isoformat(),
        "sampleAvatar": avatar_slug,
        "profile": profile_name or "public",
        "previewFormat": "image/webp",
        "canvas": [width, height],
        "styleVersion": style["styleVersion"],
        "limitations": _profiles(style).get(profile_name, {}).get("limitations", []) if profile_name else [
            "The reference avatar's texture shows a dark band at the waist and brown tights on her "
            "legs: they are painted on her body, so no garment job can take them off.",
        ],
        "records": records if not ids else _merged(previous, records),
    }
    # Keep the failure report separate from the public API; the API only checks
    # existence of successfully exported preview image files.
    (destination.parent / "build-report.json").write_text(json.dumps(summary, indent=2) + "\n")
    failed = [r for r in records if r["status"] in {"failed-or-ineligible", "render-failed"}]
    generated = sum(r["status"] == "generated" for r in records)
    cached = sum(r["status"] == "cached" for r in records)
    print(f"{generated} WebPs rendered, {len(failed)} failed, "
          f"{cached} cached → {destination}")
    return 1 if failed else 0


async def _reference_base(orch, store, entry, base_style: dict, name: str) -> dict:
    """Her reference base, made once per profile and build: the neutral foundation on and her
    own clothes off (replace-outer takes off what the foundation covers). Every garment is
    fitted onto this, so her cardigan, shorts and tights no longer hid the trousers, skirts
    and shoes. The underwear profile's base is a nude set, put on with underwear-base."""
    base = await orch.run_now(CreateJobRequest.model_validate({
        "avatar": entry.avatar_input(),
        "outfit": {"prompt": base_style["prompt"], "mode": "auto"},
        "options": {"renderPreview": False, "engine": "native", "baseBody": base_style["baseBody"]},
    }))
    if base.state != "completed" or base.look is None or not (base.fit_report and base.fit_report.passed):
        raise RuntimeError(f"the reference base could not be made: {base.reason or base.error or base.state}")
    key = f"sources/catalog-base-{name}.vrm"
    await store.put(key, await store.get(f"looks/{base.look.id}/look.vrm"))
    avatar = {k: v for k, v in dict(entry.avatar_input()).items() if k not in ("url", "sha256", "storageKey")}
    avatar["storageKey"] = key
    return avatar


def presentation_views(template_id: str, profile: dict, style: dict, focus: list, size: tuple[int, int],
                       product: list[str], styled: list[str]) -> list[dict]:
    """The views one fitted garment is rendered as.

    Without a ``presentation`` block: one view, exactly the one this builder always made. With
    one (PR1): fitting is unchanged, and what is drawn is chosen here. ``product`` is the
    garments of this template's own job; the nude base set it was fitted over, and her own
    clothes, are hidden unless ``showUnrelatedFoundation`` says otherwise. Each named view
    turns her (front, back, three-quarter); ``enableGarmentIsolation`` adds the garment alone
    (ghost); a finishing piece (the guêpière's bralette) adds a ``styled`` view naming it,
    while the plain views show the template's own construction only.
    """
    base = {"file": f"g-{template_id}.vrm", "size": list(size), "focus": focus}
    present = profile.get("presentation")
    if not present:
        return [{**base, "out": f"r-{template_id}.png", "yaw": style["yaw"]}]
    show = None if present.get("showUnrelatedFoundation") else product
    light = present.get("light")
    views = []
    for spec in present["views"]:
        view = {**base, "out": f"r-{template_id}--{spec['name']}.png", "yaw": spec["yaw"],
                "variant": spec["name"], "light": light}
        if show is not None:
            view["present"] = {"mode": present.get("mode", "form"), "product": show,
                               "shading": present.get("shading")}
        views.append(view)
    if present.get("enableGarmentIsolation"):
        # UA2. ``isolationViews`` turns the garment alone more than one way: from behind is how a
        # thong's or a G-string's back is inspected, since on the form it sits between her glutes
        # and the dress-form back view barely shows it. Without the list, the one view as before.
        alone = {"mode": "ghost", "product": product, "shading": present.get("shading")}
        for spec in present.get("isolationViews") or [{"name": "garment-only", "yaw": -20}]:
            views.append({**base, "out": f"r-{template_id}--{spec['name']}.png", "yaw": spec["yaw"],
                          "variant": spec["name"], "light": light, "present": alone})
    if styled != product:
        views.append({**base, "out": f"r-{template_id}--styled.png", "yaw": present["views"][0]["yaw"],
                      "variant": "styled", "light": light,
                      "present": {"mode": present.get("mode", "form"), "product": styled,
                                  "shading": present.get("shading")}})
    return views


def _planned_from(template_id: str, plan) -> bool:
    """The plan is this template: its own id, or the parts Forge plans a set as (SET_PARTS)."""
    ids = {g.template_id for g in plan.garments}
    return template_id in ids or bool(set(SET_PARTS.get(template_id, ())) & ids)


def _rendered(plan) -> list[dict]:
    """What was actually built, as the planner resolved it: a hosiery belt picks its own colour."""
    return [{"name": g.name, "templateId": g.template_id, "color": g.material.color_name,
             "fabric": g.material.fabric} for g in plan.garments]


async def _finish(orch, base_avatar: dict, result, finish: dict, color: str):
    """Fit the profile's finishing piece over the finished look (the guêpière's bralette)."""
    styled = await orch.run_now(CreateJobRequest.model_validate({
        "avatar": {**base_avatar, "storageKey": f"looks/{result.look.id}/look.vrm"},
        "outfit": {"prompt": f"{color} {finish['template']}", "mode": "template",
                   "templateId": finish["template"], "color": color},
        "options": {"renderPreview": False, "engine": "native", "baseBody": finish["baseBody"]},
    }))
    ok = (styled.state == "completed" and styled.look is not None and styled.fit_report is not None
          and styled.fit_report.passed)
    return styled if ok else None


def _height(document) -> float:
    return float(max(document.read_accessor(p["attributes"]["POSITION"])[:, 1].max()
                     for mesh in document.meshes for p in mesh["primitives"]))


def _merged(previous: dict, records: list[dict]) -> list[dict]:
    """A partial build (--ids) updates its own records and keeps everyone else's."""
    merged = dict(previous)
    merged.update({r["id"]: r for r in records})
    return [merged[k] for k in sorted(merged)]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--avatar", default="avatar-sample-a")
    parser.add_argument("--ids", nargs="*", default=[])
    parser.add_argument("--color", default=None,
                        help="one colour for every garment (default: preview-style.json's rules)")
    parser.add_argument("--size", default=None, help="WxH, e.g. 960x1280 for a review build")
    parser.add_argument("--profile", default=None,
                        help="a preview-style.json profile (underwear): the adult catalog, built apart")
    parser.add_argument("--out", type=Path, default=None)
    args = parser.parse_args()
    out = args.out or (ROOT / "assets" / "catalog" / ("adult/previews" if args.profile else "previews"))
    size = tuple(int(n) for n in args.size.split("x")) if args.size else None
    return asyncio.run(build(args.avatar, set(args.ids), out, args.color, args.profile, size))


if __name__ == "__main__":
    raise SystemExit(main())
