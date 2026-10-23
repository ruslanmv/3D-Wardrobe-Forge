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
    # Schema 2 reports declare the canvas every preview was rendered on; a file of another
    # size is left over from an older style (or hand-placed) and does not belong to this build.
    canvas = tuple(report["canvas"]) if report.get("canvas") else None
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
            if canvas and (img.width, img.height) != canvas:
                raise SystemExit(f"Preview {tid} is {img.width}x{img.height}, not the build's {canvas}")
            if max(ImageStat.Stat(img.convert("RGB")).stddev) < 8:
                raise SystemExit(f"Image looks blank/unrendered: {path}")
            # Fitted into the tile, never stretched: a squashed contact sheet hides exactly the
            # proportions a reviewer is looking at.
            thumb = img.convert("RGB")
            thumb.thumbnail((144, 250), Image.Resampling.LANCZOS)
            width, height = img.width, img.height
        audit.append(
            {"id": tid, "category": template.category, "sha256": hashlib.sha256(data).hexdigest(),
             "bytes": len(data), "width": width, "height": height, "preview": path.name,
             "color": reported[tid].get("color"), "_thumb": thumb}
        )
    for template in catalog:
        claimed = reported[template.id]["status"] in {"cached", "generated"}
        if claimed and not (root / (template.id + ".webp")).is_file():
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
        thumb = record.pop("_thumb")
        sheet.paste(thumb, (x + 10 + (144 - thumb.width) // 2, y + 8 + (250 - thumb.height) // 2))
        label = record["id"]
        draw.text((x + 7, y + 261), label[:22], fill="#ddf7ff")
        draw.text((x + 7, y + 277), record["category"], fill="#5ccee8")
    contact_sheet.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(contact_sheet, "WEBP", quality=78)

    inventory = {
        "schemaVersion": 1,
        "source": "Forge template catalog with verified preview images",
        "sampleAvatar": report["sampleAvatar"],
        "styleVersion": report.get("styleVersion", 1),
        "count": len(audit),
        "items": [{k: v for k, v in item.items() if k != "_thumb"} for item in audit],
    }
    (root.parent / "preview-manifest.json").write_text(json.dumps(inventory, indent=2) + "\n")
    print(f"Validated {len(audit)} genuine WebP previews; contact sheet: {contact_sheet}")
    return 0


#: Garment types of the adult QA sheet, in shelf order: what a shopper browses by.
ADULT_GROUPS = [
    ("Bras & bralettes", ("bra", "bra-block")),
    ("Bodysuits & sets", ("one-piece", "bodysuit-block", "bikini")),
    ("Briefs & thongs", ("briefs", "brief-block")),
    ("Corsetry & suspenders", ("guepiere", "waspie", "suspender-belt")),
]


def validate_adult(profile: str, adult_root: Path) -> int:
    """The adult collection: every template of the profile's category accounted for.

    A preview is accepted only for a template the build report says was generated on
    the declared avatar with its fit passing; the rest are listed with their reason.
    The QA sheet shows all of them, a failure as a labelled empty tile, never a stand-in.
    """
    previews = adult_root / "previews"
    report = json.loads((adult_root / "build-report.json").read_text())
    if report.get("profile") != profile:
        raise SystemExit(f"{adult_root}/build-report.json is not a {profile} build")
    catalog = TemplateCatalog.from_directory(ROOT / "assets" / "garment_templates")
    templates = sorted((t for t in catalog if t.category == profile), key=lambda t: t.id)
    reported = {record["id"]: record for record in report["records"]}
    missing = [t.id for t in templates if t.id not in reported]
    if missing:
        raise SystemExit(f"incomplete {profile} run, never attempted: {', '.join(missing)}")
    stray = sorted(p.stem for p in previews.glob("*.webp") if p.stem not in {t.id for t in templates})
    if stray:
        raise SystemExit(f"Previews outside the {profile} category in the adult folder: {', '.join(stray)}")
    canvas = tuple(report["canvas"])
    items = []
    for template in templates:
        record = reported[template.id]
        path = previews / f"{template.id}.webp"
        claimed = record["status"] in {"cached", "generated"}
        if claimed != path.is_file():
            raise SystemExit(f"{template.id}: build report says {record['status']} but the file "
                             f"{'is missing' if claimed else 'exists'}")
        item = {"id": template.id, "name": template.name, "kind": template.procedural_kind,
                "status": record["status"], "fitPassed": record.get("fitPassed"),
                "rating": record.get("rating"), "color": record.get("color"),
                "baseBody": record.get("baseBody"), "warnings": record.get("warnings", []),
                "reason": record.get("reason")}
        if claimed:
            data = path.read_bytes()
            with Image.open(path) as img:
                if img.format != "WEBP" or (img.width, img.height) != canvas:
                    raise SystemExit(f"{template.id}: not a {canvas} WebP")
                if max(ImageStat.Stat(img.convert("RGB")).stddev) < 8:
                    raise SystemExit(f"{template.id}: image looks blank")
                thumb = img.convert("RGB")
            if record.get("fitPassed") is not True or record.get("rating") != "intimate":
                raise SystemExit(f"{template.id}: a preview without a passed fit and its real rating")
            thumb.thumbnail((180, 240), Image.Resampling.LANCZOS)
            item.update(sha256=hashlib.sha256(data).hexdigest(), bytes=len(data), preview=path.name,
                        width=canvas[0], height=canvas[1], _thumb=thumb)
        items.append(item)

    _adult_sheet(items, adult_root / "contact-sheet.webp", profile)
    ready = [i for i in items if "_thumb" in i]
    manifest = {
        "schemaVersion": 1,
        "collection": profile,
        "access": "admin session only (X-Wardrobe-Admin); requiresAdult on every item",
        "sampleAvatar": report["sampleAvatar"],
        "styleVersion": report.get("styleVersion"),
        "count": len(items),
        "readyCount": len(ready),
        "limitations": report.get("limitations", []),
        "items": [{k: v for k, v in i.items() if k != "_thumb"} for i in items],
    }
    (adult_root / "manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n")
    sheet = adult_root / "contact-sheet.webp"
    print(f"{len(ready)} of {len(items)} {profile} previews validated; sheet: {sheet}")
    return 0


def _adult_sheet(items: list[dict], out: Path, profile: str) -> None:
    tile_w, tile_h, columns = 200, 330, 7
    rows = []
    known = {kind for _label, kinds in ADULT_GROUPS for kind in kinds}
    groups = [(label, [i for i in items if i["kind"] in kinds]) for label, kinds in ADULT_GROUPS]
    groups.append(("Other", [i for i in items if i["kind"] not in known]))
    for label, members in groups:
        if not members:
            continue
        rows.append(("label", label))
        for start in range(0, len(members), columns):
            rows.append(("tiles", members[start:start + columns]))
    height = sum(28 if kind == "label" else tile_h for kind, _ in rows) + 40
    sheet = Image.new("RGB", (columns * tile_w, height), "#15121a")
    draw = ImageDraw.Draw(sheet)
    draw.text((10, 12), f"{profile} QA - {sum('_thumb' in i for i in items)} of {len(items)} rendered",
              fill="#ffffff")
    y = 40
    for kind, payload in rows:
        if kind == "label":
            draw.text((10, y + 8), payload.upper(), fill="#e8b4c8")
            y += 28
            continue
        for column, item in enumerate(payload):
            x = column * tile_w
            thumb = item.get("_thumb")
            if thumb is not None:
                sheet.paste(thumb, (x + 10 + (180 - thumb.width) // 2, y + 4))
            else:
                draw.rectangle((x + 10, y + 4, x + 190, y + 244), outline="#c0392b")
                draw.text((x + 16, y + 110), "NOT RENDERED", fill="#ff7b6b")
                for n, start in enumerate(range(0, min(len(item.get("reason") or ""), 120), 28)):
                    draw.text((x + 16, y + 128 + 14 * n), item["reason"][start:start + 28], fill="#d0a0a0")
            draw.text((x + 8, y + 250), item["id"][:30], fill="#ffffff")
            draw.text((x + 8, y + 264), item["name"][:30], fill="#cfc6d8")
            fit = {True: "fit pass", False: "fit FAIL", None: "fit -"}[item.get("fitPassed")]
            draw.text((x + 8, y + 278), f"{item['status']} | {fit}", fill="#7fd6a4" if thumb else "#ff7b6b")
            styling = f"{item.get('color') or ''} | {item.get('baseBody') or ''}"
            draw.text((x + 8, y + 292), styling, fill="#9aa")
            defects = "; ".join(item.get("warnings") or []) or "no warnings"
            draw.text((x + 8, y + 306), defects[:32], fill="#d8c27a" if item.get("warnings") else "#777")
        y += tile_h
    out.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(out, "WEBP", quality=85)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path)
    parser.add_argument("--report", type=Path)
    parser.add_argument("--contact-sheet", type=Path, default=Path("/tmp/catalog-contact-sheet.webp"))
    parser.add_argument("--profile", default=None, help="validate an adult profile build (underwear)")
    parser.add_argument("--adult-root", type=Path, default=ROOT / "assets" / "catalog" / "adult")
    args = parser.parse_args()
    if args.profile:
        return validate_adult(args.profile, args.adult_root)
    if args.root is None or args.report is None:
        parser.error("--root and --report are required for the public catalog")
    return validate(args.root, args.report, args.contact_sheet)


if __name__ == "__main__":
    raise SystemExit(main())
