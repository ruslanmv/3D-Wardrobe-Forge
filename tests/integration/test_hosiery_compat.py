"""Non-destructive: outfits without hosiery build byte-for-byte the geometry they built before it.

``tests/fixtures/gallery_geometry_hashes.json`` was written by
``tools/gallery/geometry_hashes.py`` before the hosiery system existed: one
hash per garment (positions, normals, UVs, indices, joints, weights, material)
for the 81 gallery looks. The full comparison takes minutes and is the tool's
``--check``; this test re-runs a sample on every CI run: an opaque baseline,
lingerie under a dress, fishnet stockings (legwear, the layer hosiery extends)
and the full layered outfit.
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools" / "gallery"))
import geometry_hashes  # noqa: E402

SAMPLE = (1, 7, 8, 19)


@pytest.mark.parametrize("number", SAMPLE)
def test_a_gallery_look_without_hosiery_is_unchanged(number, tmp_path):
    from wardrobe.config import Settings
    from wardrobe.domain.garments import TemplateCatalog
    from wardrobe.pipeline.orchestrator import Orchestrator
    from wardrobe.queue.jobs import AsyncioJobQueue
    from wardrobe.storage.database import InMemoryJobRepository, InMemoryWardrobeRepository
    from wardrobe.storage.object_store import LocalObjectStore

    baseline = json.loads((ROOT / "tests" / "fixtures" / "gallery_geometry_hashes.json").read_text())
    settings = Settings(wardrobe_storage_root=str(tmp_path), wardrobe_engine="native", strict_licensing=True)
    store = LocalObjectStore(settings.storage_root_path, settings)
    orchestrator = Orchestrator(settings=settings, store=store, jobs=InMemoryJobRepository(),
                                wardrobes=InMemoryWardrobeRepository(), queue=AsyncioJobQueue(concurrency=1),
                                catalog=TemplateCatalog.from_directory(ROOT / "assets" / "garment_templates"))
    look = next(entry for entry in geometry_hashes.LOOKS if entry[0] == number)

    async def go():
        await store.put("sources/plain.vrm", geometry_hashes.toon_mannequin().to_bytes())
        await store.put("sources/dressed.vrm", geometry_hashes.dressed_mannequin())
        return await geometry_hashes.run(None, [look], orchestrator, store, {"depictsAdult": True})

    result = asyncio.run(go())
    assert result[f"mannequin/{number:02d}"] == baseline[f"mannequin/{number:02d}"]
