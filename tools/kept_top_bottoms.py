#!/usr/bin/env python3
"""KL1. Which cached looks still have the jeans hip split, and the commands that rebuild only them.

KL1 changed how a bottom is fitted under a top she keeps, without bumping ``PIPELINE_VERSION``
(that would make all ~1900 cached looks misses and drop the historic keys). So the looks built
before KL1 are still served as they were. This tool names exactly the ones KL1 changes:

* a library character whose own file has a ``tops`` slot (her top stays on under new bottoms);
* a listed, public, fresh look of hers whose template is in ``UNDER_TOP_CATEGORIES``
  (trousers, shorts, skirt) — a one-template look; an outfit of several garments with a top
  replaces her top and is not affected;
* built before KL1: its fit report has no ``keptTopTuck`` (a look built with KL1 has one).

It reads only. It prints the pairs and one ``tools/prebuild.py`` command per character, for a
fresh local Forge with KL1, followed by ``tools/publish_prebuilt.py --overwrite``. That replaces
exactly those entries and list items under their unchanged keys; nothing else is rebuilt and no
other key moves.

    python tools/kept_top_bottoms.py --lists <dir with prebuilt/wardrobes/*.json> [--entries <dir>]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from wardrobe.config import get_settings  # noqa: E402
from wardrobe.domain.garments import TemplateCatalog  # noqa: E402
from wardrobe.geometry.kept_layers import OVER_SLOTS, UNDER_TOP_CATEGORIES  # noqa: E402
from wardrobe.library import AvatarLibrary  # noqa: E402
from wardrobe.vrm.document import GltfDocument  # noqa: E402
from wardrobe.vrm.garment_inventory import garment_inventory  # noqa: E402


def keeps_a_top(path: Path) -> bool:
    return any(g.slot in OVER_SLOTS for g in garment_inventory(GltfDocument.from_path(path)))


def built_before_kl1(entries: Path | None, key: str | None) -> bool | None:
    """True/False from the stored record's fit report; None when there is no entry to read."""
    if entries is None or not key:
        return None
    path = entries / "prebuilt" / f"{key}.json"
    try:
        record = json.loads(path.read_text(encoding="utf-8"))["record"]
    except (OSError, ValueError, KeyError):
        return None
    return "keptTopTuck" not in (record.get("fitReport") or {})


def affected(library: AvatarLibrary, catalog: TemplateCatalog, lists: Path,
             entries: Path | None) -> list[dict]:
    under = {t.id for t in catalog.all() if t.category in UNDER_TOP_CATEGORIES and not t.is_body_mode}
    out = []
    for avatar in library.available():
        if not keeps_a_top(avatar.path):
            continue
        listed = lists / "prebuilt" / "wardrobes" / f"{avatar.slug}.json"
        if not listed.is_file():
            continue
        for item in json.loads(listed.read_text(encoding="utf-8")).get("looks", []):
            if item.get("private") or item.get("plan") or item.get("templateId") not in under:
                continue
            before = built_before_kl1(entries, item.get("key"))
            if before is False:
                continue  # already built with KL1
            out.append({"slug": avatar.slug, "templateId": item["templateId"], "color": item.get("color"),
                        "lookId": item.get("lookId"), "key": item.get("key"),
                        "evidence": "fit report has no keptTopTuck" if before else "no entry read"})
    return out


def main(argv=None) -> int:
    raw = argparse.RawDescriptionHelpFormatter
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=raw)
    parser.add_argument("--lists", type=Path, required=True, help="Root holding prebuilt/wardrobes/*.json")
    parser.add_argument("--entries", type=Path, help="Root holding prebuilt/<key>.json (to skip KL1 builds)")
    parser.add_argument("--forge", default="http://127.0.0.1:8090")
    parser.add_argument("--json", action="store_true")
    opts = parser.parse_args(argv)
    settings = get_settings()
    library = AvatarLibrary.from_directory(settings.wardrobe_library_root)
    catalog = TemplateCatalog.from_directory(settings.wardrobe_template_root)
    pairs = affected(library, catalog, opts.lists, opts.entries)
    if opts.json:
        print(json.dumps(pairs, indent=2))
        return 0
    for p in pairs:
        print(f"{p['slug']:24} {p['templateId']:28} {str(p['color']):10} {p['lookId']}  ({p['evidence']})")
    by_slug: dict[str, set[str]] = {}
    for p in pairs:
        by_slug.setdefault(p["slug"], set()).add(p["templateId"])
    print(f"\n{len(pairs)} looks on {len(by_slug)} characters. Rebuild only these, on a fresh local Forge:")
    for slug, templates in sorted(by_slug.items()):
        for template in sorted(templates):
            print(f"python tools/prebuild.py --forge {opts.forge} --slugs {slug} --only {template}")
    print("python tools/publish_prebuilt.py --root <the local Forge's storage> --repo <dataset> --overwrite")
    return 0


if __name__ == "__main__":
    sys.exit(main())
