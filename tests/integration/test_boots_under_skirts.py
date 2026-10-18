"""AN1. A boot goes under what hangs over it, and over what hugs her legs.

Cut round every layer already fitted, ankle boots under a floor-length gown were cut
round the gown's hem — a drum at her ankles — and over-the-knee boots under a pencil
skirt took the skirt's width all the way down. A boot is cut round her legs and the
layers that hug them; a dress or a skirt stays outside it.
"""

from __future__ import annotations

import numpy as np

from tests.conftest import job_request
from wardrobe.domain.jobs import CreateJobRequest, JobState
from wardrobe.vrm.document import GltfDocument


async def boot_width(orchestrator, store, stored_avatar, prompt: str) -> float:
    """Widest the boots are, across her (x), metres."""
    record = await orchestrator.run_now(CreateJobRequest.model_validate(job_request(stored_avatar, prompt)))
    assert record.state is JobState.COMPLETED, record.error
    document = GltfDocument.from_bytes(await store.get(f"looks/{record.look.id}/look.vrm"))
    xs = []
    for node in document.nodes:
        if "mesh" in node and "Boots" in (node.get("name") or ""):
            for primitive in document.meshes[node["mesh"]]["primitives"]:
                xs.append(document.read_accessor(primitive["attributes"]["POSITION"])[:, 0])
    assert xs, "no boots in the look"
    x = np.concatenate(xs)
    return float(x.max() - x.min())


async def test_ankle_boots_under_a_gown_are_ankle_boots(orchestrator, store, stored_avatar):
    alone = await boot_width(orchestrator, store, stored_avatar, "black stiletto ankle boots")
    under = await boot_width(orchestrator, store, stored_avatar,
                             "white satin evening gown + black stiletto ankle boots")
    assert under < alone + 0.01


async def test_boots_still_go_over_stockings(orchestrator, store, stored_avatar):
    bare = await boot_width(orchestrator, store, stored_avatar, "black over-the-knee boots")
    over = await boot_width(orchestrator, store, stored_avatar,
                            "black opaque thigh-high stockings + black over-the-knee boots")
    assert over >= bare - 1e-4  # the stockings are inside the boot, not through it
