"""Body-art test support: the declared-adult body, dressed like a VRoid export, and a fingerprint.

Every tattoo test runs on ``calibration-b-medium``, a generated, faceless body that
``assets/calibration/policy.json`` declares adult — never on a library character
(docs/BODY_ART_PLAN.md §5).

``fingerprint`` is what "the same output" means for invariant I1. A job's VRM is
byte-for-byte reproducible except the look id, which is new per job and written into
the root's and every Forge garment node's ``extras.wardrobeForge``; the fingerprint is
the binary buffer's hash and the glTF JSON's hash with every ``lookId`` removed.
"""

from __future__ import annotations

import hashlib
import json

from tests.conftest import job_request
from tests.vroid_support import dress_like_vroid
from wardrobe.domain.jobs import CreateJobRequest
from wardrobe.policy.calibration import declared_adult
from wardrobe.vrm.build import CALIBRATION_BODIES, build_vrm
from wardrobe.vrm.document import GltfDocument

BODY = CALIBRATION_BODIES[1]
assert declared_adult(BODY.name), "body-art tests run only on a declared-adult calibration body"


def dressed_body() -> bytes:
    """VRM 1.0 (its terms allow what the VRM 0.x body's disallow), in VRoid Tops and Bottoms."""
    return dress_like_vroid(build_vrm(BODY, spec="VRM1"))


def _without_look_ids(value):
    if isinstance(value, dict):
        return {k: _without_look_ids(v) for k, v in value.items() if k != "lookId"}
    if isinstance(value, list):
        return [_without_look_ids(v) for v in value]
    return value


def fingerprint(vrm: bytes) -> list[str]:
    document = GltfDocument.from_bytes(vrm)
    body = json.dumps(_without_look_ids(document.gltf), sort_keys=True).encode("utf-8")
    return [hashlib.sha256(bytes(document.binary)).hexdigest(), hashlib.sha256(body).hexdigest()]


async def run(orchestrator, store, prompt: str, source: bytes | None = None, **fields):
    """A job on the dressed declared-adult body; ``fields`` go on the request (bodyArt, …)."""
    await store.put("sources/body-art.vrm", source if source is not None else dressed_body())
    payload = job_request("sources/body-art.vrm", prompt)
    payload["avatar"]["depictsAdult"] = True
    payload.update(fields)
    record = await orchestrator.run_now(CreateJobRequest.model_validate(payload))
    output = await store.get(f"looks/{record.look.id}/look.vrm") if record.look else None
    return record, output
