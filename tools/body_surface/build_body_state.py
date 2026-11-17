#!/usr/bin/env python3
"""CG5. Build a character's bare body-state file from her library source, with no artist.

    python tools/body_surface/build_body_state.py --slug fem-vroid --out <private dir>
    python tools/body_surface/build_body_state.py --all --out <private dir> [--json report.json]

``docs/qa/BODY_FIX_PLAYBOOK.md`` sent four characters (Rinna, VRoid Female, VRoid Male,
AvatarSample_O) to a 3D artist for two to three weeks: paint skin over the clothing on the body
texture by hand (Route A), and for O rebuild the chest band her export deleted (Route C). Forge
already does both, automatically, inside a bare look: ``skin_restore.restore_skin`` repaints the
painted-on clothing from her own skin (the readiness report records it ``restoration-completed``
for every one of these files), and BR1's ``body_completion.complete_body`` fills a deleted band
with BC1's featureless proxy patch, as a separate mesh tagged ``bodyProxy``. What was missing
was only the step from "a look Forge builds on request" to "a file the body-state import takes".
This is that step: the same calls, in the same order as ``bare_body.prepare``, written to disk.

Measured 2026-11-17 on the four exact library files: every output passes all nine structural
checks of ``body_state_import.check`` (sha256, source binding, VRM, humanoid, rig, expressions,
metadata, face and hair, body state: closed in all six bands, no clothing left). The only
refusals left are the ones meant to need a person.

What this does **not** do, and must never be made to do:

* review anything. Every output is a new exact file; the import still needs a ``clearly-adult``
  review of the source and of these bytes (Studio, Character review), recorded by a person;
* attest rights. The import's licence and ``rightsAttested`` are the operator's statement;
* turn on the operator's switch (``WARDROBE_ADULT_BODY_SURFACE``). The pre-flight run here
  reports it as it is;
* hide that O's chest is reconstructed: the file says so (``reconstructed``,
  ``reconstruction: bc1-proxy``, the regions), as a BR1 look does, so a reviewer can tell.

The outputs are private files, never committed: they go to ``--out`` and to the Studio import.
Building is deterministic for a given source, so a rebuilt file keeps its hash and its review.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools" / "body_surface"))

import asset_spec  # noqa: E402

from wardrobe.config import Settings  # noqa: E402
from wardrobe.library import AvatarLibrary  # noqa: E402
from wardrobe.pipeline.bare_body import _complete_if_asked  # noqa: E402
from wardrobe.vrm.document import GltfDocument  # noqa: E402
from wardrobe.vrm.garment_inventory import build_strip_plan, garment_inventory, remove_garments  # noqa: E402
from wardrobe.vrm.inspect import inspect_document  # noqa: E402
from wardrobe.vrm.measure import measure_body  # noqa: E402
from wardrobe.vrm.skin_restore import restore_skin  # noqa: E402

#: The four the playbook named: clothing painted on (three) or a band deleted (O).
FOUR = ("vroid-rinna", "fem-vroid", "masc-vroid", "vroid-avatar-sample-o")


def build_bare(document: GltfDocument) -> dict:
    """Complete (only where a band is missing), take every garment off, restore painted skin.

    The order is ``bare_body.prepare``'s: the BC1 patch is shaped from the garments that covered
    the hole, so it is made before they are removed. Completion is asked for here because this is
    the operator's own tool, run on purpose; it is a no-op on a closed body (``applied`` false)."""
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


def build_one(slug: str, library: AvatarLibrary, settings: Settings, out: Path) -> dict:
    source = asset_spec._source(library, slug)
    document = GltfDocument.from_bytes(source.read_bytes())
    built = build_bare(document)
    data = document.to_bytes()
    sha = hashlib.sha256(data).hexdigest()
    target = out / f"{slug}-bare.vrm"
    target.write_bytes(data)
    verdict = asset_spec.preflight(target, source, slug, library, settings, state="bare", declared_sha256=sha)
    print(asset_spec.preflight_text(verdict), end="")
    return {"slug": slug, "file": str(target), "sha256": sha,
            "sourceSha256": verdict["sourceSha256"], **built,
            "structurallyAccepted": verdict["structurallyAccepted"], "accepted": verdict["accepted"],
            "reason": verdict["reason"]}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--slug", action="append", help="repeatable")
    parser.add_argument("--all", action="store_true", help=f"the four: {', '.join(FOUR)}")
    parser.add_argument("--out", type=Path, required=True, help="a private directory (never the repository)")
    parser.add_argument("--json", type=Path, default=None)
    args = parser.parse_args(argv)
    slugs = list(FOUR) if args.all else (args.slug or [])
    if not slugs:
        raise SystemExit("name --slug <slug> or --all")
    settings = Settings()
    library = AvatarLibrary.from_directory(settings.wardrobe_library_root)
    args.out.mkdir(parents=True, exist_ok=True)
    results = []
    for slug in slugs:
        print(f"== {slug}")
        try:
            results.append(build_one(slug, library, settings, args.out))
        except Exception as error:  # one character's failure must not hide the others' results
            print(f"  not built: {type(error).__name__}: {error}")
            results.append({"slug": slug, "structurallyAccepted": False, "error": str(error)})
        print()
    print("Summary (structure is the file; import still needs the reviews and the operator's switch):")
    for r in results:
        print(f"  {r['slug']:<24} {'structure ok' if r['structurallyAccepted'] else 'NOT OK':<13} "
              f"{r.get('sha256', '-')}")
    if args.json:
        args.json.write_text(json.dumps(results, indent=2) + "\n", encoding="utf-8")
    return 0 if all(r["structurallyAccepted"] for r in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
