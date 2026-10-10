"""BA6. A tattoo is hers, not the outfit's — but it exists as geometry only while it can be seen.

Every look a tattoo was made on records it in the root's ``extras.wardrobeForge.bodyArt``:
the request (design, placement, transforms) and its ``state``. A later job built on that
look inherits the recipes, because the engines rewrite the root's extras from scratch
(``tag_derived``) and a recipe left behind there would be a tattoo forgotten the first time
she changed her top. Each inherited recipe is then decided on the *new* outfit like any
request, with one difference (docs/BODY_ART_PLAN.md §3 Lifecycle):

* still visible, decal still there → **kept as it is** (nothing is rebuilt);
* still visible, decal missing (an engine that did not carry it) → re-applied;
* now covered → the decal is **dropped** (I3, I6) and the recipe stays, ``state: "covered"``;
* covered before, visible again → **re-applied** from the recipe, same settings.

A request at the same placement replaces the recipe once it is drawn; ``bodyArtRemove`` deletes it. Only
recipes that were once on her skin travel: a tattoo that was asked for and refused
(``"not-applied"``) is not quietly added to some later outfit that happens to show the spot.

Reading the recipes parses the source's JSON chunk only — a few kilobytes, never the
buffer — so a job on a look without any (every look before BA4, every look that never had
a tattoo) pays one ``json.loads`` and goes on exactly as before (I1).
"""

from __future__ import annotations

import json
import logging
import struct

from pydantic import ValidationError

from wardrobe.body_art.contract import BodyArtRequest
from wardrobe.vrm.document import GltfDocument

logger = logging.getLogger(__name__)

#: Recipe states that travel to the next look.
INHERITED_STATES = ("applied", "covered", "held")

_HEADER = struct.Struct("<4sII")
_CHUNK = struct.Struct("<I4s")
_REQUEST_KEYS = frozenset((field.alias or name) for name, field in BodyArtRequest.model_fields.items())


def json_chunk(data: bytes | None) -> dict | None:
    """The glTF JSON of a GLB, without touching its binary chunk. None if it is not one."""
    if not data or len(data) < _HEADER.size + _CHUNK.size:
        return None
    magic, _version, _length = _HEADER.unpack_from(data, 0)
    length, kind = _CHUNK.unpack_from(data, _HEADER.size)
    if magic != b"glTF" or kind != b"JSON":
        return None
    start = _HEADER.size + _CHUNK.size
    try:
        gltf = json.loads(data[start : start + length])
    except ValueError:
        return None
    return gltf if isinstance(gltf, dict) else None


def forge_tag(gltf: dict | None) -> dict | None:
    """The root's ``extras.wardrobeForge`` — present on every Forge look — or None."""
    extras = (gltf or {}).get("extras")
    tag = extras.get("wardrobeForge") if isinstance(extras, dict) else None
    return tag if isinstance(tag, dict) else None


def recipes(gltf: dict | None) -> list[BodyArtRequest]:
    """The tattoos a look carries for the next one: once on her skin, whether shown now or not."""
    return [recipe for recipe, _state in recipe_states(gltf)]


def recipe_states(gltf: dict | None) -> list[tuple[BodyArtRequest, str]]:
    """Each carried recipe with its state on this look (``applied``, ``covered`` or ``held``)."""
    tag = forge_tag(gltf)
    entries = tag.get("bodyArt") if tag else None
    found: list[tuple[BodyArtRequest, str]] = []
    for entry in entries if isinstance(entries, list) else []:
        if not isinstance(entry, dict):
            continue
        # BA4 looks wrote no state; on those, "applied" says the same thing.
        state = entry.get("state") or ("applied" if entry.get("applied") else "not-applied")
        if state not in INHERITED_STATES:
            continue
        try:
            fields = {k: v for k, v in entry.items() if k in _REQUEST_KEYS}
            found.append((BodyArtRequest.model_validate(fields), state))
        except ValidationError as exc:  # a recipe this version cannot read is left, not guessed
            logger.warning("skipping an unreadable body-art recipe: %s", exc)
    return found


def inherited(source: bytes | None, *, remove: list[str]) -> list[BodyArtRequest]:
    """The source look's recipes this job carries, minus the ones it removes.

    One asked for again at the same placement is *not* dropped here: it gives way only if
    the new one is actually drawn (``decorate.decide``), so a replacement that is refused
    leaves her old tattoo, and its recipe, where they were.
    """
    taken = set(remove)
    seen: set[str] = set()
    carried = []
    for recipe in recipes(json_chunk(source)):
        if recipe.placement in taken or recipe.placement in seen:
            continue
        seen.add(recipe.placement)
        carried.append(recipe)
    return carried


def live_placements(document: GltfDocument) -> set[str]:
    """Placements with a Forge decal drawn on this document now."""
    live = set()
    for node in document.nodes:
        extras = node.get("extras") if isinstance(node.get("extras"), dict) else {}
        tag = extras.get("wardrobeForge") if isinstance(extras.get("wardrobeForge"), dict) else {}
        if tag.get("kind") == "bodyArt" and "mesh" in node and tag.get("placement"):
            live.add(str(tag["placement"]))
    return live


__all__ = [
    "INHERITED_STATES",
    "forge_tag",
    "inherited",
    "json_chunk",
    "live_placements",
    "recipe_states",
    "recipes",
]
