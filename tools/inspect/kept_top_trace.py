#!/usr/bin/env python3
"""KL3. What the kept-top pass did to a garment's own shell, measured inside one build.

    python tools/inspect/kept_top_trace.py avatar-sample-c:shorts-denim-v1 [slug:template ...] \\
        [--json out.json] [--colour blue]

``kept_top_layers.py --before`` compares a look with a second build of it made with the pass
switched off. That is the right comparison for what shows (which layer is outermost), and the
wrong one for the mesh: the two builds do not start from the same shell. With the pass off the
foundation underneath sits elsewhere, the shell built over it differs (by up to 13 mm on
AvatarSample C's shorts), and two vertices that happen to coincide in one build are 1.8 mm apart
in the other before any pass has touched them. Read across builds, that was reported as a seam
the pass had opened; it had not moved the pair relative to each other at all.

This builds each look once, as ``tools/prebuild.py`` asks for it, and reads the garment's
positions immediately before and immediately after ``tuck_under_kept_tops``, and then in the
exported file. Per garment the pass ran on:

* seam pairs (vertices that share a position before the pass) and how far apart the pass, and
  the export, left them;
* every edge's length after against before: the range, and how many are past 1.5x or under 0.67x;
* triangles turned over, degenerate triangles, the largest move, any change of height;
* whether the exported mesh is the mesh the pass left.

Nothing is stored; the look is built in a temporary directory and thrown away.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import tempfile
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools" / "inspect"))

import kept_top_layers  # noqa: E402

import wardrobe.engines.native as native  # noqa: E402
from wardrobe.config import Settings  # noqa: E402
from wardrobe.domain.garments import TemplateCatalog  # noqa: E402
from wardrobe.domain.jobs import CreateJobRequest  # noqa: E402
from wardrobe.library import AvatarLibrary  # noqa: E402
from wardrobe.pipeline.orchestrator import Orchestrator  # noqa: E402
from wardrobe.queue.jobs import AsyncioJobQueue  # noqa: E402
from wardrobe.storage.database import InMemoryJobRepository, InMemoryWardrobeRepository  # noqa: E402
from wardrobe.storage.object_store import LocalObjectStore  # noqa: E402
from wardrobe.vrm.document import GltfDocument  # noqa: E402


def coincident_pairs(points: np.ndarray) -> np.ndarray:
    """Index pairs of vertices that share a position (to 0.01 mm): a seam's two sides."""
    keys = np.round(points * 1e5).astype(np.int64)
    _, inverse, counts = np.unique(keys, axis=0, return_inverse=True, return_counts=True)
    inverse = inverse.ravel()
    pairs = [(int(members[0]), int(other))
             for group in np.nonzero(counts > 1)[0]
             for members in [np.nonzero(inverse == group)[0]] for other in members[1:]]
    return np.asarray(pairs, dtype=np.int64).reshape(-1, 2)


def _normals(points: np.ndarray, triangles: np.ndarray) -> np.ndarray:
    return np.cross(points[triangles[:, 1]] - points[triangles[:, 0]],
                    points[triangles[:, 2]] - points[triangles[:, 0]])


def measure(before: np.ndarray, after: np.ndarray, triangles: np.ndarray,
            exported: np.ndarray | None = None) -> dict:
    """The pass's effect on one mesh: ``before`` and ``after`` are the same vertices."""
    pairs = coincident_pairs(before)

    def apart(points: np.ndarray) -> float:
        if not len(pairs):
            return 0.0
        return float(np.linalg.norm(points[pairs[:, 0]] - points[pairs[:, 1]], axis=1).max()) * 1000

    edges = np.unique(np.sort(np.concatenate(
        [triangles[:, [0, 1]], triangles[:, [1, 2]], triangles[:, [2, 0]]]), axis=1), axis=0)
    rest = np.linalg.norm(before[edges[:, 0]] - before[edges[:, 1]], axis=1)
    now = np.linalg.norm(after[edges[:, 0]] - after[edges[:, 1]], axis=1)
    usable = rest > 1e-6
    ratio = now[usable] / rest[usable]
    was_normals, normals = _normals(before, triangles), _normals(after, triangles)
    moved = np.linalg.norm(after - before, axis=1)
    out = {
        "vertices": int(before.shape[0]),
        "triangles": int(triangles.shape[0]),
        "movedVertices": int((moved > 1e-7).sum()),
        "maxMoveMm": round(float(moved.max()) * 1000, 1),
        "heightChangedMm": round(float(np.abs(after[:, 1] - before[:, 1]).max()) * 1000, 4),
        "seamPairs": int(len(pairs)),
        "seamGapAfterPassMm": round(apart(after), 4),
        "edges": int(usable.sum()),
        "edgeRatio": [round(float(ratio.min()), 2), round(float(ratio.max()), 2)],
        "edgesPast1_5x": int((ratio > 1.5).sum()),
        "edgesUnder0_67x": int((ratio < 1 / 1.5).sum()),
        "flippedTriangles": int((np.einsum("ij,ij->i", normals, was_normals) < 0).sum()),
        "degenerateTriangles": int((np.linalg.norm(normals, axis=1) < 1e-12).sum()),
        "degenerateBefore": int((np.linalg.norm(was_normals, axis=1) < 1e-12).sum()),
    }
    if exported is not None:
        # A skirt is exported as more than the shell the pass moved (its cloth asset adds to it):
        # then the two cannot be laid side by side, and that is said rather than called a difference.
        out["exportedVertices"] = int(exported.shape[0])
        if exported.shape == after.shape:
            out["exportedIsWhatThePassLeft"] = bool(float(np.abs(exported - after).max()) < 1e-6)
            out["seamGapExportedMm"] = round(apart(exported), 4)
        else:
            out["exportedIsWhatThePassLeft"] = None
            own = coincident_pairs(exported)
            out["exportedCoincidentPairs"] = int(len(own))
    return out


async def trace(pairs: list[tuple[str, str]], colour: str) -> list[dict]:
    calls: list[dict] = []
    real = native.tuck_under_kept_tops

    def traced(document, mesh, measurements, **kw):
        before = mesh.positions.copy()
        report = real(document, mesh, measurements, **kw)
        calls.append({"category": kw.get("category"), "before": before, "after": mesh.positions.copy(),
                      "triangles": np.asarray(mesh.indices).reshape(-1, 3).copy(), "report": report})
        return report

    native.tuck_under_kept_tops = traced
    catalog = TemplateCatalog.from_directory(ROOT / "assets" / "garment_templates")
    library = AvatarLibrary.from_directory(ROOT / "assets" / "library")
    rows = []
    try:
        with tempfile.TemporaryDirectory() as tmp:
            settings = Settings(_env_file=None, wardrobe_storage_root=str(Path(tmp) / "store"),
                                wardrobe_engine="native", strict_licensing=True)
            store = LocalObjectStore(settings.storage_root_path, settings)
            orchestrator = Orchestrator(
                settings=settings, store=store, jobs=InMemoryJobRepository(),
                wardrobes=InMemoryWardrobeRepository(), queue=AsyncioJobQueue(concurrency=1), catalog=catalog)
            await library.seed(store)
            for slug, template in pairs:
                calls.clear()
                item = catalog.get(template)
                result = await orchestrator.run_now(CreateJobRequest.model_validate({
                    "avatar": library.get(slug).avatar_input(),
                    "outfit": {"prompt": f"{colour} {item.name}", "mode": "template", "templateId": template,
                               "color": colour},
                    "options": {"renderPreview": False, "engine": "native", "ensureFoundation": True,
                                "wardrobeId": slug}}))
                row = {"avatar": slug, "template": template, "state": str(result.state), "garments": []}
                exported = None
                if result.look is not None:
                    document = GltfDocument.from_bytes(await store.get(f"looks/{result.look.id}/look.vrm"))
                    found = kept_top_layers.bottom_mesh(document)
                    exported = found[0] if found is not None else None
                for index, call in enumerate(calls):
                    last = index == len(calls) - 1  # the look's own garment; earlier calls are its foundation
                    measured = measure(call["before"], call["after"], call["triangles"],
                                       exported if last else None)
                    row["garments"].append({"category": call["category"], "isTheBottom": last,
                                            "keptTopTuck": call["report"], **measured})
                rows.append(row)
                print(json.dumps(row), flush=True)
    finally:
        native.tuck_under_kept_tops = real
    return rows


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("looks", nargs="+", help="slug:template")
    parser.add_argument("--colour", default="blue")
    parser.add_argument("--json", type=Path)
    args = parser.parse_args(argv)
    rows = asyncio.run(trace([tuple(look.split(":", 1)) for look in args.looks], args.colour))
    if args.json:
        args.json.write_text(json.dumps(rows, indent=1) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
