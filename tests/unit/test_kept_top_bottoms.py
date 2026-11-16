"""KL3. Selective regeneration: only the cached looks the old rules built are named, by their own keys.

``PIPELINE_VERSION`` is not bumped (every key in the dataset stays valid:
``test_cache_key_stability``), so a look cached before KL3 is served as it was until it is rebuilt.
``tools/kept_top_bottoms.py`` reads the wardrobe lists and the stored fit reports and names
exactly those. The characters are the committed library's: AvatarSample O keeps a top of her
own, Rinna wears nothing Forge recognises.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

from wardrobe.geometry import kept_layers
from wardrobe.library import AvatarLibrary
from wardrobe.pipeline import prebuilt

ROOT = Path(__file__).resolve().parents[2]
KEEPS_A_TOP, NO_TOP = "vroid-avatar-sample-o", "vroid-rinna"


def _tool():
    spec = importlib.util.spec_from_file_location("kept_top_bottoms", ROOT / "tools/kept_top_bottoms.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def library() -> AvatarLibrary:
    found = AvatarLibrary.from_directory(ROOT / "assets" / "library")
    if found.get(KEEPS_A_TOP) is None or not found.get(KEEPS_A_TOP).available:
        pytest.skip("library file not present")
    return found


def _item(key: str, template: str | None, **extra) -> dict:
    return {"key": key, "templateId": template, "color": "black", "lookId": f"look_{key}", "private": False,
            **extra}


def _dataset(root: Path, lists: dict[str, list[dict]], tucks: dict[str, dict | None]) -> Path:
    """A storage root as the dataset holds it: wardrobe lists, and an entry per key with its report."""
    for slug, items in lists.items():
        path = root / prebuilt.wardrobe_key(slug)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"wardrobeId": slug, "looks": items}))
    for key, tuck in tucks.items():
        report = {"passed": True, **({"keptTopTuck": tuck} if tuck is not None else {})}
        (root / "prebuilt" / f"{key}.json").write_text(json.dumps({"record": {"fitReport": report}}))
    return root


CURRENT = {"moved": 181, "noRoom": 0, "version": kept_layers.VERSION}
KL1 = {"moved": 159, "noRoom": 6, "hiddenUnderTop": 124}  # as KL1 wrote it: no version


def test_only_looks_built_by_older_rules_are_named(tmp_path, library, template_catalog):
    tool = _tool()
    root = _dataset(tmp_path, {
        KEEPS_A_TOP: [
            _item("pre-kl1", "jeans-straight-v1"),                 # no keptTopTuck at all
            _item("kl1", "skirt-pencil-v1"),                       # KL1: the front-hem band
            _item("kl3", "shorts-denim-v1"),                       # current: left alone
            _item("no-entry", "trousers-slim-v1"),                 # cannot be told: named
            _item("dress", "dress-mini-bodycon-v1"),               # not a bottom under a top
            _item("outfit", None, plan="plan-abc"),                # several garments, never tucked
            _item("import", None, origin="operator-import", plan="import-x"),
        ],
        NO_TOP: [
            _item("rinna-jeans", "jeans-straight-v1"),             # no top of her own: not affected
            _item("rinna-waspie", "under-waspie-v1", private=True),  # KL2: tucked under a bralette
            _item("rinna-briefs", "under-briefs-v2", private=True),  # the old pass moved nothing
        ],
    }, {"pre-kl1": None, "kl1": KL1, "kl3": CURRENT, "dress": None, "outfit": None,
        "rinna-jeans": None, "rinna-waspie": {"moved": 59, "noRoom": 0, "hiddenUnderTop": 59},
        "rinna-briefs": {"moved": 0, "noRoom": 0}})
    named = {p["key"]: p for p in tool.affected(library, template_catalog, root, root)}
    assert set(named) == {"pre-kl1", "kl1", "no-entry", "rinna-waspie"}
    assert "before KL1" in named["pre-kl1"]["evidence"]
    assert named["kl1"]["evidence"] == f"keptTopTuck version 1, current is {kept_layers.VERSION}"
    assert named["rinna-waspie"]["private"] is True and "moved 59" in named["rinna-waspie"]["evidence"]
    # Public only: the private one is left for a run with an admin token.
    public = tool.affected(library, template_catalog, root, root, include_private=False)
    assert {p["key"] for p in public} == {"pre-kl1", "kl1", "no-entry"}


def test_a_rebuilt_look_is_no_longer_named_and_its_key_did_not_move(tmp_path, library, template_catalog):
    """The whole loop: name it, rebuild it under the same key, name nothing."""
    tool = _tool()
    root = _dataset(tmp_path, {KEEPS_A_TOP: [_item("kl1", "jeans-straight-v1")]}, {"kl1": KL1})
    assert [p["key"] for p in tool.affected(library, template_catalog, root, root)] == ["kl1"]
    # tools/prebuild.py on a fresh Forge writes the same key (PIPELINE_VERSION unchanged) with
    # the new report; tools/publish_prebuilt.py --overwrite replaces exactly that entry.
    _dataset(tmp_path, {}, {"kl1": CURRENT})
    assert tool.affected(library, template_catalog, root, root) == []
    assert prebuilt.PIPELINE_VERSION == 1


def test_the_commands_name_each_character_and_template_once(tmp_path, library, template_catalog, capsys,
                                                             monkeypatch):
    tool = _tool()
    root = _dataset(tmp_path, {
        KEEPS_A_TOP: [_item("a", "jeans-straight-v1"), _item("b", "jeans-straight-v1", color="blue"),
                      _item("c", "skirt-pencil-v1")],
        NO_TOP: [_item("w", "under-waspie-v1", private=True)],
    }, {"a": KL1, "b": KL1, "c": None, "w": {"moved": 3}})
    monkeypatch.setattr(tool, "get_settings", lambda: type("S", (), {
        "wardrobe_library_root": ROOT / "assets" / "library",
        "wardrobe_template_root": ROOT / "assets" / "garment_templates"})())
    assert tool.main(["--lists", str(root), "--entries", str(root)]) == 0
    out = capsys.readouterr().out
    assert "4 looks on 2 characters" in out
    assert out.count(f"--slugs {KEEPS_A_TOP} --only jeans-straight-v1") == 1
    assert f"--slugs {KEEPS_A_TOP} --only skirt-pencil-v1" in out
    assert f"--slugs {NO_TOP} --only under-waspie-v1 --admin-token-file" in out
    assert "publish_prebuilt.py" in out and "--overwrite" in out
