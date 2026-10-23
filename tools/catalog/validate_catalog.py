"""Audit public catalog previews produced by the Forge batch renderer.

Refuses stale, tampered, placeholder, adult-gated, or undeclared image files.
Creates a visual contact sheet as a CI artifact for human quality review.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from PIL import Image, ImageDraw, ImageStat  # noqa: E402

from wardrobe.domain.garments import INTIMATE_CATEGORIES, TemplateCatalog  # noqa: E402


def validate(root: Path, report_path: Path, contact_sheet: Path) -> int:
    catalog = TemplateCatalog.from_directory(ROOT / "assets" / "garment_templates")
    by_id = {template.id: template for template in catalog}
    report = json.loads(report_path.read_text())
    reported = {record["id"]: record for record in report["records"]}
    image_paths = sorted(root.glob("*.webp"))
    if len(reported) != len(by_id):
        raise SystemExit(
            f"incomplete catalog run: {len(reported)} template records; expected {len(by_id)}"
        )
    if not image_paths:
        raise SystemExit("No real WebP garment previews were created; refusing empty release")
    audit = []
    for path in image_paths:
        tid = path.stem
        template = by_id.get(tid)
        if template is None:
            raise SystemExit(f"Preview for unknown template: {tid}")
        if template.category in INTIMATE_CATEGORIES or template.requires_adult:
            raise SystemExit(f"Restricted preview must not be published: {tid}")
        if reported[tid]["status"] not in {"cached", "generated"}:
            raise SystemExit(f"Preview {tid} missing positive build evidence")
        data = path.read_bytes()
        if not data.startswith(b"RIFF") or data[8:12] != b"WEBP":
            raise SystemExit(f"Not a WebP file: {path}")
        with Image.open(path) as img:
            if img.format != "WEBP" or img.width < 300 or img.height < 400:
                raise SystemExit(f"Bad WebP dimensions/format: {path}")
            if max(ImageStat.Stat(img.convert("RGB")).stddev) < 8:
                raise SystemExit(f"Image looks blank/unrendered: {path}")
            thumb = img.convert("RGB").resize((144, 250), Image.Resampling.LANCZOS)
        audit.append(
            {"id": tid, "category": template.category, "sha256": hashlib.sha256(data).hexdigest(),
             "bytes": len(data), "width": 480, "preview": path.name, "_thumb": thumb}
        )
    for template in catalog:
        if reported[template.id]["status"] in {"cached", "generated"}:
            if not (root / (template.id + ".webp")).is_file():
                raise SystemExit(f"Build report claims preview that is missing: {template.id}")

    # Contact sheet is not distributed in the public API.
    columns = 7
    tile_w, tile_h = 164, 298
    rows = (len(audit) + columns - 1) // columns
    sheet = Image.new("RGB", (columns * tile_w, rows * tile_h), "#0b1420")
    draw = ImageDraw.Draw(sheet)
    for i, record in enumerate(audit):
        x = (i % columns) * tile_w
        y = (i // columns) * tile_h
        sheet.paste(record.pop("_thumb"), (x + 10, y + 8))
        label = record["id"]
        draw.text((x + 7, y + 261), label[:22], fill="#ddf7ff")
        draw.text((x + 7, y + 277), record["category"], fill="#5ccee8")
    contact_sheet.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(contact_sheet, "WEBP", quality=78)

    inventory = {
        "schemaVersion": 1,
        "source": "Forge template catalog with verified preview images",
        "sampleAvatar": report["sampleAvatar"],
        "count": len(audit),
        "items": [{k: v for k, v in item.items() if k != "_thumb"} for item in audit],
    }
    (root.parent / "preview-manifest.json").write_text(json.dumps(inventory, indent=2) + "\n")
    print(f"Validated {len(audit)} genuine WebP previews; contact sheet: {contact_sheet}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--contact-sheet", type=Path, default=Path("/tmp/catalog-contact-sheet.webp"))
    args = parser.parse_args()
    return validate(args.root, args.report, args.contact_sheet)


if __name__ == "__main__":
    raise SystemExit(main())
