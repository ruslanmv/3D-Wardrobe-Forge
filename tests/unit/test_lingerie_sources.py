"""RL3. The lingerie reference library: licensed, pinned, and what its records say it is."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BASE = ROOT / "assets" / "reference" / "lingerie"


def _verify():
    spec = importlib.util.spec_from_file_location("verify", ROOT / "tools/data/verify_lingerie_sources.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_library_verifies_offline():
    assert _verify().verify() == []


def test_gpl_gated_and_paid_sources_keep_nothing_here():
    lock = json.loads((BASE / "sources.lock.json").read_text(encoding="utf-8"))
    for source in lock["sources"]:
        if source["license"] not in _verify().REDISTRIBUTABLE:
            assert source["files"] == [], source["id"]


def test_no_source_claims_lingerie_it_was_not_seen_to_contain():
    """GarmentCodeData and Seamly2D were inspected and hold no lingerie pattern; say so, never more."""
    by_id = {
        s["id"]: s for s in json.loads((BASE / "sources.lock.json").read_text(encoding="utf-8"))["sources"]
    }
    for sid in ("garmentcode", "garmentcodedata-v2", "seamly2d"):
        assert not {"bra", "brief", "bra cup"} & set(by_id[sid]["garmentCategories"]), sid
    assert by_id["seamly2d"]["use"] == "unsuitable"


def test_cup_sizes_are_monotonic_and_in_millimetres():
    cup = json.loads((BASE / "patterns/bracuppattern/bracuppattern-cup.json").read_text(encoding="utf-8"))
    sizes = cup["sizes"]
    assert [s["size"] for s in sizes] == list(range(1, 30))
    for a, b in zip(sizes, sizes[1:], strict=False):
        assert b["overBreastMinMm"] - a["overBreastMinMm"] == 17.0
        assert b["line1Mm"] > a["line1Mm"]
    reference = next(s for s in sizes if s["size"] == cup["referenceSize"])
    assert reference["scale"] == 1.0 and 140.0 < reference["overBreastMinMm"] < 250.0


def test_uma_defaults_sit_inside_their_own_ranges():
    uma = json.loads((BASE / "patterns/freesewing-uma/uma-draft.json").read_text(encoding="utf-8"))
    for name, option in uma["options"].items():
        assert option["min"] <= option["default"] <= option["max"], name
    assert uma["options"]["gussetLength"]["default"] == 0.127
    assert uma["options"]["xStretch"]["default"] == 0.15
