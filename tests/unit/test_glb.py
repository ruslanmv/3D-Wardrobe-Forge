"""GLB container parsing and writing."""

from __future__ import annotations

import json
import struct

import pytest

from wardrobe.vrm.glb import CHUNK_BIN, CHUNK_JSON, GLB_MAGIC, Glb, GlbError, is_glb


def _container(gltf: dict, binary: bytes = b"") -> bytes:
    return Glb(gltf=gltf, binary=binary).serialize()


def test_round_trip_preserves_json_and_binary():
    payload = {"asset": {"version": "2.0"}, "nodes": [{"name": "hips"}]}
    data = _container(payload, b"\x01\x02\x03")

    parsed = Glb.parse(data)
    assert parsed.gltf == payload
    # The BIN chunk is padded to 4 bytes on write.
    assert parsed.binary[:3] == b"\x01\x02\x03"


def test_chunks_are_four_byte_aligned():
    data = _container({"a": "bcd"}, b"\x01")
    assert len(data) % 4 == 0


def test_rejects_non_glb():
    with pytest.raises(GlbError, match="not a GLB"):
        Glb.parse(b"PK\x03\x04" + b"\x00" * 32)


def test_rejects_truncated_header():
    with pytest.raises(GlbError, match="too small"):
        Glb.parse(b"glTF")


def test_rejects_unsupported_version():
    header = struct.pack("<III", GLB_MAGIC, 1, 12)
    with pytest.raises(GlbError, match="unsupported GLB version"):
        Glb.parse(header)


def test_rejects_declared_length_beyond_file():
    header = struct.pack("<III", GLB_MAGIC, 2, 4096)
    with pytest.raises(GlbError, match="exceeds the actual file size"):
        Glb.parse(header)


def test_rejects_chunk_past_end():
    body = json.dumps({"a": 1}).encode()
    data = struct.pack("<III", GLB_MAGIC, 2, 12 + 8 + len(body))
    data += struct.pack("<II", len(body) + 500, CHUNK_JSON) + body
    with pytest.raises(GlbError, match="past the end"):
        Glb.parse(data)


def test_rejects_missing_json_chunk():
    payload = b"\x00\x00\x00\x00"
    data = struct.pack("<III", GLB_MAGIC, 2, 12 + 8 + len(payload))
    data += struct.pack("<II", len(payload), CHUNK_BIN) + payload
    with pytest.raises(GlbError, match="no JSON chunk"):
        Glb.parse(data)


def test_rejects_invalid_json():
    body = b"{not json"
    body += b" " * ((-len(body)) % 4)
    data = struct.pack("<III", GLB_MAGIC, 2, 12 + 8 + len(body))
    data += struct.pack("<II", len(body), CHUNK_JSON) + body
    with pytest.raises(GlbError, match="not valid UTF-8 JSON"):
        Glb.parse(data)


def test_unknown_chunks_are_ignored():
    body = json.dumps({"asset": {"version": "2.0"}}).encode()
    body += b" " * ((-len(body)) % 4)
    extra = b"\xde\xad\xbe\xef"

    total = 12 + 8 + len(body) + 8 + len(extra)
    data = struct.pack("<III", GLB_MAGIC, 2, total)
    data += struct.pack("<II", len(body), CHUNK_JSON) + body
    data += struct.pack("<II", len(extra), 0x12345678) + extra

    assert Glb.parse(data).gltf["asset"]["version"] == "2.0"


def test_is_glb_sniffs_magic(vrm_bytes: bytes):
    assert is_glb(vrm_bytes)
    assert not is_glb(b"notaglb")
    assert not is_glb(b"")
