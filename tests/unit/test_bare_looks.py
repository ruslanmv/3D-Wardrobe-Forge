"""AB1. After Dark · Bare: named bare looks, private, valid, and buildable as they are written."""

import json
import re
from pathlib import Path

from wardrobe.registry import bare_looks, classify, registry

ROOT = Path(__file__).resolve().parents[2] / "assets" / "body_detail"
RAW = json.loads((ROOT / "bare_looks.json").read_text(encoding="utf-8"))


def test_every_written_look_is_one_forge_can_paint():
    # The loader drops what it cannot paint; nothing written in the file may be dropped.
    assert set(bare_looks.load()["looks"]) == set(RAW["looks"])


def test_every_chapter_has_looks_and_every_preset_is_used():
    looks = RAW["looks"].values()
    assert {c["id"] for c in RAW["chapters"]} == {v["chapter"] for v in looks}
    presets = set(json.loads((ROOT / "presets.json").read_text())["presets"]) - {"porcelain", "anime"}
    assert presets <= {v["preset"] for v in looks}


def test_no_young_coded_words_in_any_name_or_description():
    banned = re.compile(r"\b(teen|young|girl|school|loli|petite|little|baby|kid|minor|virgin)\b", re.I)
    text = json.dumps(RAW)
    assert not banned.search(text)


def test_listed_privately_by_chapter():
    ids = [c.id for c in classify.AFTER_DARK_BARE]
    assert ids[0] == "ad-bare" and len(ids) == 1 + len(RAW["chapters"])
    assert all(c.private and c.section == "private-after-dark" for c in classify.AFTER_DARK_BARE)
    items = [i for i in registry.body_items() if i["bodyKind"] == "look"]
    assert len(items) == len(RAW["looks"])
    assert all(i["private"] and i["adult"] for i in items)


def test_job_options_are_a_bare_job():
    spec = RAW["looks"]["used-every-way"]
    options = bare_looks.job_options(spec)
    assert options["baseBody"] == "bare"
    assert options["bareDetail"] == spec["preset"]
    assert options["bareStates"] == ["closed", spec["state"]]
    assert options["bareExtras"] == spec["extras"]


def test_a_look_naming_something_forge_cannot_paint_is_refused():
    problems = bare_looks.problems_of(
        {"label": "x", "chapter": "ready", "preset": "natural", "state": "nope", "extras": ["nope"]},
        {"natural"}, {"open"}, {"spanked"}, {"ready"},
    )
    assert any("state" in p for p in problems) and any("extras" in p for p in problems)
