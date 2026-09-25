"""A minimal PNG encoder, so textures need no imaging library.

Pillow is an optional extra (``preview``); the garment pipeline is not. A tiling
fabric texture is a few kilobytes of RGBA that zlib compresses well, and the
PNG container around it is three chunks. Writing it here keeps texture
generation in the core install, deterministic, and byte-identical across runs.
"""

from __future__ import annotations

import struct
import zlib

import numpy as np

SIGNATURE = b"\x89PNG\r\n\x1a\n"


def _chunk(kind: bytes, payload: bytes) -> bytes:
    return (
        struct.pack(">I", len(payload))
        + kind
        + payload
        + struct.pack(">I", zlib.crc32(kind + payload) & 0xFFFFFFFF)
    )


def encode_png(pixels: np.ndarray) -> bytes:
    """Encode an ``(height, width, 4)`` uint8 RGBA array (row 0 at the top)."""
    array = np.ascontiguousarray(pixels, dtype=np.uint8)
    if array.ndim != 3 or array.shape[2] != 4:
        raise ValueError("expected an (height, width, 4) RGBA array")
    height, width = array.shape[:2]
    # Filter type 0 (None) on every row: textures this small gain nothing from
    # per-row filtering that zlib does not already find.
    rows = np.concatenate([np.zeros((height, 1), dtype=np.uint8), array.reshape(height, width * 4)], axis=1)
    header = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)
    return (
        SIGNATURE
        + _chunk(b"IHDR", header)
        + _chunk(b"IDAT", zlib.compress(rows.tobytes(), 9))
        + _chunk(b"IEND", b"")
    )


def png_size(data: bytes) -> tuple[int, int]:
    """(width, height) from a PNG's header — enough for tests and sanity checks."""
    if not data.startswith(SIGNATURE) or data[12:16] != b"IHDR":
        raise ValueError("not a PNG")
    width, height = struct.unpack(">II", data[16:24])
    return int(width), int(height)


def decode_png(data: bytes) -> np.ndarray:
    """Decode what :func:`encode_png` writes (8-bit RGBA, filter 0). Test helper."""
    width, height = png_size(data)
    offset, payload = 8, b""
    while offset < len(data):
        (length,) = struct.unpack(">I", data[offset : offset + 4])
        kind = data[offset + 4 : offset + 8]
        if kind == b"IDAT":
            payload += data[offset + 8 : offset + 8 + length]
        offset += 12 + length
    raw = np.frombuffer(zlib.decompress(payload), dtype=np.uint8).reshape(height, width * 4 + 1)
    if raw[:, 0].any():
        raise ValueError("only unfiltered rows are supported")
    return raw[:, 1:].reshape(height, width, 4).copy()


__all__ = ["decode_png", "encode_png", "png_size"]
