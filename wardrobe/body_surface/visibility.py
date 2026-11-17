"""CV1. May her clothing be hidden, for these exact bytes? Forge's answer, which the app only follows.

Every question the bare body state asks is asked here of the exact file the app has loaded (its
SHA-256), and one more: does a hide show a whole body (``clothing_structure.analyze``). The design
clearance is a person's review of these bytes, or — for a file that adds only clothing to a cleared
file — that file's clearance: a synthetic reference Forge rebuilt and verified by hash, or a library
file a person reviewed. "Adds only clothing" is checked surface by surface (``body_is_from``): what a
hide shows must be the cleared file's own body. Nothing about the person using the app is an input.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from wardrobe.body_surface.clothing_structure import analyze, body_is_from
from wardrobe.body_surface.eligibility import assess
from wardrobe.body_surface.gate import design_review

_REFERENCES: dict[str, bytes] = {}


def _synthetic_sources(reference_root) -> list[tuple[str, str, bytes]]:
    """(sha256, bodyId, bytes) of every registered synthetic reference this generator still reproduces."""
    try:
        data = json.loads((Path(reference_root) / "synthetic-references.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    out = []
    for sha, record in (data.get("references") or {}).items():
        if sha not in _REFERENCES:
            try:
                from wardrobe.anatomy.vrm import build_reference_vrm

                built = build_reference_vrm(record["bodyId"])
            except Exception:  # noqa: BLE001 - a body that cannot be rebuilt clears nothing
                continue
            if hashlib.sha256(built).hexdigest() != sha:
                continue  # the generator changed: the record no longer describes these bytes
            _REFERENCES[sha] = built
        out.append((sha, record["bodyId"], _REFERENCES[sha]))
    return out


def answer(data: bytes, *, settings, library=None) -> dict:
    from wardrobe.vrm.document import GltfDocument
    from wardrobe.vrm.inspect import inspect_document
    from wardrobe.vrm.measure import measure_body

    sha = hashlib.sha256(data).hexdigest()
    doc = GltfDocument.from_bytes(data)
    info = inspect_document(doc)
    entry = next((a for a in (library.available() if library else []) if a.sha256 == sha), None)
    roots = {"review_root": settings.body_surface_root_path,
             "reference_root": settings.wardrobe_calibration_root}
    declared = bool(entry and entry.depicts_adult)
    verdict = assess(terms=info.license, operator_enabled=settings.wardrobe_adult_body_surface,
                     depicts_adult=declared, private=True, source_sha256=sha, **roots)
    checks = {k: dict(v) for k, v in verdict.checks.items()}
    derived = None
    if not checks["design-clearance"]["passed"]:
        sources = [(s, f"synthetic reference {b}", d)
                   for s, b, d in _synthetic_sources(settings.wardrobe_calibration_root)]
        for avatar in (library.available() if library else []):
            review = design_review(settings.body_surface_root_path, avatar.sha256)
            if review and review.get("outcome") == "clearly-adult":
                sources.append((avatar.sha256, avatar.slug, Path(avatar.path).read_bytes()))
        for source_sha, label, source_bytes in sources:
            if source_sha != sha and body_is_from(doc, GltfDocument.from_bytes(source_bytes)):
                derived = {"kind": "derived", "from": source_sha, "source": label}
                checks["design-clearance"] = {"passed": True, "clearance": derived, "why": ""}
                if not declared:
                    # The cleared source's own declaration or review is what makes it adult; this
                    # file adds only clothing to it.
                    checks["adult-declaration"] = {"passed": True, "why": "", "from": label}
                break
    elif entry is None and not declared:
        # A file outside the library has no operator declaration; a person's clearly-adult review of
        # these exact bytes is the stronger answer to the same question.
        checks["adult-declaration"] = {"passed": True, "why": "", "from": "review of these bytes"}
    structure = analyze(doc, measure_body(doc, info))
    refused = next((k for k, c in checks.items() if not c["passed"]), None)
    if refused is None and structure["verdict"] != "separable-complete":
        refused = "clothing-structure"
    return {
        "sha256": sha, "slug": entry.slug if entry else None,
        "allowed": refused is None, "refusedBy": refused,
        "checks": {k: {"passed": c["passed"], "why": c.get("why", "")} for k, c in checks.items()},
        "clearance": derived or checks["design-clearance"].get("clearance"),
        "structure": structure,
        "hideMaterials": [h["material"] for h in structure["hideable"]] if refused is None else [],
    }


__all__ = ["answer"]
