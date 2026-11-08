"""Separate a geometry fingerprint from the cloth payload it must not absorb.

A fitted garment's positions, indices, joints, weights, images, and materials
are the regression. ``extras.wardrobeForge.clothAsset`` and the buffer view it
points at are metadata. A geometry check strips those and leaves everything else.
"""

from __future__ import annotations

import copy

CLOTH_EXTRA_KEY = "clothAsset"


def cloth_buffer_views(gltf: dict) -> list[int]:
    """Buffer views named by a cloth asset extra, including LOD payloads."""
    found: list[int] = []

    def walk(node) -> None:
        if isinstance(node, dict):
            asset = node.get(CLOTH_EXTRA_KEY)
            if isinstance(asset, dict):
                if "bufferView" in asset:
                    found.append(int(asset["bufferView"]))
                for lod in asset.get("lods") or []:
                    if isinstance(lod, dict) and "bufferView" in lod:
                        found.append(int(lod["bufferView"]))
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)

    walk(gltf)
    return found


def strip_cloth_payload(gltf: dict) -> tuple[dict, int | None]:
    """Copy ``gltf`` without cloth extras and without a trailing cloth buffer.

    The integer is the binary prefix that still belongs to the garment, or
    ``None`` when there is no cloth payload. Views after the first cloth view
    must all be cloth views. Anything else is left in place so a real geometry
    change still fails the fingerprint.
    """
    cloned = copy.deepcopy(gltf)
    views = cloth_buffer_views(cloned)

    def drop(node) -> None:
        if isinstance(node, dict):
            node.pop(CLOTH_EXTRA_KEY, None)
            for value in node.values():
                drop(value)
        elif isinstance(node, list):
            for value in node:
                drop(value)

    drop(cloned)
    if not views:
        return cloned, None
    buffer_views = cloned.get("bufferViews") or []
    first = min(views)
    cloth = set(views)
    if first >= len(buffer_views) or any(index not in cloth for index in range(first, len(buffer_views))):
        return cloned, None
    start = int(buffer_views[first].get("byteOffset", 0))
    cloned["bufferViews"] = buffer_views[:first]
    buffers = cloned.get("buffers") or []
    if buffers:
        buffers[0]["byteLength"] = start
    return cloned, start


def geometry_forge_tag(forge: dict) -> dict:
    """Garment extras a geometry hash may see. The cloth asset is not one of them."""
    return {key: value for key, value in forge.items() if key not in {"lookId", CLOTH_EXTRA_KEY}}
