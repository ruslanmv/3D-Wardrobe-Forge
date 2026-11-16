#!/usr/bin/env python3
"""RP1. What a human reviewer needs to review one avatar file, gathered; and nothing a reviewer decides.

    python tools/body_surface/review_packet.py --slug avatar-sample-a --out /tmp/review/avatar-sample-a
    python tools/body_surface/review_packet.py --file candidate.vrm --out /tmp/review/candidate \\
        [--sheets DIR]   # clothed reference pictures of this exact file, to list with their hashes

The bare body state (``body-bare-v1``, and a ``bare`` import) opens only for an exact file a
*person* has reviewed and found clearly adult in design: ``design-clearance`` in
``wardrobe.body_surface.eligibility``, recorded in ``assets/body_surface/adult-design-reviews.json``
under the SHA-256 of the file's bytes. That registry is empty, and has been since it was added,
partly because reviewing was never made a job someone could do: which file exactly, what hash goes
in the key, what the file's own terms say, what was looked at, where the answer is written.

This tool prepares that job. It writes ``packet.json`` and ``packet.md`` to ``--out``:

* the **exact file**: path, size, SHA-256 (the registry key), and whether it is the library's pin;
* what the **file says about itself**: VRM title, authors, version, and its licence terms as
  Forge reads them (the first eligibility question, the author's permission);
* what the **operator has declared** (``assets/library/policy.json``), labelled as a declaration;
* the file's **rig, expressions, face and hair** (the identity an import will be held to), and
  the **clothing it wears** as Forge detects it;
* the **five eligibility answers** for this file as the registries stand now, so the reviewer sees
  which of them their review would change and which are someone else's;
* the **clothed reference pictures** the review is made from, when ``--sheets`` names them
  (made with the companion app's ``tools/qa/look-turntable.mjs --focus body`` from this same
  file), each with its SHA-256, so the record can say what was looked at;
* a **blank review entry** in the registry's own shape, and where it goes.

What it does not do, on purpose:

* It **records no outcome**. ``outcome``, ``reviewer``, ``date`` and ``evidence`` are empty in the
  entry it prints, and an entry with any of them empty is not a review (``gate.design_review``).
* It **does not write the registry**, and nothing in Forge does: a review is added by the person
  who made it, in a commit under their name.
* It offers **no opinion** on the design, no score, no hint. The operator's declaration and the
  file's terms are reported as what they are; neither is a review, and neither is evidence of one.
* It renders nothing and removes nothing: the file is only read. Every picture a review is made
  from is of the character as its author dressed it.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from wardrobe.body_surface import body_state_import  # noqa: E402
from wardrobe.body_surface.eligibility import assess  # noqa: E402
from wardrobe.body_surface.gate import REVIEW_FIELDS, REVIEWS_SCHEMA  # noqa: E402
from wardrobe.config import Settings  # noqa: E402
from wardrobe.library import AvatarLibrary  # noqa: E402
from wardrobe.vrm.document import GltfDocument  # noqa: E402
from wardrobe.vrm.garment_inventory import garment_inventory  # noqa: E402
from wardrobe.vrm.inspect import inspect_document  # noqa: E402

REGISTRY = "assets/body_surface/adult-design-reviews.json"
#: The views a clothed reference sheet holds (the turntable tool's own names).
VIEWS = ("front", "left", "back", "right")
TURNTABLE = "companion app: node tools/qa/look-turntable.mjs --vrm <this file> --focus body --out <dir>"


def _sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _outside(out: Path) -> Path:
    out = out.resolve()
    if out == ROOT or ROOT in out.parents:
        raise SystemExit(f"{out} is inside the repository; a review packet is written outside it")
    return out


def sheets(folder: Path | None) -> list[dict]:
    """The pictures in ``folder``, each with its hash. Listed, never opened here."""
    if folder is None:
        return []
    found = sorted(p for p in folder.iterdir() if p.suffix.lower() in (".png", ".jpg", ".jpeg", ".webp"))
    return [
        {
            "file": p.name,
            "bytes": p.stat().st_size,
            "sha256": _sha(p),
            "view": next((v for v in VIEWS if v in p.stem.lower()), None),
        }
        for p in found
    ]


def packet(
    path: Path, *, slug: str | None, library: AvatarLibrary, settings: Settings, sheet_dir: Path | None = None
) -> dict:
    data = path.read_bytes()
    digest = hashlib.sha256(data).hexdigest()
    document = GltfDocument.from_bytes(data)
    info = inspect_document(document)
    entry = library.get(slug) if slug else None
    declared = bool(entry is not None and entry.depicts_adult)
    head = info.humanoid_bones.get("head")
    identity = body_state_import.identity_primitives(document, head)
    worn = garment_inventory(document)
    answers = assess(
        terms=info.license,
        operator_enabled=settings.wardrobe_adult_body_surface,
        depicts_adult=declared,
        private=True,
        source_sha256=digest,
        review_root=settings.body_surface_root_path,
        reference_root=settings.wardrobe_calibration_root,
    )
    pictures = sheets(sheet_dir)
    return {
        "schema": "wardrobe.bodySurface.reviewPacket.v1",
        "preparedAt": datetime.now(UTC).replace(microsecond=0).isoformat(),
        "file": {
            "path": str(path),
            "bytes": len(data),
            "sha256": digest,
            "librarySlug": slug,
            "libraryPin": entry.sha256 if entry is not None else None,
            "matchesLibraryPin": bool(entry is not None and entry.sha256 == digest),
        },
        "whatTheFileSays": {
            "spec": str(info.spec),
            "title": info.title,
            "version": getattr(info, "version", None),
            "licence": info.license.to_dict(),
        },
        "operatorDeclaration": {
            "depictsAdult": declared,
            "source": "assets/library/policy.json" if entry is not None else None,
            "note": "A declaration is the operator's statement about a character. It is not a review "
            "and is not evidence for one.",
        },
        "identity": {
            "humanoidBones": len(info.humanoid_bones),
            "expressions": sorted(info.expressions) if hasattr(info, "expressions") else None,
            "faceAndHairPrimitives": len(identity),
            "note": "An imported body state must keep every one of these: same bone nodes within 1 mm, "
            "every expression, face and hair vertex for vertex within 0.1 mm "
            "(wardrobe.body_surface.body_state_import).",
        },
        "clothingAsAuthored": sorted(
            {f"{g.slot}{' (dress length)' if g.dress_length else ''}" for g in worn}
        ),
        "eligibilityNow": {
            "allowed": answers.allowed,
            "refusedBy": answers.refused_by,
            "checks": {
                name: {"passed": check["passed"], "why": check.get("why", "")}
                for name, check in answers.checks.items()
            },
            "note": "As the registries stand. design-clearance is the one a review answers; "
            "author-permission is the file's, operator-switch the deployment's, "
            "adult-declaration the operator's, private-session the job's.",
        },
        "referencePictures": {
            "made": TURNTABLE,
            "views": list(VIEWS),
            "files": pictures,
            "note": "Clothed, as authored. Listed with their hashes so a review can name what was looked at."
            if pictures
            else "None listed (--sheets). A review should name the pictures it was made from.",
        },
        "reviewEntry": {
            "registry": REGISTRY,
            "schema": REVIEWS_SCHEMA,
            "key": digest,
            "entry": dict.fromkeys(REVIEW_FIELDS, ""),
            "requiredFields": list(REVIEW_FIELDS),
            "rule": "A person who looked at this exact file fills every field and commits the entry "
            "themselves. outcome is 'clearly-adult' only if that is their finding; any other "
            "finding is not entered, and the file stays closed. An entry with an empty field is "
            "not a review. Any change to the file changes its SHA-256 and voids the entry.",
        },
    }


def markdown(p: dict) -> str:
    file, says, now, entry = p["file"], p["whatTheFileSays"], p["eligibilityNow"], p["reviewEntry"]
    lines = [
        "# Adult-design review packet",
        "",
        f"Prepared {p['preparedAt']} by `tools/body_surface/review_packet.py`. This packet records no "
        "finding. The determination is the reviewer's.",
        "",
        "## The exact file",
        "",
        f"- Path: `{file['path']}`",
        f"- Size: {file['bytes']} bytes",
        f"- SHA-256 (the registry key): `{file['sha256']}`",
        f"- Library avatar: `{file['librarySlug']}`, pin "
        f"{'matches' if file['matchesLibraryPin'] else '**does not match**'}"
        if file["librarySlug"]
        else "- Not a library avatar",
        "",
        "## What the file says about itself",
        "",
        f"- {says['spec']}, title `{says['title']}`",
        f"- Licence terms as Forge reads them: `{json.dumps(says['licence'], sort_keys=True)}`",
        "",
        "## What the operator has declared",
        "",
        f"- depictsAdult: {p['operatorDeclaration']['depictsAdult']}. {p['operatorDeclaration']['note']}",
        "",
        "## Identity an import is held to",
        "",
        f"- {p['identity']['humanoidBones']} humanoid bones, "
        f"{len(p['identity']['expressions'] or [])} expressions, "
        f"{p['identity']['faceAndHairPrimitives']} face and hair primitives. {p['identity']['note']}",
        f"- Clothing as authored: {', '.join(p['clothingAsAuthored']) or 'none detected'}",
        "",
        "## Eligibility as the registries stand",
        "",
        "| Question | Answer | Why not |",
        "|---|---|---|",
        *[f"| {name} | {'yes' if c['passed'] else 'no'} | {c['why']} |" for name, c in now["checks"].items()],
        "",
        now["note"],
        "",
        "## Reference pictures (clothed, as authored)",
        "",
        f"Made with: `{p['referencePictures']['made']}`",
        "",
        *(
            [
                f"- `{f['file']}` ({f['view'] or 'view not named'}), {f['bytes']} bytes, "
                f"sha256 `{f['sha256']}`"
                for f in p["referencePictures"]["files"]
            ]
            or [p["referencePictures"]["note"]]
        ),
        "",
        "## The review entry (blank)",
        "",
        f"Registry: `{entry['registry']}`, under `reviews`, key `{entry['key']}`:",
        "",
        "```json",
        json.dumps({entry["key"]: entry["entry"]}, indent=1),
        "```",
        "",
        entry["rule"],
        "",
    ]
    return "\n".join(lines)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--slug", help="a library avatar")
    parser.add_argument("--file", type=Path, help="any VRM file (a candidate that is not in the library)")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--sheets", type=Path, default=None, help="folder of clothed reference pictures")
    args = parser.parse_args(argv)
    if bool(args.slug) == bool(args.file):
        raise SystemExit("name a library avatar (--slug) or a file (--file), one of them")
    settings = Settings(_env_file=None)
    library = AvatarLibrary.from_directory(ROOT / "assets" / "library")
    if args.slug:
        entry = library.get(args.slug)
        if entry is None or entry.path is None or not Path(entry.path).is_file():
            raise SystemExit(f"{args.slug} is not in the library here (make library)")
        path = Path(entry.path)
    else:
        path = args.file
    out = _outside(args.out)
    out.mkdir(parents=True, exist_ok=True)
    result = packet(path, slug=args.slug, library=library, settings=settings, sheet_dir=args.sheets)
    (out / "packet.json").write_text(json.dumps(result, indent=1) + "\n")
    (out / "packet.md").write_text(markdown(result))
    print(f"{result['file']['sha256']}  {path.name}: packet written to {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
