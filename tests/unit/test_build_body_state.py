"""CG5. The no-artist body-state build: one deleted band filled, every garment off, file tagged.

Run on the suite's generated body (``body_completion_support.deleted_chest``), never a character.
"""

from __future__ import annotations

import sys
from pathlib import Path

from tests.body_completion_support import deleted_chest
from wardrobe.vrm.document import GltfDocument
from wardrobe.vrm.garment_inventory import garment_inventory

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools" / "body_surface"))

import build_body_state  # noqa: E402


def test_completes_strips_and_tags():
    document = deleted_chest()
    assert garment_inventory(document)
    report = build_body_state.build_bare(document)
    assert report["garmentsRemoved"] >= 1
    assert report["reconstructedRegions"]
    tag = document.gltf["extras"]["wardrobeForge"]
    assert tag["bare"] is True and tag["reconstruction"] == "bc1-proxy"
    reread = GltfDocument.from_bytes(document.to_bytes())
    drawn = {n["mesh"] for n in reread.nodes if "mesh" in n}
    assert not [g for g in garment_inventory(reread) if g.mesh in drawn]


def test_is_deterministic():
    first, second = deleted_chest(), deleted_chest()
    build_body_state.build_bare(first)
    build_body_state.build_bare(second)
    assert first.to_bytes() == second.to_bytes()


def test_operator_switches_default_on(monkeypatch):
    from wardrobe.config import Settings

    monkeypatch.delenv("WARDROBE_ADULT_BODY_SURFACE", raising=False)
    monkeypatch.delenv("WARDROBE_BARE_BODY_COMPLETION", raising=False)
    settings = Settings(_env_file=None)
    assert settings.wardrobe_adult_body_surface is True
    assert settings.wardrobe_bare_body_completion is True
