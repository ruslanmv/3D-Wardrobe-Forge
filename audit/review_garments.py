"""Render a real fitted VRM the way the Model Girl reviews were made.

The pictures are not template previews. Each prompt goes through the same
orchestrator the API uses, on Model Girl, and the Studio viewer
(``tools/gallery/views.mjs``) photographs the VRM that job wrote.

    python audit/review_garments.py OUT_DIR
    python audit/review_garments.py OUT_DIR --name tee --prompt "black fitted tee"
    python audit/review_garments.py OUT_DIR --no-render

Default looks are the four dark-fashion garments, with the detail bands used
for their review. A new look without ``--focus`` is framed on the upper half
of the meshes this pipeline attached. Studio light and an orthographic camera
are fixed, so two runs can be compared.

Model Girl arrives in her own dress. Unless ``--keep-clothes`` is set, that
source outfit (tops, one-piece, bottoms, shoes) is taken off the copy the job
starts from, so the new garment is what the picture shows.

Writes ``OUT_DIR/<name>.vrm``, the five PNGs, ``views.json`` and ``records.json``.
Rendering needs Node, Playwright and Chromium, as ``tools/gallery/views.mjs`` does
(``PLAYWRIGHT_CHROMIUM``). ``--no-render`` still writes the VRMs and ``views.json``.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from wardrobe.config import Settings  # noqa: E402
from wardrobe.domain.garments import TemplateCatalog  # noqa: E402
from wardrobe.domain.jobs import CreateJobRequest  # noqa: E402
from wardrobe.pipeline.orchestrator import Orchestrator  # noqa: E402
from wardrobe.queue.jobs import AsyncioJobQueue  # noqa: E402
from wardrobe.storage.database import InMemoryJobRepository, InMemoryWardrobeRepository  # noqa: E402
from wardrobe.storage.object_store import LocalObjectStore  # noqa: E402
from wardrobe.vrm.document import GltfDocument  # noqa: E402
from wardrobe.vrm.garments import remove_slots  # noqa: E402

GIRL = ROOT / "assets" / "library" / "vroid" / "vroid-model-girl.vrm"
VIEWS = ROOT / "tools" / "gallery" / "views.mjs"
#: Source slots taken off before the job, so a dress she arrived in is not left underneath.
STRIP = ["tops", "onepiece", "bottoms", "shoes"]
#: Full body, then the construction close-up. Yaw is degrees, the Studio's camera.
FULL = (640, 960)
DETAIL = (800, 800)
VIEWS_OF = (
    ("front", 0, None),
    ("back", 180, None),
    ("side", 90, None),
    ("three-quarter", 40, None),
    ("detail", 25, "focus"),
)

#: name, prompt, detail focus [y0, y1] in the fitted VRM, or None to measure it.
DARK_FASHION = [
    ("catsuit", "high-neck latex catsuit", [1.02, 1.40]),
    ("garter", "leather garter belt with stockings", [0.62, 1.05]),
    ("dress", "buckle-front leather mini dress", [0.78, 1.24]),
    ("corset", "structured leather corset", [0.88, 1.36]),
]


def strip_source_outfit(data: bytes) -> tuple[bytes, list[str]]:
    """A copy of the avatar with her own clothes removed. The body underneath stays."""
    document = GltfDocument.from_bytes(data)
    removed = remove_slots(document, STRIP)
    return document.to_bytes(), removed


def garment_bounds(data: bytes) -> tuple[float, float, float, float] | None:
    """Axis-aligned bounds of the meshes this pipeline attached, in the VRM's rest pose."""
    document = GltfDocument.from_bytes(data)
    points = []
    for node in document.nodes:
        extras = node.get("extras") if isinstance(node.get("extras"), dict) else {}
        tag = extras.get("wardrobeForge") if isinstance(extras, dict) else None
        if not isinstance(tag, dict) or tag.get("kind") != "garment" or "mesh" not in node:
            continue
        for primitive in document.meshes[node["mesh"]].get("primitives", []):
            position = primitive.get("attributes", {}).get("POSITION")
            if position is None:
                continue
            points.append(document.read_accessor(position)[:, :3])
    if not points:
        return None
    cloud = np.vstack(points)
    low, high = cloud.min(axis=0), cloud.max(axis=0)
    return float(low[0]), float(high[0]), float(low[1]), float(high[1])


def detail_focus(bounds, preset: list[float] | None) -> list[float] | None:
    """The close-up band: a look's own band, or the upper half of the garment it grew."""
    if preset is not None:
        return [float(preset[0]), float(preset[1])]
    if bounds is None:
        return None
    _x0, _x1, y0, y1 = bounds
    return [round(y0 + (y1 - y0) * 0.45, 3), round(y1 + 0.03, 3)]


def view_list(name: str, focus: list[float] | None) -> list[dict]:
    """Front, back, side, three-quarter, and a close-up. Studio light, orthographic."""
    views = []
    for label, yaw, kind in VIEWS_OF:
        size = DETAIL if kind else FULL
        view = {
            "file": f"{name}.vrm",
            "out": f"{name}-{label}.png",
            "yaw": yaw,
            "size": list(size),
            "ortho": True,
            "light": "studio",
        }
        if kind == "focus" and focus is not None:
            view["focus"] = focus
        views.append(view)
    return views


def _summarise(result) -> dict:
    plan = result.plan
    garments = []
    if plan is not None:
        for garment in plan.garments:
            garments.append(
                {
                    "name": garment.name,
                    "templateId": garment.template_id,
                    "role": garment.role,
                    "finish": garment.material.finish,
                    "requiresAdult": garment.requires_adult,
                }
            )
    fit = result.fit_report
    state = getattr(result.state, "value", result.state)
    return {
        "state": state,
        "error": result.error,
        "passed": getattr(fit, "passed", None),
        "clipping": getattr(fit, "clipping", None),
        "garments": garments,
    }


async def build(out: Path, looks: list[tuple], avatar: Path, *, adult: bool, keep: bool) -> list[dict]:
    """Fit each look. Returns the records, and leaves ``<name>.vrm`` in ``out``."""
    out.mkdir(parents=True, exist_ok=True)
    source, removed = (avatar.read_bytes(), []) if keep else strip_source_outfit(avatar.read_bytes())
    tmp = Path(tempfile.mkdtemp(prefix="audit-review-"))
    settings = Settings(
        wardrobe_storage_root=str(tmp),
        wardrobe_engine="native",
        strict_licensing=True,
    )
    store = LocalObjectStore(settings.storage_root_path, settings)
    orchestrator = Orchestrator(
        settings=settings,
        store=store,
        jobs=InMemoryJobRepository(),
        wardrobes=InMemoryWardrobeRepository(),
        queue=AsyncioJobQueue(concurrency=1),
        catalog=TemplateCatalog.from_directory(ROOT / "assets" / "garment_templates"),
    )
    await store.put("sources/girl.vrm", source)
    records = []
    for name, prompt, focus in looks:
        request = CreateJobRequest.model_validate(
            {
                "avatar": {
                    "storageKey": "sources/girl.vrm",
                    "avatarId": "vroid-model-girl",
                    "depictsAdult": adult,
                },
                "outfit": {"prompt": prompt, "mode": "template"},
                "options": {"renderPreview": False, "engine": "native"},
            }
        )
        result = await orchestrator.run_now(request)
        data = await store.get(f"looks/{result.look.id}/look.vrm") if result.look else None
        entry = {"name": name, "prompt": prompt, "removedSourceMaterials": removed, **_summarise(result)}
        if data is not None:
            (out / f"{name}.vrm").write_bytes(data)
            bounds = garment_bounds(data)
            entry["bounds"] = bounds
            entry["views"] = view_list(name, detail_focus(bounds, focus))
        else:
            entry["views"] = []
        records.append(entry)
        print(
            name,
            entry["state"],
            entry["passed"],
            prompt,
            "->",
            [g["templateId"] for g in entry["garments"]],
            entry["error"] or "",
        )
    return records


def render(out: Path, records: list[dict]) -> None:
    """Photograph every view with the Studio viewer. Leaves the PNGs beside the VRMs."""
    views = [view for record in records for view in record.get("views", [])]
    if not views:
        print("no VRM to render")
        return
    (out / "views.json").write_text(json.dumps(views, indent=2))
    link = ROOT / "node_modules"
    made = False
    playwright = Path("/tmp/review-pw/node_modules")
    if not (link / "playwright").exists() and (playwright / "playwright").exists() and not link.exists():
        link.symlink_to(playwright)
        made = True
    try:
        done = subprocess.run(
            ["node", str(VIEWS), str(out)],
            cwd=str(ROOT),
            check=False,
        )
    finally:
        if made:
            link.unlink(missing_ok=True)
    if done.returncode != 0:
        raise SystemExit(done.returncode)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("out", type=Path)
    parser.add_argument("--name", action="append", default=[], help="look name, paired with --prompt")
    parser.add_argument("--prompt", action="append", default=[], help="outfit prompt, in --name order")
    parser.add_argument(
        "--focus",
        action="append",
        default=[],
        help="detail band y0,y1 for one --prompt, or '-' to measure it",
    )
    parser.add_argument("--avatar", type=Path, default=GIRL)
    parser.add_argument(
        "--adult",
        action="store_true",
        help="declare depictsAdult (required for the garter; on for the default looks)",
    )
    parser.add_argument(
        "--keep-clothes", action="store_true", help="leave the avatar's own outfit on under the new garment"
    )
    parser.add_argument("--no-render", action="store_true", help="write the VRMs and views.json only")
    args = parser.parse_args()
    if args.name or args.prompt:
        if len(args.name) != len(args.prompt):
            raise SystemExit("--name and --prompt must be given the same number of times")
        focuses: list = []
        for raw in args.focus:
            focuses.append(None if raw == "-" else [float(part) for part in raw.split(",")])
        while len(focuses) < len(args.name):
            focuses.append(None)
        looks = list(zip(args.name, args.prompt, focuses, strict=True))
        adult = args.adult
    else:
        looks = list(DARK_FASHION)
        adult = True
    out = args.out.resolve()
    records = asyncio.run(build(out, looks, args.avatar.resolve(), adult=adult, keep=args.keep_clothes))
    (out / "records.json").write_text(json.dumps(records, indent=2))
    views = [view for record in records for view in record.get("views", [])]
    (out / "views.json").write_text(json.dumps(views, indent=2))
    if not args.no_render:
        render(out, records)


if __name__ == "__main__":
    main()
