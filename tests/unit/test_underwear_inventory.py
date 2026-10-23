"""The 28 original underwear templates stay exactly as recorded.

The adult catalog renders the inventory it was given. A template that is hard to
fit or to photograph is fixed in the pipeline or the preview profile, never removed,
renamed or quietly simplified, so every recorded id must still load from the same
bytes.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from wardrobe.domain.garments import TemplateCatalog

ROOT = Path(__file__).resolve().parents[2]
INVENTORY = json.loads((ROOT / "assets/catalog/adult/underwear-inventory.json").read_text(encoding="utf-8"))


def test_the_inventory_records_all_28_originals():
    assert INVENTORY["count"] == len(INVENTORY["templates"]) == 28
    assert len({t["id"] for t in INVENTORY["templates"]}) == 28


def test_every_original_underwear_template_is_present_and_unchanged():
    catalog = TemplateCatalog.from_directory(ROOT / "assets/garment_templates")
    for recorded in INVENTORY["templates"]:
        template = catalog.get(recorded["id"])
        assert template is not None, f"{recorded['id']} was removed"
        assert template.category == "underwear" and template.name == recorded["name"]
        assert template.procedural_kind == recorded["proceduralKind"]
        data = (ROOT / recorded["file"]).read_bytes()
        assert hashlib.sha256(data).hexdigest() == recorded["sha256"], f"{recorded['id']} was edited"
