"""AF4. Run the bare path on every library source and compare each result with its source.

Reports, per character: built or refused (and why), slots removed, retained accessors verified
byte-identical, VRM expression binds that would point at a mesh no longer drawn, morph-target
counts changed, material alpha modes changed and materials changed. Reads only.

    python tools/audit/bare_visibility.py   # prints a line per character, writes work/af4-bare-audit.json
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from tests.conftest import job_request  # noqa: E402
from wardrobe.config import Settings  # noqa: E402
from wardrobe.domain.jobs import CreateJobRequest, JobRecord  # noqa: E402
from wardrobe.pipeline.bare_body import prepare  # noqa: E402
from wardrobe.vrm.document import GltfDocument  # noqa: E402
from wardrobe.vrm.inspect import inspect_document  # noqa: E402
from wardrobe.vrm.measure import measure_body  # noqa: E402


def expression_meshes(doc: GltfDocument) -> list[int]:
    """Every mesh a VRM expression (0.x blend shape or 1.0 morph bind) drives."""
    out: list[int] = []
    vrm0 = (doc.gltf.get("extensions") or {}).get("VRM") or {}
    for group in (vrm0.get("blendShapeMaster") or {}).get("blendShapeGroups", []):
        out += [bind["mesh"] for bind in group.get("binds", [])]
    vrm1 = (doc.gltf.get("extensions") or {}).get("VRMC_vrm") or {}
    for group in ((vrm1.get("expressions") or {}).get("preset") or {}).values():
        out += [doc.nodes[bind["node"]].get("mesh", -1) for bind in group.get("morphTargetBinds", [])]
    return out


def drawn_meshes(doc: GltfDocument) -> set[int]:
    return {node["mesh"] for node in doc.nodes if "mesh" in node}


def morph_counts(doc: GltfDocument, meshes: set[int]) -> dict:
    return {(mi, prim.get("material")): len(prim.get("targets", []))
            for mi, mesh in enumerate(doc.meshes) if mi in meshes for prim in mesh["primitives"]}


async def audit(path: Path) -> dict:
    source, doc = GltfDocument.from_path(path), GltfDocument.from_path(path)
    settings = Settings()
    settings.wardrobe_adult_body_surface = True
    payload = job_request("sources/x.vrm", "Bare", template_id="body-bare-v1", baseBody="bare", private=True)
    payload["avatar"]["depictsAdult"] = True
    info = inspect_document(doc)
    context = SimpleNamespace(document=doc, info=info, measurements=measure_body(doc, info), settings=settings,
                              fit_report=SimpleNamespace(base_body=None),
                              record=JobRecord.queued(CreateJobRequest.model_validate(payload)))
    try:
        await prepare(context)
    except Exception as exc:  # a refusal is a result, not a crash
        return {"result": f"refused: {type(exc).__name__}: {str(exc)[:80]}"}
    drawn = drawn_meshes(doc)
    lost = [m for m in expression_meshes(source) if m in drawn_meshes(source) and m not in drawn]
    before = morph_counts(source, set(range(len(source.meshes))))
    after = morph_counts(doc, drawn)
    report = context.fit_report.base_body
    return {
        "result": "built",
        "removedSlots": report["removedSlots"],
        "accessorsVerifiedUnchanged": report["authoredAccessorsUnchanged"],
        "expressionBindsToUndrawnMesh": len(lost),
        "morphCountChanged": [list(k) for k, v in after.items() if before.get(k) != v],
        "alphaModeChanged": [i for i, (a, b) in enumerate(zip(source.materials, doc.materials, strict=False))
                             if a.get("alphaMode") != b.get("alphaMode")],
        "materialsChanged": [[i, doc.materials[i].get("name")]
                             for i, (a, b) in enumerate(zip(source.materials, doc.materials, strict=False)) if a != b],
        "skinRestored": bool(report["skinRestored"]),
        "keptAnatomicalMaterials": report.get("keptAnatomicalMaterials", []),
    }


def main() -> int:
    library = ROOT / "assets" / "library"
    results = {}
    for path in sorted([*library.glob("*.vrm"), *(library / "vroid").glob("*.vrm")]):
        results[path.stem] = asyncio.run(audit(path))
        print(path.stem, json.dumps(results[path.stem]))
    out = ROOT / "work" / "af4-bare-audit.json"
    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps(results, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
