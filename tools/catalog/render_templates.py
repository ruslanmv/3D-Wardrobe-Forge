"""Build genuine WebP clothing thumbnails with Forge and the Studio VRM viewer.

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
import json
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


async def build(avatar_slug: str, ids: set[str], destination: Path, color: str) -> int:
    from PIL import Image, ImageStat

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
    records = []
    rendered_ids: list[str] = []
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

        for t in sorted(catalog, key=lambda v: (v.category, v.id)):
            if ids and t.id not in ids:
                continue
            if not eligible(t):
                records.append({"id": t.id, "status": "restricted-skipped"})
                continue
            if (destination / (t.id + ".webp")).is_file():
                try:
                    with Image.open(destination / (t.id + ".webp")) as cached:
                        cached.verify()
                    records.append({"id": t.id, "status": "cached"})
                    continue
                except (OSError, ValueError):
                    (destination / (t.id + ".webp")).unlink(missing_ok=True)
            try:
                request = CreateJobRequest.model_validate({
                    "avatar": entry.avatar_input(),
                    "outfit": {
                        "prompt": f"{color} {t.name}",
                        "mode": "template",
                        "templateId": t.id,
                        "color": color,
                    },
                    "options": {
                        "renderPreview": False,
                        "engine": "native",
                        "baseBody": "replace-outer",
                        "ensureFoundation": True,
                    },
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
                        "id": t.id, "status": "failed-or-ineligible",
                        "jobState": str(result.state),
                        "reason": str(result.reason or result.error or "fit not verified"),
                    })
                    continue
                data = await store.get(f"looks/{result.look.id}/look.vrm")
                (work / f"g-{t.id}.vrm").write_bytes(data)
                rendered_ids.append(t.id)
                records.append({"id": t.id, "status": "pending-render"})
            except Exception as exc:
                records.append({
                    "id": t.id, "status": "failed-or-ineligible",
                    "reason": f"{type(exc).__name__}: {str(exc)[:200]}",
                })
                continue

        # The existing gallery renderer is the source of visual truth. Render
        # in bounded chunks so a corrupted VRM cannot discard 50 good images.
        by_id = {entry["id"]: entry for entry in records}
        for start in range(0, len(rendered_ids), 6):
            chunk = rendered_ids[start:start + 6]
            try:
                subprocess.run(
                    ["node", str(ROOT / "tools/gallery/render.mjs"), str(work), *chunk],
                    check=True, cwd=ROOT, timeout=720,
                )
            except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
                print(f"Gallery renderer failed for chunk {chunk}: {exc}", file=sys.stderr)

            for tid in chunk:
                screenshot = work / f"r-{tid}-34.png"
                entry = by_id[tid]
                if not screenshot.is_file():
                    entry.update(status="render-failed", reason="gallery screenshot missing")
                    continue
                try:
                    with Image.open(screenshot) as original:
                        img = original.convert("RGB")
                    # Skip empty/blank browser screenshots; never publish
                    # an image unrelated to a real rendered avatar.
                    if max(ImageStat.Stat(img).stddev) < 8:
                        raise ValueError("screenshot is nearly uniform; model may not have rendered")
                    width = 480
                    height = round(img.height * width / img.width)
                    img = img.resize((width, height), Image.Resampling.LANCZOS)
                    img.save(destination / f"{tid}.webp", "WEBP", quality=82, method=6)
                    entry["status"] = "generated"
                except (OSError, ValueError) as exc:
                    (destination / f"{tid}.webp").unlink(missing_ok=True)
                    entry.update(status="render-failed", reason=str(exc)[:200])

    summary = {
        "schemaVersion": 1,
        "generatedAt": datetime.now(UTC).replace(microsecond=0).isoformat(),
        "sampleAvatar": avatar_slug,
        "previewFormat": "image/webp",
        "records": records,
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


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--avatar", default="avatar-sample-a")
    parser.add_argument("--ids", nargs="*", default=[])
    parser.add_argument("--color", default="navy")
    parser.add_argument("--out", type=Path,
                        default=ROOT / "assets" / "catalog" / "previews")
    args = parser.parse_args()
    return asyncio.run(build(args.avatar, set(args.ids), args.out, args.color))


if __name__ == "__main__":
    raise SystemExit(main())
