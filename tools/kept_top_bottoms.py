#!/usr/bin/env python3
"""KL1. Which cached looks still have the jeans hip split, and the commands that rebuild only them.

KL1 changed how a bottom is fitted under a top she keeps, without bumping ``PIPELINE_VERSION``
(that would make all ~1900 cached looks misses and drop the historic keys). So the looks built
before KL1 are still served as they were. This tool names exactly the ones KL1 changes:

* a library character whose own file has a ``tops`` slot (her top stays on under new bottoms);
* a listed, public, fresh look of hers whose template is in ``UNDER_TOP_CATEGORIES``
  (trousers, shorts, skirt) — a one-template look; an outfit of several garments with a top
  replaces her top and is not affected;
* built before the current rules: its fit report has no ``keptTopTuck`` (before KL1), or one
  without ``version`` or with a lower one than ``kept_layers.VERSION`` (KL1 left the front-hem
  band; KL3 is version 3).

KL2/KL3 add one more kind, on any character: a listed look whose stored report says the old
pass *moved* something (``keptTopTuck.moved > 0``, version below the current one). That is how
a waspie or a guêpière layered over a Forge bralette is found: KL1 took the bralette for a kept
top and pulled them into her (KL2), on avatars with no top of their own. Private looks are
listed too (``private: true``); rebuilding those needs ``tools/prebuild.py --admin-token-file``.

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
from wardrobe.geometry.kept_layers import OVER_SLOTS, UNDER_TOP_CATEGORIES, VERSION  # noqa: E402
from wardrobe.library import AvatarLibrary  # noqa: E402
from wardrobe.vrm.document import GltfDocument  # noqa: E402
from wardrobe.vrm.garment_inventory import garment_inventory  # noqa: E402


def keeps_a_top(path: Path) -> bool:
    return any(g.slot in OVER_SLOTS for g in garment_inventory(GltfDocument.from_path(path)))


def stored_tuck(entries: Path | None, key: str | None) -> tuple[bool, dict | None]:
    """(entry read, its ``keptTopTuck`` or None). No entry to read: (False, None)."""
    if entries is None or not key:
        return False, None
    path = entries / "prebuilt" / f"{key}.json"
    try:
        record = json.loads(path.read_text(encoding="utf-8"))["record"]
    except (OSError, ValueError, KeyError):
        return False, None
    tuck = (record.get("fitReport") or {}).get("keptTopTuck")
    return True, tuck if isinstance(tuck, dict) else None


def built_before_kl1(entries: Path | None, key: str | None) -> bool | None:
    """True/False from the stored record's fit report; None when there is no entry to read."""
    read, tuck = stored_tuck(entries, key)
    return None if not read else tuck is None


def stale(entries: Path | None, key: str | None) -> tuple[bool | None, str]:
    """Whether a look that the pass applies to was built by older rules, and how that is known.

    None: no entry to read, so it cannot be told (listed, as before KL3: rebuilding a look that
    was current costs one build; missing one that was not leaves the defect in the cache).
    """
    read, tuck = stored_tuck(entries, key)
    if not read:
        return None, "no entry read"
    if tuck is None:
        return True, "fit report has no keptTopTuck (built before KL1)"
    version = tuck.get("version") or 1
    if version < VERSION:
        return True, f"keptTopTuck version {version}, current is {VERSION}"
    return False, ""


def affected(library: AvatarLibrary, catalog: TemplateCatalog, lists: Path,
             entries: Path | None, *, include_private: bool = True) -> list[dict]:
    under = {t.id for t in catalog.all() if t.category in UNDER_TOP_CATEGORIES and not t.is_body_mode}
    out = []
    for avatar in library.available():
        listed = lists / "prebuilt" / "wardrobes" / f"{avatar.slug}.json"
        if not listed.is_file():
            continue
        keeps = keeps_a_top(avatar.path)
        for item in json.loads(listed.read_text(encoding="utf-8")).get("looks", []):
            if item.get("private") and not include_private:
                continue
            if item.get("origin") == "operator-import":
                continue  # an imported file is not built by Forge: nothing to rebuild
            evidence = None
            if keeps and not item.get("plan") and item.get("templateId") in under:
                # Her own top stays on under this bottom: every such look is fitted by the pass.
                old, why = stale(entries, item.get("key"))
                evidence = why if old is not False else None
            if evidence is None:
                # Anything else the old pass moved: a piece tucked under a foundation (KL2), an
                # outfit of several garments over a kept top.
                read, tuck = stored_tuck(entries, item.get("key"))
                version = (tuck or {}).get("version") or 1
                if read and tuck and version < VERSION and int(tuck.get("moved") or 0) > 0:
                    evidence = f"keptTopTuck version {version} moved {tuck['moved']} vertices"
            if evidence is None:
                continue
            out.append({"slug": avatar.slug, "templateId": item.get("templateId"), "color": item.get("color"),
                        "lookId": item.get("lookId"), "key": item.get("key"),
                        "private": bool(item.get("private")), "plan": item.get("plan"), "evidence": evidence})
    return out


def main(argv=None) -> int:
    raw = argparse.RawDescriptionHelpFormatter
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=raw)
    parser.add_argument("--lists", type=Path, required=True, help="Root holding prebuilt/wardrobes/*.json")
    parser.add_argument("--entries", type=Path, help="Root holding prebuilt/<key>.json (to skip KL1 builds)")
    parser.add_argument("--forge", default="http://127.0.0.1:8090")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--public-only", action="store_true", help="Leave private looks out of the list")
    opts = parser.parse_args(argv)
    settings = get_settings()
    library = AvatarLibrary.from_directory(settings.wardrobe_library_root)
    catalog = TemplateCatalog.from_directory(settings.wardrobe_template_root)
    pairs = affected(library, catalog, opts.lists, opts.entries, include_private=not opts.public_only)
    if opts.json:
        print(json.dumps(pairs, indent=2))
        return 0
    for p in pairs:
        mark = " private" if p["private"] else ""
        print(f"{p['slug']:24} {str(p['templateId']):28} {str(p['color']):10} {p['lookId']}{mark}  "
              f"({p['evidence']})")
    by_slug: dict[tuple[str, bool], set[str]] = {}
    outfits = 0
    for p in pairs:
        if p["templateId"] and not p["plan"]:
            by_slug.setdefault((p["slug"], p["private"]), set()).add(p["templateId"])
        else:
            outfits += 1
    print(f"\n{len(pairs)} looks on {len({p['slug'] for p in pairs})} characters. Rebuild only these, on a "
          "fresh local Forge:")
    for (slug, private), templates in sorted(by_slug.items()):
        token = " --admin-token-file <file>" if private else ""
        for template in sorted(templates):
            print(f"python tools/prebuild.py --forge {opts.forge} --slugs {slug} --only {template}{token}")
    if outfits:
        print(f"# {outfits} of them are outfits of several garments: rebuild those from their own recipes "
              "(tools/prebuild.py --outfits), the keys above name them")
    print("python tools/publish_prebuilt.py --root <the local Forge's storage> --repo <dataset> --overwrite")
    return 0


if __name__ == "__main__":
    sys.exit(main())
