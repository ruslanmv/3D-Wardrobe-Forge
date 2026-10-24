"""RL4. A verified reference drafts a garment's geometry, on more than one body.

A brief whose block says ``"gussetDraft": "freesewing-uma"`` takes its gusset width from
FreeSewing Uma's rule (assets/reference/lingerie/patterns/freesewing-uma/uma-draft.json)
applied to her measured body, instead of the block's 55 mm constant. These tests fit such a
brief on two adult reference bodies and require: the gusset's middle row is exactly the
drafted width; the drafted width is Uma's formula on that body's own recorded inputs; the
two bodies get different widths, in the ratio of their waist-to-upper-leg spans; the fit
report says where each figure came from, with the reference file's pinned hash; and the
fabric's stretch allowance changes the width as Uma's 1/(1 + stretch) says.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import numpy as np
import pytest

from tests.conftest import job_request
from wardrobe.domain.garments import TemplateCatalog
from wardrobe.domain.jobs import CreateJobRequest
from wardrobe.pipeline.orchestrator import Orchestrator
from wardrobe.queue.jobs import AsyncioJobQueue
from wardrobe.storage.database import InMemoryJobRepository, InMemoryWardrobeRepository

ROOT = Path(__file__).resolve().parents[2]
TEMPLATES = ROOT / "assets" / "garment_templates"
LOCK = ROOT / "assets" / "reference" / "lingerie" / "sources.lock.json"
DRAFTED_ID = "test-uma-briefs"


def _catalog(tmp: Path, fabric: str | None = None) -> TemplateCatalog:
    shutil.copytree(TEMPLATES, tmp / "templates")
    template = json.loads((TEMPLATES / "underwear" / "under-briefs-v2.json").read_text(encoding="utf-8"))
    template["id"] = DRAFTED_ID
    template["name"] = "Uma-Drafted Briefs"
    template["lingerie"]["brief"]["gussetDraft"] = "freesewing-uma"
    if fabric is not None:
        template["lingerie"]["fabric"] = fabric
    (tmp / "templates" / "underwear" / f"{DRAFTED_ID}.json").write_text(
        json.dumps(template), encoding="utf-8"
    )
    return TemplateCatalog.from_directory(tmp / "templates")


class _Drafts:
    """Every brief block drafted while installed (the audit's own technique)."""

    def __init__(self):
        import wardrobe.lingerie.blocks as blocks

        self.blocks, self.original, self.made = blocks, blocks.build_block, []

    def __enter__(self):
        def build(kind, params):
            mesh = self.original(kind, params)
            # Positions as drafted: later steps move the same mesh's vertices in place.
            self.made.append((kind, mesh, mesh.positions.copy()))
            return mesh

        self.blocks.build_block = build
        return self

    def __exit__(self, *_exc):
        self.blocks.build_block = self.original


async def _fit(settings, store, catalog, body: bytes, name: str):
    orchestrator = Orchestrator(
        settings=settings,
        store=store,
        jobs=InMemoryJobRepository(),
        wardrobes=InMemoryWardrobeRepository(),
        queue=AsyncioJobQueue(concurrency=1),
        catalog=catalog,
    )
    await store.put(f"sources/{name}.vrm", body)
    payload = job_request(f"sources/{name}.vrm", "uma-drafted briefs", template_id=DRAFTED_ID, avatar_id=name)
    payload["avatar"]["depictsAdult"] = True
    with _Drafts() as drafts:
        record = await orchestrator.run_now(CreateJobRequest.model_validate(payload))
    assert record.state == "completed", record.error
    meshes = [
        (mesh, drafted)
        for kind, mesh, drafted in drafts.made
        if kind == "brief-block" and mesh.metadata.get("lingerieReferences")
    ]
    assert len(meshes) == 1, "exactly the drafted brief carries a reference"
    return record, *meshes[0]


def _middle_row_width_mm(mesh, positions) -> float:
    rows = mesh.metadata["lingerieBrief"]["gusset"]
    middle = np.asarray(rows[len(rows) // 2], dtype=int)  # GUSSET_ROWS = 9: row 5 of 11 is t = 0.5
    return float(np.ptp(positions[middle, 0])) * 1000.0


@pytest.fixture(scope="module")
def bodies() -> dict[str, bytes]:
    from wardrobe.anatomy.vrm import build_reference_vrm

    return {name: build_reference_vrm(name, correctives=False) for name in ("ref-f-median", "ref-f-full")}


async def test_uma_drafts_the_gusset_on_each_body(settings, store, bodies, tmp_path):
    catalog = _catalog(tmp_path)
    found = {}
    for name, body in bodies.items():
        record, mesh, drafted_positions = await _fit(settings, store, catalog, body, name)
        (drafted,) = mesh.metadata["lingerieReferences"]
        inputs = drafted["inputs"]
        formula = (
            inputs["waistToUpperLegMm"]["value"]
            * inputs["gussetWidth"]["value"]
            * 2
            / (1 + inputs["xStretch"]["value"])
        )
        assert drafted["gussetWidthMm"] == pytest.approx(formula, abs=0.15)  # inputs are recorded to 0.1 mm
        assert _middle_row_width_mm(mesh, drafted_positions) == pytest.approx(
            drafted["gussetWidthMm"], abs=0.01
        )
        assert drafted["gussetWidthMm"] != 55.0  # not the block's constant
        # The fit report says where it came from, pinned to the hash the lock records.
        pieces = record.fit_report.lingerie["pieces"]
        (piece,) = [p for p in pieces if p.get("references")]
        lock = json.loads(LOCK.read_text(encoding="utf-8"))
        uma = next(s for s in lock["sources"] if s["id"] == "freesewing-uma")
        pinned = next(f["sha256"] for f in uma["files"] if f["path"].endswith("base.mjs"))
        assert piece["references"][0]["provenance"]["sha256"] == pinned
        assert {v["kind"] for v in inputs.values()} == {"body", "reference", "material"}
        found[name] = drafted
    median, full = found["ref-f-median"], found["ref-f-full"]
    ratio = median["inputs"]["waistToUpperLegMm"]["value"] / full["inputs"]["waistToUpperLegMm"]["value"]
    assert median["gussetWidthMm"] / full["gussetWidthMm"] == pytest.approx(ratio, rel=2e-3)


async def test_the_fabrics_stretch_allowance_moves_the_width(settings, store, bodies, tmp_path):
    """stretch-knit carries Uma's own 15%: same width. A class without one falls back, and says so."""
    knit = await _fit(
        settings, store, _catalog(tmp_path / "knit", "stretch-knit"), bodies["ref-f-median"], "knit"
    )
    lace = await _fit(
        settings, store, _catalog(tmp_path / "lace", "stretch-lace"), bodies["ref-f-median"], "lace"
    )
    (k,) = knit[1].metadata["lingerieReferences"]
    (lace_drafted,) = lace[1].metadata["lingerieReferences"]
    assert k["inputs"]["xStretch"]["from"] == "fabric stretch-knit"
    assert k["inputs"]["xStretch"]["status"] == "designer-convention"
    assert "stretch-lace has none" in lace_drafted["inputs"]["xStretch"]["from"]
    assert (
        k["gussetWidthMm"] == lace_drafted["gussetWidthMm"]
    )  # both 15%: one from the class, one by fallback


def test_stretch_enters_as_uma_says():
    from wardrobe.lingerie.references import uma_draft

    draft = uma_draft()
    assert (
        draft["formulas"]["gussetWidthMm"] == "waistToUpperLeg * gussetWidth * 2 * stretchToScale(xStretch)"
    )
    assert draft["formulas"]["stretchToScale"] == "1 / (1 + stretch)"


def test_the_existing_catalog_drafts_nothing_from_references():
    """The 35 keep their own constants: a reference is opted into, never imposed."""
    catalog = TemplateCatalog.from_directory(TEMPLATES)
    for template in catalog:
        brief = (template.lingerie or {}).get("brief") or {}
        assert "gussetDraft" not in brief, template.id
