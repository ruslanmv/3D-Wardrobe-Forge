"""Minimal GLB container reader/writer with no third-party dependencies.

The parser is deliberately strict: a VRM that arrives from an untrusted user
should fail loudly here rather than half-way through a Blender run.
"""

from __future__ import annotations

import json
import struct
from dataclasses import dataclass, field

GLB_MAGIC = 0x46546C67  # b"glTF"
GLB_VERSION = 2
CHUNK_JSON = 0x4E4F534A  # b"JSON"
CHUNK_BIN = 0x004E4942  # b"BIN\0"

HEADER_STRUCT = struct.Struct("<III")
CHUNK_STRUCT = struct.Struct("<II")

#: Hard ceiling applied while parsing. The API enforces its own (smaller)
#: limit from configuration; this one exists so a malformed header can never
#: make the parser allocate an unbounded buffer.
MAX_GLB_BYTES = 512 * 1024 * 1024


class GlbError(ValueError):
    """Raised when a byte stream is not a GLB container we can process."""


@dataclass(slots=True)
class Glb:
    """A parsed GLB: the JSON chunk plus the optional binary chunk."""

    gltf: dict
    binary: bytes = b""
    extras: dict = field(default_factory=dict)

    @classmethod
    def parse(cls, data: bytes) -> Glb:
        if len(data) > MAX_GLB_BYTES:
            raise GlbError(f"file exceeds {MAX_GLB_BYTES} bytes")
        if len(data) < HEADER_STRUCT.size:
            raise GlbError("file is too small to be a GLB container")

        magic, version, total_length = HEADER_STRUCT.unpack_from(data, 0)
        if magic != GLB_MAGIC:
            raise GlbError("not a GLB container (bad magic; is this a .gltf or .zip?)")
        if version != GLB_VERSION:
            raise GlbError(f"unsupported GLB version {version}; expected {GLB_VERSION}")
        if total_length > len(data):
            raise GlbError("declared GLB length exceeds the actual file size")

        gltf: dict | None = None
        binary = b""
        offset = HEADER_STRUCT.size
        end = min(total_length, len(data))

        while offset + CHUNK_STRUCT.size <= end:
            chunk_length, chunk_type = CHUNK_STRUCT.unpack_from(data, offset)
            offset += CHUNK_STRUCT.size
            if offset + chunk_length > end:
                raise GlbError("chunk extends past the end of the container")
            payload = data[offset : offset + chunk_length]
            offset += chunk_length
            # Chunks are padded to a 4-byte boundary.
            offset += (-chunk_length) % 4

            if chunk_type == CHUNK_JSON:
                if gltf is not None:
                    raise GlbError("container declares more than one JSON chunk")
                try:
                    gltf = json.loads(payload.decode("utf-8"))
                except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                    raise GlbError(f"JSON chunk is not valid UTF-8 JSON: {exc}") from exc
            elif chunk_type == CHUNK_BIN:
                if binary:
                    raise GlbError("container declares more than one BIN chunk")
                binary = bytes(payload)
            # Unknown chunk types are ignored, as the glTF spec requires.

        if gltf is None:
            raise GlbError("container has no JSON chunk")
        if not isinstance(gltf, dict):
            raise GlbError("JSON chunk is not an object")
        return cls(gltf=gltf, binary=binary)

    def serialize(self) -> bytes:
        json_payload = json.dumps(self.gltf, separators=(",", ":")).encode("utf-8")
        json_payload += b" " * ((-len(json_payload)) % 4)

        chunks = [(CHUNK_JSON, json_payload)]
        if self.binary:
            binary_payload = bytes(self.binary)
            binary_payload += b"\0" * ((-len(binary_payload)) % 4)
            chunks.append((CHUNK_BIN, binary_payload))

        total = HEADER_STRUCT.size + sum(CHUNK_STRUCT.size + len(p) for _, p in chunks)
        out = bytearray(HEADER_STRUCT.pack(GLB_MAGIC, GLB_VERSION, total))
        for chunk_type, payload in chunks:
            out += CHUNK_STRUCT.pack(len(payload), chunk_type)
            out += payload
        return bytes(out)


def is_glb(data: bytes) -> bool:
    """Cheap sniff used by upload validation before a full parse."""
    return len(data) >= 4 and struct.unpack_from("<I", data, 0)[0] == GLB_MAGIC
