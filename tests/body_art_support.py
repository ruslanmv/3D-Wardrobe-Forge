"""Body-art test support: the declared-adult body, dressed like a VRoid export, and a fingerprint.

Every tattoo test runs on ``calibration-b-medium``, a generated, faceless body that
``assets/calibration/policy.json`` declares adult — never on a library character
(docs/BODY_ART_PLAN.md §5).

``fingerprint`` is what "the same output" means for invariant I1, across machines. A job's
VRM is reproducible except the look id, which is new per job and written into the root's
and every Forge garment node's ``extras.wardrobeForge``, and except the last bits of its
float data: GitHub's runners are not all one CPU, numpy takes a different SIMD path on each,
and a reduction can round the other way. The fingerprint was one hash of the binary buffer,
so the same commit passed on one runner and failed on the next (the red bodycon on 3.11,
an hour apart, while 3.12 passed). Now:

* ``exact`` hashes everything that is not float vertex data — the glTF JSON with every
  ``lookId`` and every float accessor's ``min``/``max`` removed, and every buffer view no
  float accessor reads (indices, joints, images) — and must match exactly;
* ``floats`` sums up each float accessor (count, extremes, sum, sum of squares and a sum
  weighted by position in the array, which a swap of two values changes), compared within
  ``FLOAT_SUM_TOLERANCE`` / ``FLOAT_EDGE_TOLERANCE`` by ``differences``. Rounding noise moves
  them by ~1e-5 at most; a vertex moved by a millimetre, by more than the tolerance.
"""

from __future__ import annotations

import hashlib
import json

import numpy as np

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


#: Metres (or unit weights) summed over an accessor: CPU rounding noise stays far below it.
FLOAT_SUM_TOLERANCE = 1e-3
#: An accessor's smallest and largest value.
FLOAT_EDGE_TOLERANCE = 1e-5
FLOAT = 5126


def fingerprint(vrm: bytes) -> dict:
    document = GltfDocument.from_bytes(vrm)
    gltf = _without_look_ids(document.gltf)
    accessors = gltf.get("accessors") or []
    floats, float_views = [], set()
    for index, accessor in enumerate(accessors):
        if int(accessor.get("componentType", 0)) != FLOAT:
            continue
        values = document.read_accessor(index).astype(np.float64).reshape(-1)
        weight = (np.arange(values.size) % 7) + 1
        floats.append([index, int(values.size), float(values.min(initial=0.0)), float(values.max(initial=0.0)),
                       float(values.sum()), float((values * values).sum()), float((values * weight).sum())])
        accessor.pop("min", None)
        accessor.pop("max", None)
        if "bufferView" in accessor:
            float_views.add(int(accessor["bufferView"]))
    digest = hashlib.sha256(json.dumps(gltf, sort_keys=True).encode("utf-8"))
    binary = bytes(document.binary)
    for index, view in enumerate(gltf.get("bufferViews") or []):
        if index in float_views:
            continue
        start = int(view.get("byteOffset", 0))
        digest.update(binary[start:start + int(view["byteLength"])])
    return {"exact": digest.hexdigest(), "floats": floats}


def differences(got: dict, want: dict) -> list[str]:
    """What differs between two fingerprints beyond rounding; empty when they are the same output."""
    out = []
    if got["exact"] != want["exact"]:
        out.append("structure, indices, joints or images differ")
    if len(got["floats"]) != len(want["floats"]):
        return [*out, f"{len(got['floats'])} float accessors, {len(want['floats'])} expected"]
    for g, w in zip(got["floats"], want["floats"], strict=True):
        if g[:2] != w[:2]:
            out.append(f"accessor {g[0]}: {g[1]} values, {w[1]} expected")
            continue
        edges = np.abs(np.subtract(g[2:4], w[2:4])).max()
        sums = np.abs(np.subtract(g[4:], w[4:])).max()
        if edges > FLOAT_EDGE_TOLERANCE or sums > FLOAT_SUM_TOLERANCE:
            out.append(f"accessor {g[0]}: extremes off by {edges:.2e}, sums by {sums:.2e}")
    return out


async def run(orchestrator, store, prompt: str, source: bytes | None = None, **fields):
    """A job on the dressed declared-adult body; ``fields`` go on the request (bodyArt, …)."""
    await store.put("sources/body-art.vrm", source if source is not None else dressed_body())
    payload = job_request("sources/body-art.vrm", prompt)
    payload["avatar"]["depictsAdult"] = True
    payload.update(fields)
    record = await orchestrator.run_now(CreateJobRequest.model_validate(payload))
    output = await store.get(f"looks/{record.look.id}/look.vrm") if record.look else None
    return record, output
