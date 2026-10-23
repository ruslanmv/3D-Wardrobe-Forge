"""Build genuine WebP clothing thumbnails with Forge and the Studio VRM viewer.

Each garment is fitted onto a reference base (the neutral foundation, her own clothes off),
in its own colour, and framed by category; preview-style.json says how.

Usage (after make library and browser dependencies):
    python tools/catalog/render_templates.py --avatar avatar-sample-a
    python tools/catalog/render_templates.py --avatar avatar-sample-a --ids top-crop-tee-v1 jeans-straight-v1

Previews are REAL generated looks fitted to a fixed sample avatar, NOT
isolated GLBs or promised universal garment assets. The catalog API only
advertises images that this script successfully created and that have been
included in the deployment. The public builder never renders adult-gated looks.

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
from wardrobe.queue.jobs import AsyncioJobQueue  # noqa: E402
from wardrobe.storage.database import InMemoryJobRepository, InMemoryWardrobeRepository  # noqa: E402
from wardrobe.storage.object_store import LocalObjectStore  # noqa: E402
from wardrobe.targets.pack import rating_for  # noqa: E402


def eligible(template) -> bool:
    return template.category not in INTIMATE_CATEGORIES and not template.requires_adult


#: How previews look: base outfit, canvas, framing by category, colour rules (bump its
#: styleVersion to re-render everything). Read by this script only.
STYLE_PATH = ROOT / "tools" / "catalog" / "preview-style.json"


def load_style() -> dict:
    return json.loads(STYLE_PATH.read_text(encoding="utf-8"))


def color_for(template, catalog, style: dict) -> str:
    """The colour a template is previewed in: a matching rule, else the category palette in
    order of template id. Fixed for every build, so a preview never changes colour by itself."""
    for rule in style["colors"]["rules"]:
        if re.search(rule["match"], template.id):
            return rule["color"]
    palette = style["colors"]["palette"]
    siblings = sorted(t.id for t in catalog if t.category == template.category)
    return palette[siblings.index(template.id) % len(palette)]


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


async def build(avatar_slug: str, ids: set[str], destination: Path, color_override: str | None) -> int:
    from PIL import Image, ImageStat

    from wardrobe.vrm.document import GltfDocument

    style = load_style()
    catalog = TemplateCatalog.from_directory(ROOT / "assets" / "garment_templates")
    unknown = ids - {t.id for t in catalog}
    if unknown:
        raise SystemExit(f"Unknown garment template IDs: {', '.join(sorted(unknown))}")
    library = AvatarLibrary.from_directory(ROOT / "assets" / "library")
    entry = library.get(avatar_slug)
    if entry is None or entry.path is None:
        raise SystemExit(f"Missing sample avatar {avatar_slug}. Run make library first.")
    if (entry.presentation or "") != "feminine":
        raise SystemExit(
            "Use a vetted feminine sample for the reference catalog; do not mix body types."
        )
    if entry.license.strip() not in {"CC0", "CC0-1.0"}:
        raise SystemExit("Sample avatar license not approved for distribution of derivative previews.")

    destination.mkdir(parents=True, exist_ok=True)
    previous = _previous(destination)
    width, height = style["canvas"]
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
        base_avatar = None  # made on the first garment that needs rendering

        for t in sorted(catalog, key=lambda v: (v.category, v.id)):
            if ids and t.id not in ids:
                continue
            if not eligible(t):
                records.append({"id": t.id, "status": "restricted-skipped"})
                continue
            color = color_override or color_for(t, catalog, style)
            frame = style["framing"].get(t.category, [0.0, 1.0])
            key = {"color": color, "framing": frame, "styleVersion": style["styleVersion"],
                   "templateSha256": template_digest(t.id), "sampleAvatar": avatar_slug}
            target = destination / (t.id + ".webp")
            before = previous.get(t.id, {})
            if target.is_file() and all(before.get(k) == v for k, v in key.items()):
                try:
                    with Image.open(target) as cached:
                        cached.verify()
                    records.append({"id": t.id, "status": "cached", **key})
                    continue
                except (OSError, ValueError):
                    target.unlink(missing_ok=True)
            try:
                if base_avatar is None:
                    base_avatar = await _reference_base(orch, store, entry, style)
                request = CreateJobRequest.model_validate({
                    "avatar": base_avatar,
                    "outfit": {
                        "prompt": f"{color} {t.name}",
                        "mode": "template",
                        "templateId": t.id,
                        "color": color,
                    },
                    "options": {"renderPreview": False, "engine": "native", "baseBody": "replace-outer"},
                })
                result = await orch.run_now(request)
                ok = (
                    result.state == "completed"
                    and result.look is not None
                    and result.fit_report is not None
                    and result.fit_report.passed
                    and result.plan is not None
                    and rating_for(result.plan) == "general"
                    and any(g.template_id == t.id for g in result.plan.garments)
                )
                if not ok:
                    records.append({
                        "id": t.id, "status": "failed-or-ineligible", **key,
                        "jobState": str(result.state),
                        "reason": str(result.reason or result.error or "fit not verified"),
                    })
                    continue
                data = await store.get(f"looks/{result.look.id}/look.vrm")
                (work / f"g-{t.id}.vrm").write_bytes(data)
                stature = _height(GltfDocument.from_bytes(data))
                focus = [round(frame[0] * stature, 3), round(frame[1] * stature, 3)]
                view = {"file": f"g-{t.id}.vrm", "out": f"r-{t.id}.png", "size": [width, height],
                        "yaw": style["yaw"], "focus": focus}
                to_render.append((t.id, view))
                records.append({"id": t.id, "status": "pending-render", **key})
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
                except (OSError, ValueError) as exc:
                    (destination / f"{tid}.webp").unlink(missing_ok=True)
                    record.update(status="render-failed", reason=str(exc)[:200])

    # A preview whose template is no longer published is removed, never left to be served.
    published = {r["id"] for r in records if r["status"] in {"generated", "cached"}}
    if not ids:
        for stale in destination.glob("*.webp"):
            if stale.stem not in published:
                stale.unlink()

    summary = {
        "schemaVersion": 2,
        "generatedAt": datetime.now(UTC).replace(microsecond=0).isoformat(),
        "sampleAvatar": avatar_slug,
        "previewFormat": "image/webp",
        "canvas": [width, height],
        "styleVersion": style["styleVersion"],
        "limitations": [
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


async def _reference_base(orch, store, entry, style: dict) -> dict:
    """Her reference base, made once per build: the neutral foundation on and her own clothes
    off (replace-outer takes off what the foundation covers). Every garment is fitted onto
    this, so her cardigan, shorts and tights no longer hid the trousers, skirts and shoes."""
    base = await orch.run_now(CreateJobRequest.model_validate({
        "avatar": entry.avatar_input(),
        "outfit": {"prompt": style["base"]["prompt"], "mode": "auto"},
        "options": {"renderPreview": False, "engine": "native", "baseBody": "replace-outer"},
    }))
    if base.state != "completed" or base.look is None or not (base.fit_report and base.fit_report.passed):
        raise RuntimeError(f"the reference base could not be made: {base.reason or base.error or base.state}")
    await store.put("sources/catalog-base.vrm", await store.get(f"looks/{base.look.id}/look.vrm"))
    avatar = {k: v for k, v in dict(entry.avatar_input()).items() if k not in ("url", "sha256", "storageKey")}
    avatar["storageKey"] = "sources/catalog-base.vrm"
    return avatar


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
    parser.add_argument("--out", type=Path,
                        default=ROOT / "assets" / "catalog" / "previews")
    args = parser.parse_args()
    return asyncio.run(build(args.avatar, set(args.ids), args.out, args.color))


if __name__ == "__main__":
    raise SystemExit(main())
