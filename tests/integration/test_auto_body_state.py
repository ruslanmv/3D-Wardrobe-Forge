"""CG6. Forge builds and imports a bare body-state file itself, only when the import check says yes.

On Rinna's real library file (committed: her clothing is painted on her skin). Without a review
of her file nothing is imported; with one, the file is built, checked and listed once, and a
second pass imports nothing more. The review here is a test fixture in a temporary copy of the
registry (``clear_design_for_test``), never the committed registry.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.conftest import clear_design_for_test
from wardrobe.body_surface import auto_body_state
from wardrobe.library import AvatarLibrary
from wardrobe.pipeline import prebuilt
from wardrobe.storage.object_store import LocalObjectStore

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def rinna():
    library = AvatarLibrary.from_directory(ROOT / "assets" / "library")
    avatar = library.get("vroid-rinna")
    if avatar is None or not avatar.available:
        pytest.skip("Rinna's library file is not here")
    return avatar


@pytest.mark.slow
async def test_waits_for_the_review_then_imports_once(rinna, settings):
    settings.wardrobe_adult_body_surface = True
    store = LocalObjectStore(settings.storage_root_path, settings)

    waiting = await auto_body_state.ensure(rinna, settings, store)
    assert waiting["status"] == "waiting" and waiting["reason"] == "not-permitted"
    assert (await prebuilt.read_list(store, rinna.slug)).get("looks", []) == []

    clear_design_for_test(settings, rinna.path.read_bytes())
    done = await auto_body_state.ensure(rinna, settings, store)
    assert done["status"] == "imported", done
    looks = (await prebuilt.read_list(store, rinna.slug))["looks"]
    assert len(looks) == 1
    assert looks[0]["wardrobeState"] == "bare" and looks[0]["sourceSha256"] == rinna.sha256
    assert looks[0]["private"] is True

    again = await auto_body_state.ensure(rinna, settings, store)
    assert again["status"] == "already-imported"


async def test_off_does_nothing(rinna, settings):
    settings.wardrobe_auto_body_states = False
    store = LocalObjectStore(settings.storage_root_path, settings)
    assert (await auto_body_state.ensure(rinna, settings, store))["status"] == "off"


@pytest.mark.slow
async def test_an_operators_withdrawal_stands(rinna, settings):
    """Codex review: a restart re-registered a withdrawn auto import and turned its receipt to
    restored. The operator's withdrawal of those exact bytes is never undone by Forge itself."""
    from wardrobe.storage import withdrawals

    settings.wardrobe_adult_body_surface = True
    store = LocalObjectStore(settings.storage_root_path, settings)
    clear_design_for_test(settings, rinna.path.read_bytes())
    done = await auto_body_state.ensure(rinna, settings, store)
    assert done["status"] == "imported", done
    await prebuilt.withdraw_import(store, rinna.slug, done["lookId"], withdrawn_by="operator")
    again = await auto_body_state.ensure(rinna, settings, store)
    assert again["status"] == "withdrawn"
    assert withdrawals.blocks(await withdrawals.read(store, done["lookId"]))


@pytest.mark.slow
async def test_the_reviewing_sessions_declaration_counts(rinna, settings):
    """Codex review: a character declared adult only in the admin session (as the manual import and
    the review row accept) got no automatic file after her review. The route passes that declaration."""
    from dataclasses import replace

    settings.wardrobe_adult_body_surface = True
    store = LocalObjectStore(settings.storage_root_path, settings)
    clear_design_for_test(settings, rinna.path.read_bytes())
    undeclared = replace(rinna, depicts_adult=False)
    assert (await auto_body_state.ensure(undeclared, settings, store))["status"] == "waiting"
    done = await auto_body_state.ensure(undeclared, settings, store, declared_adult=True)
    assert done["status"] == "imported", done
