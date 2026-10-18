"""AB. Independent collections: named sets of designs, each a complete outfit construction.

A collection lives in its own folder, ``assets/collections/<name>/collection.json``, and is
added beside everything that exists, never into it. Anime Beachwear is the first: twelve
original swimsuits, each a *design* that names its pieces exactly — the template, the words
the planner reads for colour and pattern, and the pattern-block fields that make it that
swimsuit and not the plain one (``lingerie``: halter straps, a string side, a cut-out; and
procedural options: ``hem``).

A job asks for one with the ``design`` block (``DesignRequest``)::

    {"prompt": "beach-noir-cutout", "design": {"collection": "anime-beachwear", "id": "beach-noir-cutout"}}

``expand`` turns it into ordinary layers before planning, one per piece, each with its
template named; ``apply`` hands each planned garment its design's construction
(``StylePlan.design``) once it is planned. Everything after — Base Body Prep, the fit, the
adult gate, the licence check, the fit report — is the pipeline's own, exactly as for a
typed prompt. A design grants nothing: a swimsuit is swimwear, rated and gated as swimwear.

Additive by construction: ``StylePlan.design`` is None for every garment no design names, and
enters neither a garment's id nor its metadata then (``providers/templates.py``), so every
existing look plans and builds byte for byte as before.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

from wardrobe.domain.looks import OutfitPlan, OutfitRequest

ROOT = Path(__file__).resolve().parents[2] / "assets" / "collections"
STATUSES = ("existing-template-proxy", "implemented", "visually-validated")


@lru_cache(maxsize=1)
def collections() -> dict[str, dict]:
    """Every collection on disk, by id, in folder order."""
    out: dict[str, dict] = {}
    for path in sorted(ROOT.glob("*/collection.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        data["_dir"] = str(path.parent)
        out[data["id"]] = data
    return out


def get(collection_id: str) -> dict | None:
    return collections().get(collection_id)


def design(collection_id: str, design_id: str) -> dict | None:
    collection = get(collection_id)
    if collection is None:
        return None
    return next((d for d in collection["designs"] if d["id"] == design_id), None)


def validate_all() -> list[str]:
    """Problems with the collections on disk, as sentences; empty when sound."""
    issues: list[str] = []
    for cid, collection in collections().items():
        ids = [d["id"] for d in collection["designs"]]
        if len(ids) != len(set(ids)):
            issues.append(f"{cid}: duplicate design ids")
        for d in collection["designs"]:
            where = f"{cid}/{d['id']}"
            if d.get("status") not in STATUSES:
                issues.append(f"{where}: status {d.get('status')!r} not one of {STATUSES}")
            if d.get("category") not in collection.get("categories", []):
                issues.append(f"{where}: category {d.get('category')!r} is not one of the collection's")
            if not d.get("pieces"):
                issues.append(f"{where}: no pieces")
    return issues


def expand(request: OutfitRequest) -> OutfitRequest:
    """The request with its design's pieces as layers; the request itself when it names none."""
    ask = request.design
    if ask is None:
        return request
    found = design(ask.collection, ask.id)
    if found is None:  # the model's validator refuses this before a job exists
        return request
    layers = []
    for piece in found["pieces"]:
        fields: dict = {"prompt": piece["prompt"], "templateId": piece["template"]}
        if ask.color:
            fields["color"] = ask.color
        if ask.finish:
            fields["finish"] = ask.finish
        layers.append(OutfitRequest.model_validate(fields))
    return request.model_copy(update={"layers": layers})


def apply(plan: OutfitPlan, request: OutfitRequest) -> OutfitPlan:
    """Each planned garment of a design given its piece's construction; ``plan`` when none is named."""
    ask = request.design
    found = design(ask.collection, ask.id) if ask is not None else None
    if found is None:
        return plan
    garments = list(plan.layers) if plan.layers else [plan]
    pieces = list(found["pieces"])
    for index, garment in enumerate(garments):
        piece = next((p for p in pieces if p["template"] == garment.template_id), None)
        if piece is None:
            continue
        pieces.remove(piece)
        construction = {"collection": ask.collection, "id": found["id"], "piece": piece["piece"]}
        construction.update({k: piece[k] for k in ("lingerie", "hem") if k in piece})
        garments[index] = garment.model_copy(
            update={"style": garment.style.model_copy(update={"design": construction}),
                    "set_id": f"{ask.collection}:{found['id']}"})
    note = f"design: {found['title']} ({ask.collection})"
    if plan.layers:
        update = {"layers": garments, "name": found["title"], "notes": [*plan.notes, note]}
        return plan.model_copy(update=update)
    return garments[0].model_copy(update={"name": found["title"], "notes": [*plan.notes, note]})


def public(collection: dict) -> dict:
    """What the API serves: the record without its folder."""
    return {k: v for k, v in collection.items() if not k.startswith("_")}


__all__ = ["ROOT", "STATUSES", "apply", "collections", "design", "expand", "get", "public", "validate_all"]
