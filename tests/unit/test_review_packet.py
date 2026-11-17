"""RP1. The review packet prepares a person's review and never makes it.

The registry of adult-design reviews gates the bare body state, and only a person fills it. The
tool that gathers what a reviewer needs must therefore never be a way to fill it: these tests
hold that it writes no outcome, no reviewer, no registry, and reports the operator's declaration
as a declaration. The file is a committed library character; only its clothed, as-authored
bytes are read.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path

import pytest

from wardrobe.body_surface import gate
from wardrobe.config import Settings
from wardrobe.library import AvatarLibrary

ROOT = Path(__file__).resolve().parents[2]
SLUG = "vroid-avatar-sample-o"
REGISTRY = ROOT / "assets" / "body_surface" / "adult-design-reviews.json"


def _tool():
    spec = importlib.util.spec_from_file_location("review_packet", ROOT / "tools/body_surface/review_packet.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def library() -> AvatarLibrary:
    found = AvatarLibrary.from_directory(ROOT / "assets" / "library")
    if found.get(SLUG) is None or not found.get(SLUG).available:
        pytest.skip("library file not present")
    return found


def _without_reviews(folder: Path) -> Settings:
    """Settings over a copy of the body-surface folder whose registry holds no review: these
    tests describe an unreviewed file, whatever the operator's committed registry records."""
    import shutil

    root = folder / "body_surface"
    shutil.copytree(ROOT / "assets" / "body_surface", root)
    data = json.loads((root / "adult-design-reviews.json").read_text(encoding="utf-8"))
    data["reviews"] = {}
    (root / "adult-design-reviews.json").write_text(json.dumps(data), encoding="utf-8")
    return Settings(_env_file=None, wardrobe_body_surface_root=str(root))


@pytest.fixture(scope="module")
def made(library, tmp_path_factory):
    tool = _tool()
    path = Path(library.get(SLUG).path)
    sheets = tmp_path_factory.mktemp("sheets")
    (sheets / "01-original-front.png").write_bytes(b"front picture bytes")
    (sheets / "01-original-back.png").write_bytes(b"back picture bytes")
    (sheets / "notes.txt").write_text("not a picture")
    settings = _without_reviews(tmp_path_factory.mktemp("registry"))
    return tool, path, tool.packet(path, slug=SLUG, library=library, settings=settings,
                                   sheet_dir=sheets)


def test_the_packet_names_the_exact_file_by_the_registry_key(made, library):
    _tool_module, path, packet = made
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    assert packet["file"]["sha256"] == digest == packet["reviewEntry"]["key"]
    assert packet["file"]["matchesLibraryPin"] is True and packet["file"]["libraryPin"] == library.get(SLUG).sha256
    assert packet["reviewEntry"]["registry"] == "assets/body_surface/adult-design-reviews.json"
    assert packet["reviewEntry"]["schema"] == gate.REVIEWS_SCHEMA
    assert packet["identity"]["humanoidBones"] >= 15 and packet["identity"]["faceAndHairPrimitives"] > 0


def test_the_packet_records_no_finding_and_is_not_a_review(made, tmp_path):
    """Every field a reviewer fills is empty, and an entry like that opens nothing."""
    _tool_module, _path, packet = made
    entry = packet["reviewEntry"]["entry"]
    assert set(entry) == set(gate.REVIEW_FIELDS) and all(value == "" for value in entry.values())
    registry = tmp_path / "adult-design-reviews.json"
    registry.write_text(json.dumps({"schema": gate.REVIEWS_SCHEMA,
                                    "reviews": {packet["reviewEntry"]["key"]: entry}}))
    assert gate.design_review(tmp_path, packet["reviewEntry"]["key"]) is None
    text = json.dumps(packet).lower()
    for word in ("approved", "recommend", "score", "looks adult", "appears adult"):
        assert word not in text


def test_a_declaration_is_reported_as_a_declaration_and_changes_nothing(made):
    _tool_module, _path, packet = made
    assert "not a review" in packet["operatorDeclaration"]["note"]
    checks = packet["eligibilityNow"]["checks"]
    assert set(checks) == {"author-permission", "operator-switch", "adult-declaration", "design-clearance",
                           "private-session"}
    # With no review recorded, design clearance is closed whatever was declared.
    assert checks["design-clearance"]["passed"] is False and packet["eligibilityNow"]["allowed"] is False


def test_the_pictures_reviewed_are_listed_by_hash(made):
    _tool_module, _path, packet = made
    files = {f["file"]: f for f in packet["referencePictures"]["files"]}
    assert set(files) == {"01-original-front.png", "01-original-back.png"}
    assert files["01-original-front.png"]["sha256"] == hashlib.sha256(b"front picture bytes").hexdigest()
    assert files["01-original-front.png"]["view"] == "front" and files["01-original-back.png"]["view"] == "back"


def test_the_tool_writes_outside_the_repository_and_never_the_registry(library, tmp_path):
    tool = _tool()
    before = REGISTRY.read_bytes()
    with pytest.raises(SystemExit):
        tool.main(["--slug", SLUG, "--out", str(ROOT / "docs" / "qa" / "review")])
    with pytest.raises(SystemExit):
        tool.main(["--out", str(tmp_path)])  # neither a slug nor a file
    assert tool.main(["--slug", SLUG, "--out", str(tmp_path / "packet")]) == 0
    assert REGISTRY.read_bytes() == before  # the tool never writes the registry
    written = (tmp_path / "packet" / "packet.md").read_text()
    assert "records no finding" in written and '"outcome": ""' in written
    assert json.loads((tmp_path / "packet" / "packet.json").read_text())["reviewEntry"]["entry"]["reviewer"] == ""


def test_the_inventory_lists_every_library_character_and_decides_nothing(library, tmp_path):
    """RP2. One row per character, from the clothed source files. No row says a review exists
    (the registry is empty), a file that is not on this disk gets a row that says so, and the
    registry is not touched."""
    tool = _tool()
    before = REGISTRY.read_bytes()
    rows = tool.inventory(library, _without_reviews(tmp_path))
    assert {row["slug"] for row in rows} == {avatar.slug for avatar in library.avatars} and len(rows) == 8
    here = [row for row in rows if row["present"]]
    assert SLUG in {row["slug"] for row in here}
    for row in here:
        assert row["sha256"] == row["libraryPin"] and row["matchesLibraryPin"]
        assert row["reviewRecorded"] is False
        assert row["humanoidBones"] >= 15 and row["expressions"] > 0 and row["faceAndHairPrimitives"] > 0
    table = tool.inventory_markdown(rows)
    assert table.count("\n") == len(rows) + 2 and "none recorded" in table
    assert "clearly" not in table.lower()  # it reports a record's absence, never a finding
    for row in rows:
        if not row["present"]:
            assert "not on this disk" in table
    assert REGISTRY.read_bytes() == before
