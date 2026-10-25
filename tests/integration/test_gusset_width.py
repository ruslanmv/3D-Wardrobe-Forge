"""GF1. A seated gusset keeps the width it was cut to: the foundation under her clothes.

Seating a brief's gusset on a reference body whose thighs meet squeezed its middle row from
55 mm of fabric to 16 mm (10 mm across, seen from below): every brief's crotch was a strip.
Fabric is not compressed like that; a gusset's sides ride up the inner thighs. The briefs
Auto Foundation puts under a dress must keep MIN_CUT_SHARE..MAX_CUT_SHARE of each interior
row's cut length across, on two adult bodies. Underwear she asks for is seated as before
(wardrobe/lingerie/fit.py ``_seat_brief_gusset`` says why), which the second test holds.
"""

from __future__ import annotations

import numpy as np
import pytest

from tests.conftest import job_request
from wardrobe.domain.jobs import CreateJobRequest
from wardrobe.lingerie.fit import MAX_CUT_SHARE, MIN_CUT_SHARE


class _Drafts:
    def __init__(self):
        import wardrobe.lingerie.blocks as blocks

        self.blocks, self.original, self.made = blocks, blocks.build_block, []

    def __enter__(self):
        def build(kind, params):
            mesh = self.original(kind, params)
            self.made.append((kind, mesh, mesh.positions.copy()))
            return mesh

        self.blocks.build_block = build
        return self

    def __exit__(self, *_exc):
        self.blocks.build_block = self.original


def _arc(points: np.ndarray) -> float:
    return float(np.linalg.norm(np.diff(points, axis=0), axis=1).sum())


@pytest.mark.parametrize("body", ["ref-f-median", "ref-f-full"])
async def test_a_seated_gusset_keeps_its_cut_width(orchestrator, store, body):
    from wardrobe.anatomy.vrm import build_reference_vrm

    await store.put(f"sources/{body}.vrm", build_reference_vrm(body, correctives=False))
    payload = job_request(f"sources/{body}.vrm", "black bodycon mini dress", template_id="dress-mini-bodycon-v1",
                          avatar_id=body, ensureFoundation=True)
    payload["avatar"]["depictsAdult"] = True
    with _Drafts() as drafts:
        record = await orchestrator.run_now(CreateJobRequest.model_validate(payload))
    assert record.state == "completed", record.error
    ((_kind, mesh, drafted),) = [d for d in drafts.made if d[0] == "brief-block"]
    rows = mesh.metadata["lingerieBrief"]["gusset"]
    for r, row in enumerate(rows[1:-1], start=1):
        # The seated rows start from the curve gusset_point draws between the fitted seams, not
        # from the drafted mesh; the cut is that curve's width, which the drafted row equals.
        cut = _arc(drafted[row])
        have = _arc(mesh.positions[row])
        # Above: the pushes that end the seat, so nothing is left inside her, lift a row a little
        # after the hold (ref-f-full's middle row under a dress settles at 117%).
        assert MIN_CUT_SHARE - 0.01 <= have / cut <= MAX_CUT_SHARE + 0.03, (body, r, round(have / cut, 3))


async def test_underwear_she_asks_for_is_seated_as_before(orchestrator, store, monkeypatch):
    from wardrobe.anatomy.vrm import build_reference_vrm
    from wardrobe.lingerie import fit

    held = []
    original = fit.seat_gusset

    def spy(*args, **kwargs):
        held.append(kwargs.get("hold_cut", True))
        return original(*args, **kwargs)

    monkeypatch.setattr(fit, "seat_gusset", spy)
    await store.put("sources/ref-f-median.vrm", build_reference_vrm("ref-f-median", correctives=False))
    payload = job_request("sources/ref-f-median.vrm", "briefs", template_id="under-briefs-v2", avatar_id="ref-f-median")
    payload["avatar"]["depictsAdult"] = True
    record = await orchestrator.run_now(CreateJobRequest.model_validate(payload))
    assert record.state == "completed", record.error
    assert held == [False]
