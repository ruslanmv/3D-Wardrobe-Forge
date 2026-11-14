"""Versioned little-endian cloth asset. Particles live in a glTF buffer, not in JSON.

Layout, 4-byte aligned. All integers and floats are little-endian.

Header, 48 bytes: magic ``WCL1``, version, flags, then counts for particles,
triangles, stretch, shear, bend, seams, attachments, render vertices, and LODs.

* positions: ``float32[particles * 3]``
* triangles: ``uint32[triangles * 3]`` particle indices
* stretch and bend: ``(uint32 a, uint32 b, float32 rest)``
* shear: ``(uint32 base_a, uint32 base_b, uint32 opposite, float32 rest)``
* seams: ``(uint32 render_a, uint32 render_b)`` coincident copies only
* attachments: ``(uint32 particle, float32 weight)`` for weights above zero
* bindings: ``(uint32 i0, i1, i2, float32 w0, w1, w2)`` per render vertex

Each LOD then stores a name, coarse positions, coarse triangles, and a map from
every full-resolution particle to one coarse particle.
"""

from __future__ import annotations

import struct

import numpy as np

MAGIC = b"WCL1"
VERSION = 1
HEADER = struct.Struct("<4s11I")
PAIR = struct.Struct("<IIf")
SHEAR = struct.Struct("<IIIf")
ATTACH = struct.Struct("<If")
BIND = struct.Struct("<IIIfff")
FLAG_HEIGHT_FALLBACK = 1

SCHEMA = "wardrobe.cloth/1"


class ClothBlobError(ValueError):
    """The buffer is not a cloth asset this viewer can read."""


def _pad(blob: bytearray) -> None:
    while len(blob) % 4:
        blob.append(0)


def encode_asset(
    *,
    positions: np.ndarray,
    triangles: np.ndarray,
    stretch: tuple[np.ndarray, np.ndarray],
    shear: np.ndarray,
    bend: tuple[np.ndarray, np.ndarray],
    seams: tuple[tuple[int, int], ...],
    attachment: np.ndarray,
    binding: np.ndarray,
    lods: list[dict],
    height_fallback: bool,
) -> bytes:
    """Pack one simulation mesh. ``lods`` entries need name, positions, triangles, particle_map."""
    points = np.asarray(positions, dtype=np.float32).reshape(-1, 3)
    tris = np.asarray(triangles, dtype=np.uint32).reshape(-1, 3)
    stretch_pairs, stretch_rest = stretch
    bend_pairs, bend_rest = bend
    shear_rows = np.asarray(shear, dtype=np.float64).reshape(-1, 4)
    flags = FLAG_HEIGHT_FALLBACK if height_fallback else 0
    blob = bytearray(
        HEADER.pack(
            MAGIC,
            VERSION,
            flags,
            len(points),
            len(tris),
            len(stretch_pairs),
            len(shear_rows),
            len(bend_pairs),
            len(seams),
            int(np.count_nonzero(attachment > 1e-4)) if attachment.size else 0,
            int(binding.size),
            len(lods),
        )
    )
    blob += np.ascontiguousarray(points, dtype="<f4").tobytes()
    blob += np.ascontiguousarray(tris, dtype="<u4").tobytes()
    for pair, rest in zip(stretch_pairs, stretch_rest, strict=True):
        blob += PAIR.pack(int(pair[0]), int(pair[1]), float(rest))
    for row in shear_rows:
        blob += SHEAR.pack(int(row[0]), int(row[1]), int(row[2]), float(row[3]))
    for pair, rest in zip(bend_pairs, bend_rest, strict=True):
        blob += PAIR.pack(int(pair[0]), int(pair[1]), float(rest))
    for a, b in seams:
        blob += struct.pack("<II", int(a), int(b))
    for index, weight in enumerate(np.asarray(attachment, dtype=np.float64)):
        if weight > 1e-4:
            blob += ATTACH.pack(int(index), float(weight))
    for particle in np.asarray(binding, dtype=np.int64):
        blob += BIND.pack(int(particle), 0, 0, 1.0, 0.0, 0.0)
    for lod in lods:
        name = lod["name"].encode("utf-8")
        blob += struct.pack("<I", len(name))
        blob += name
        _pad(blob)
        coarse = np.asarray(lod["positions"], dtype=np.float32).reshape(-1, 3)
        coarse_tris = np.asarray(lod["triangles"], dtype=np.uint32).reshape(-1, 3)
        mapping = np.asarray(lod["particle_map"], dtype=np.uint32).reshape(-1)
        blob += struct.pack("<II", len(coarse), len(coarse_tris))
        blob += np.ascontiguousarray(coarse, dtype="<f4").tobytes()
        blob += np.ascontiguousarray(coarse_tris, dtype="<u4").tobytes()
        blob += np.ascontiguousarray(mapping, dtype="<u4").tobytes()
    _pad(blob)
    return bytes(blob)


def _take(data: bytes, offset: int, size: int) -> tuple[bytes, int]:
    end = offset + size
    if end > len(data):
        raise ClothBlobError("cloth asset ended early")
    return data[offset:end], end


def decode_asset(data: bytes) -> dict:
    """Read a buffer written by :func:`encode_asset`."""
    if len(data) < HEADER.size:
        raise ClothBlobError("cloth asset header is missing")
    header = HEADER.unpack_from(data)
    magic, version, flags = header[0], header[1], header[2]
    particles, tris, stretch_n, shear_n, bend_n = header[3:8]
    seams_n, attach_n, render_n, lod_n = header[8:12]
    if magic != MAGIC or version != VERSION:
        raise ClothBlobError(f"unsupported cloth asset {magic!r} version {version}")
    offset = HEADER.size
    raw, offset = _take(data, offset, particles * 12)
    positions = np.frombuffer(raw, dtype="<f4").reshape(particles, 3).copy()
    raw, offset = _take(data, offset, tris * 12)
    if tris:
        triangles = np.frombuffer(raw, dtype="<u4").reshape(tris, 3).copy()
    else:
        triangles = np.zeros((0, 3), np.uint32)
    stretch = [_unpack_pair(data, offset + i * PAIR.size) for i in range(stretch_n)]
    offset += stretch_n * PAIR.size
    shear = [_unpack_shear(data, offset + i * SHEAR.size) for i in range(shear_n)]
    offset += shear_n * SHEAR.size
    bend = [_unpack_pair(data, offset + i * PAIR.size) for i in range(bend_n)]
    offset += bend_n * PAIR.size
    seams = []
    for _ in range(seams_n):
        raw, offset = _take(data, offset, 8)
        seams.append(struct.unpack("<II", raw))
    attachments = []
    for _ in range(attach_n):
        raw, offset = _take(data, offset, ATTACH.size)
        attachments.append(struct.unpack("<If", raw))
    bindings = []
    for _ in range(render_n):
        raw, offset = _take(data, offset, BIND.size)
        bindings.append(struct.unpack("<IIIfff", raw))
    lods = []
    for _ in range(lod_n):
        raw, offset = _take(data, offset, 4)
        name_len = struct.unpack("<I", raw)[0]
        raw, offset = _take(data, offset, name_len)
        name = raw.decode("utf-8")
        offset = (offset + 3) & ~3
        raw, offset = _take(data, offset, 8)
        coarse_n, coarse_tris = struct.unpack("<II", raw)
        raw, offset = _take(data, offset, coarse_n * 12)
        coarse = np.frombuffer(raw, dtype="<f4").reshape(coarse_n, 3).copy()
        raw, offset = _take(data, offset, coarse_tris * 12)
        if coarse_tris:
            coarse_idx = np.frombuffer(raw, dtype="<u4").reshape(coarse_tris, 3).copy()
        else:
            coarse_idx = np.zeros((0, 3), np.uint32)
        raw, offset = _take(data, offset, particles * 4)
        mapping = np.frombuffer(raw, dtype="<u4").copy()
        lods.append({"name": name, "positions": coarse, "triangles": coarse_idx, "particle_map": mapping})
    return {
        "schema": SCHEMA,
        "flags": flags,
        "heightFallback": bool(flags & FLAG_HEIGHT_FALLBACK),
        "positions": positions,
        "triangles": triangles,
        "stretch": stretch,
        "shear": shear,
        "bend": bend,
        "seams": seams,
        "attachments": attachments,
        "bindings": bindings,
        "lods": lods,
    }


def _unpack_pair(data: bytes, offset: int) -> tuple[int, int, float]:
    if offset + PAIR.size > len(data):
        raise ClothBlobError("constraint record is missing")
    return PAIR.unpack_from(data, offset)


def _unpack_shear(data: bytes, offset: int) -> tuple[int, int, int, float]:
    if offset + SHEAR.size > len(data):
        raise ClothBlobError("shear record is missing")
    return SHEAR.unpack_from(data, offset)
