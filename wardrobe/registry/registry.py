"""WS1. The wardrobe as one listing: every garment and ready look, typed, collected, filtered.

Built fresh from what exists — the template catalog (122 files), the shipped previews, the outfit
dictionary (143 ready looks) and the collections' design pictures — plus the admin's decisions
(wardrobe.registry.store). Nothing here is a second copy of a garment: a collection is a list of
ids, and one garment sits in as many collections as fit it.

Who sees what is decided here, on the server, for every request (WS2, the product's choice):

- **Adult** — lingerie, swimwear, erotic sets, the shows: everyone sees them, exactly as the rest of
  Forge already serves them (``adult: true`` marks them; the Studio calls the section Adult).
- **Private** — her naked body and its sexual states (open, gaped, cum, by position), marks and
  piercings, and anything an admin marks private: the admin only. For anyone else these items and
  their collections are not in the answer at all, never merely hidden by the page.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path

from wardrobe.registry import classify
from wardrobe.registry.classify import BY_ID, CATEGORIES, SECTIONS, base_name, primary_type

#: A template id → its preview URL, or None when it has no shipped picture.
PreviewFn = Callable[[object], "str | None"]


BODY_DETAIL = Path(__file__).resolve().parents[2] / "assets" / "body_detail"


def body_items(root: Path = BODY_DETAIL) -> list[dict]:
    """WS2. Forge's body detail as wardrobe items: skin presets, sexual states, extras (admin only).

    Read from the same files the painter reads (``presets.json``, ``states.json``,
    ``extras.json``), so an item here is exactly a value a bare-body job accepts.
    """
    out = []
    for name, key, prefix in (
        ("presets", "presets", "preset"),
        ("states", "states", "state"),
        ("extras", "extras", "extra"),
    ):
        try:
            data = json.loads((root / f"{name}.json").read_text(encoding="utf-8")).get(key, {})
        except (OSError, ValueError):
            continue  # a missing file means no such items, never a broken wardrobe
        for item_id, spec in data.items():
            out.append(
                {
                    "id": f"{prefix}:{item_id}",
                    "kind": "body",
                    "bodyKind": prefix,
                    "value": item_id,
                    "name": spec.get("label", item_id),
                    "description": spec.get("body") or "",
                    "type": "body",
                    "tags": [t for t in item_id.split("-") if t],
                    "adult": True,
                    "private": True,
                    "body": True,
                    "previewUrl": None,
                    "ready": True,
                }
            )
    out += bare_look_items(root)
    return out


def bare_look_items(root: Path = BODY_DETAIL) -> list[dict]:
    """AB1. After Dark · Bare: each named bare look as one private body item (``look:<id>``).

    It carries what a bare job needs (``jobOptions``) and what the look is in words, so the Studio
    can dress her in it and a client can say what her body shows. Private like every body item.
    """
    from wardrobe.registry import bare_looks

    data = bare_looks.load(root)
    try:
        states = json.loads((root / "states.json").read_text(encoding="utf-8")).get("states", {})
    except (OSError, ValueError):
        states = {}
    bodies = {k: v.get("body", "") for k, v in states.items()}
    chapters = {c["id"]: c for c in data["chapters"]}
    out = []
    for look_id, spec in data["looks"].items():
        out.append(
            {
                "id": f"look:{look_id}",
                "kind": "body",
                "bodyKind": "look",
                "value": look_id,
                "name": spec["label"],
                "description": bare_looks.describe(spec, bodies),
                "type": "body",
                "tags": ["after-dark", "bare", spec["chapter"], spec["state"]],
                "chapter": spec["chapter"],
                "chapterTitle": chapters.get(spec["chapter"], {}).get("title", spec["chapter"]),
                "preset": spec["preset"],
                "state": spec["state"],
                "extras": list(spec.get("extras", [])),
                "jobOptions": bare_looks.job_options(spec),
                "adult": True,
                "private": True,
                "body": True,
                "previewUrl": None,
                "ready": True,
            }
        )
    return out


def _body_match(pattern: str, item_id: str) -> bool:
    """WS3. A body pattern: a substring of the item id, or the exact id when it ends in ``$``."""
    return item_id == pattern[:-1] if pattern.endswith("$") else pattern in item_id


def _restricted(template) -> bool:
    from wardrobe.domain.garments import INTIMATE_CATEGORIES

    return template.category in INTIMATE_CATEGORIES or bool(template.requires_adult)


def garments(catalog, state: dict, preview: PreviewFn) -> list[dict]:
    """Every template as a garment record, rules first and the admin's decisions over them."""
    out = []
    decided = state.get("garments", {})
    for t in catalog.all():
        mine = decided.get(t.id, {})
        tags = sorted(set(t.tags) | set(mine.get("tags", [])))
        rule_type, reason = primary_type(t.id, t.category, set(tags))
        kind = mine.get("category") or rule_type
        body = bool(getattr(t, "is_body_mode", False))
        adult = _restricted(t) or body
        # WS2. Private (admin only) is the bare body and what an admin marks private; adult garments
        # are for everyone, as Forge has always served them.
        private = mine.get("visibility") == "private" if "visibility" in mine else body
        url = preview(t)
        out.append(
            {
                "id": t.id,
                "kind": "garment",
                "name": t.name,
                "engineCategory": t.category,
                "type": "body" if body else kind,
                "typeReason": "set by an admin" if mine.get("category") else reason,
                "tags": tags,
                "silhouette": t.silhouette,
                "hem": t.hem,
                "adult": adult,
                "private": private,
                "body": body,
                "previewUrl": url,
                "ready": url is not None,
                "needsReview": (not body) and not mine.get("reviewed") and (kind is None or not t.tags),
                "reviewed": bool(mine.get("reviewed")),
                "optIn": bool(getattr(t, "opt_in", False)),
            }
        )
    return out


def outfits(dictionary: dict, design_previews: dict[str, str]) -> list[dict]:
    """The outfit dictionary's ready looks: adult by its own rating or its group's, open to all."""
    group_private = {g["id"]: bool(g.get("private")) for g in dictionary.get("groups", [])}
    out = []
    for o in dictionary.get("outfits", []):
        out.append(
            {
                "id": o["id"],
                "kind": "outfit",
                "name": o.get("title") or o["id"],
                "type": "outfits",
                "group": o.get("group"),
                "tags": list(o.get("tags") or []),
                "garments": [g.get("template") for g in o.get("garments", []) if g.get("template")],
                "partial": list(o.get("partial") or []),
                "adult": o.get("rating") != "general" or group_private.get(o.get("group"), False),
                "private": False,
                "previewUrl": design_previews.get(o["id"]),
                "ready": True,
            }
        )
    return out


def _members(c: classify.Collection, items: list[dict], state: dict, favourites: list[str]) -> list[str]:
    g = [i for i in items if i["kind"] == "garment"]
    o = [i for i in items if i["kind"] == "outfit"]
    ids: list[str] = []
    if c.smart == "all":
        ids = [i["id"] for i in g if not i["body"]]
    elif c.smart == "looks-public":
        ids = [i["id"] for i in o if not i["adult"]]
    elif c.smart == "favourites":
        ids = list(favourites)
    elif c.smart == "ready":
        ids = [i["id"] for i in g if i["ready"] and not i["body"]]
    elif c.smart == "untested":
        ids = [i["id"] for i in g if not i["ready"] and not i["body"]]
    elif c.smart == "review":
        ids = [i["id"] for i in g if i["needsReview"]]
    elif c.smart == "partial":
        ids = [i["id"] for i in o if {"top", "bottom"} <= set(i["partial"])]
    elif c.smart == "bare":
        ids = [i["id"] for i in g if i["body"]]
    elif c.smart == "superseded":
        latest: dict[str, str] = {}
        for i in g:
            b = base_name(i["id"])
            if i["id"] > latest.get(b, ""):
                latest[b] = i["id"]
        ids = [i["id"] for i in g if base_name(i["id"]) in latest and latest[base_name(i["id"])] != i["id"]]
    elif c.smart == "recent":
        # Imports land here first (WS4); until there are any, the newest built atelier looks.
        ids = [i["id"] for i in o if i["group"] == "atelier"]
    # Rule membership (types, tags, hand-picked ids, groups, outfit tags).
    for i in g:
        if i["body"]:
            continue
        if i["type"] in c.types or i["id"] in c.garments or (c.tags and set(c.tags) & set(i["tags"])):
            ids.append(i["id"])
    for i in o:
        if i["group"] in c.groups or (c.outfit_tags and set(c.outfit_tags) & set(i["tags"])):
            ids.append(i["id"])
    if c.body:
        for i in items:
            if i["kind"] == "body" and any(_body_match(p, i["id"]) for p in c.body):
                ids.append(i["id"])
    seen, ordered = set(), []
    for x in ids:
        if x not in seen:
            seen.add(x)
            ordered.append(x)
    return ordered


def build(
    catalog,
    dictionary: dict,
    state: dict,
    *,
    admin: bool,
    preview: PreviewFn,
    design_previews: dict[str, str] | None = None,
) -> dict:
    """The wardrobe for one viewer: ``admin`` sees everything; anyone else never a private item."""
    items = garments(catalog, state, preview) + outfits(dictionary, design_previews or {}) + body_items()
    if not admin:
        # An adult garment's picture is served to an admin session only (/v1/catalog keeps that
        # rule): a guest gets the garment, not a link that would answer 403.
        for i in items:
            if i["kind"] == "garment" and i.get("adult") and i["previewUrl"]:
                i["previewUrl"] = None
    by_id = {i["id"]: i for i in items}
    favourites = [f for f in state.get("favourites", []) if f in by_id]
    decided = state.get("collections", {})

    defs = list(classify.ALL) + [
        classify.Collection(
            id=cid,
            title=c.get("title", cid),
            description=c.get("description", ""),
            section="private" if c.get("private") else "looks",
            private=bool(c.get("private")),
        )
        for cid, c in decided.items()
        if c.get("custom")
    ]
    raw: dict[str, list[str]] = {}
    for c in defs:
        mine = decided.get(c.id, {})
        ids = _members(c, items, state, favourites) + [x for x in mine.get("add", []) if x in by_id]
        removed = set(mine.get("remove", []))
        raw[c.id] = [x for x in dict.fromkeys(ids) if x not in removed]

    # Unassigned: garments in no curated collection. Unsorted private: private garments in no
    # private collection. Computed after the rest, from the same memberships.
    curated = {cid for cid in raw if not BY_ID.get(cid) or BY_ID[cid].smart in (None, "partial")}
    placed = {x for cid in curated for x in raw[cid]}
    raw["unassigned"] = [
        i["id"] for i in items if i["kind"] == "garment" and not i["body"] and i["id"] not in placed
    ]
    # A built-in collection's privacy is the product's; a custom one's is what the admin set.
    def is_private(cid: str) -> bool:
        return BY_ID[cid].private if cid in BY_ID else bool(decided.get(cid, {}).get("private", True))

    private_placed = {x for cid in curated if is_private(cid) for x in raw[cid]}
    raw["unsorted-private"] = [
        i["id"]
        for i in items
        if i["kind"] == "garment" and i["private"] and not i["body"] and i["id"] not in private_placed
    ]

    def visible(item_id: str) -> bool:
        return admin or not by_id[item_id]["private"]

    collections = []
    for c in defs:
        mine = decided.get(c.id, {})
        private = bool(mine.get("private", c.private))
        if private and not admin:
            continue
        archived = bool(mine.get("archived"))
        if archived and not admin:
            continue
        members = [x for x in raw[c.id] if visible(x)]
        cover = mine.get("cover") if mine.get("cover") in by_id and visible(mine.get("cover")) else None
        if cover is None:
            cover = next((x for x in members if by_id[x]["previewUrl"]), None)
        collections.append(
            {
                "id": c.id,
                "title": mine.get("title", c.title),
                "description": mine.get("description", c.description),
                "section": c.section,
                "private": private,
                "archived": archived,
                "smart": c.smart,
                "custom": bool(mine.get("custom")),
                "count": len(members),
                "cover": cover,
                "coverUrl": by_id[cover]["previewUrl"] if cover else None,
                "items": members,
            }
        )

    shown = [i for i in items if visible(i["id"])]
    membership: dict[str, list[str]] = {}
    for c in collections:
        if c["smart"] in ("all", "ready", "untested", "unassigned", "review", "recent", "favourites"):
            continue
        for x in c["items"]:
            membership.setdefault(x, []).append(c["id"])
    for i in shown:
        i["collections"] = membership.get(i["id"], [])
        i["favourite"] = i["id"] in favourites

    garment_list = [i for i in shown if i["kind"] == "garment"]
    categories = []
    for cid, title in CATEGORIES:
        count = len([i for i in shown if i["type"] == cid])
        categories.append({"id": cid, "title": title, "count": count})

    return {
        "sections": [{"id": s, "title": t} for s, t in SECTIONS if admin or not s.startswith("private")],
        "categories": categories,
        "collections": collections,
        "items": shown,
        "duplicates": list(classify.suspected_duplicates(garment_list)),
        "admin": admin,
    }


def dashboard(view: dict) -> dict:
    """The admin's counts, from an admin view (``build(..., admin=True)``)."""
    items = view["items"]
    g = [i for i in items if i["kind"] == "garment" and not i["body"]]
    o = [i for i in items if i["kind"] == "outfit"]
    by_id = {c["id"]: c for c in view["collections"]}
    return {
        "garments": len(g),
        "categorized": len([i for i in g if i["type"]]),
        "uncategorized": len([i for i in g if not i["type"]]),
        # Three tiers: general (anyone), adult (guests see it; the UI calls it "Adult"), and
        # private (admin only: bare bodies, painted states, finishes, marks).
        "general": len([i for i in g if not i["adult"] and not i["private"]]),
        "adult": len([i for i in g if i["adult"] and not i["private"]]),
        "private": len([i for i in g if i["private"]]),
        "withThumbnail": len([i for i in g if i["ready"]]),
        "missingThumbnails": len([i for i in g if not i["ready"]]),
        "needsFitTesting": by_id["needs-fit-testing"]["count"],
        "needsReview": by_id["needs-review"]["count"],
        "unassigned": by_id["unassigned"]["count"],
        "suspectedDuplicates": view["duplicates"],
        "recentlyImported": 0,
        "outfits": len(o),
        "adultOutfits": len([i for i in o if i["adult"]]),
        "privateOutfits": len([i for i in o if i["private"]]),
        "bodies": len([i for i in items if i.get("body")]),
        "bodyContent": {
            k: len([i for i in items if i["kind"] == "body" and i["id"].startswith(k + ":")])
            for k in ("preset", "state", "extra", "look")
        },
        "collections": {
            "public": len(
                [c for c in view["collections"] if not c["private"] and c.get("section") != "adult"]
            ),
            "adult": len([c for c in view["collections"] if c.get("section") == "adult"]),
            "private": len([c for c in view["collections"] if c["private"]]),
            "empty": [c["id"] for c in view["collections"] if c["count"] == 0],
        },
    }


__all__ = ["build", "dashboard", "garments", "outfits"]
