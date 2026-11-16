"""WD1 over HTTP, on the dataset store: a withdrawn import stays withdrawn.

The Space's case end to end, with the dataset in memory (``FakeHub``, the fixture the publish
tests use): an operator imports a body state, it is published, and then it is withdrawn while
the hub is failing, retried, and looked for again by a new process over an empty disk, once
after a clean withdrawal and once after the dataset's old list and files have come back.

What must hold at every point after the first DELETE: her wardrobe does not list the look and
``/v1/assets`` serves it to no one, whether the bytes are still in the dataset or not.

The avatar is the calibration body with a test box on its head (``tests/support_body_state``),
as in ``test_body_state_api``: these tests exercise the mechanism.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import sys

import pytest

from apps.api.admin import AdminSessions, admin_sessions_dependency
from apps.api.dependencies import settings_dependency
from apps.api.main import app
from tests.integration.test_body_state_api import PASSWORD, SECRET, grant_for, permitting, sign_in, upload
from tests.integration.test_studio_api import make_client
from tests.library_support import write_library
from tests.support_body_state import edited, touch, with_head
from tests.unit.test_dataset_publish import FakeHub
from wardrobe.library import AvatarLibrary
from wardrobe.pipeline import prebuilt
from wardrobe.pipeline.orchestrator import Orchestrator
from wardrobe.storage.object_store import HfDatasetObjectStore


@pytest.fixture
def hub(monkeypatch):
    fake = FakeHub()
    fake.private = True  # BI4: a private look goes only to a dataset the hub says is private
    monkeypatch.setitem(sys.modules, "huggingface_hub", fake.module)
    monkeypatch.setitem(sys.modules, "huggingface_hub.utils", fake.module.utils)
    return fake


@pytest.fixture
def space(hub, monkeypatch, tmp_path, settings, vrm_bytes, template_catalog):
    """A Forge on the dataset store. ``space["start"]()`` is a process start: a new store over
    whatever is on disk, a new orchestrator, new admin sessions, nothing kept in memory."""
    mira = with_head(edited(vrm_bytes, permitting))
    settings.wardrobe_grant_secret = SECRET
    settings.wardrobe_hf_dataset = "me/looks"
    settings.wardrobe_hf_publish_every = 100
    settings.wardrobe_hf_publish_seconds = 3600
    library = AvatarLibrary.from_directory(
        write_library(tmp_path / "library", {"Mira.vrm": mira, "Nora.vrm": with_head(vrm_bytes)}))
    app.dependency_overrides[settings_dependency] = lambda: settings

    def start():
        store = HfDatasetObjectStore(tmp_path / "disk", settings)
        orchestrator = Orchestrator(settings=settings, store=store, catalog=template_catalog)
        admins = AdminSessions(PASSWORD, ttl_hours=1)
        app.dependency_overrides[admin_sessions_dependency] = lambda: admins
        return make_client(orchestrator, monkeypatch, library), store

    try:
        yield {"start": start, "mira": mira, "state": edited(mira, touch), "disk": tmp_path / "disk"}
    finally:
        app.dependency_overrides.pop(admin_sessions_dependency, None)
        app.dependency_overrides.pop(settings_dependency, None)


def _import_and_publish(client, store, space, hub) -> tuple[dict, str, str]:
    headers = sign_in(client)
    response = upload(client, headers, space["state"], state="lingerie",
                      source=hashlib.sha256(space["mira"]).hexdigest())
    assert response.status_code == 201, response.text
    look = response.json()["look"]
    client.portal.call(store.flush)
    assert f"looks/{look['lookId']}/look.vrm" in hub.files
    return headers, look["lookId"], look["vrmUrl"].split("/v1/", 1)[1]


def _listed(client, headers) -> list[str]:
    return [item["id"] for item in client.get("/v1/wardrobes/mira", headers=headers).json()["looks"]]


def test_a_withdrawal_survives_a_failing_hub_a_retry_and_a_restart_on_an_empty_disk(space, hub):
    client, store = space["start"]()
    with client:
        headers, look_id, url = _import_and_publish(client, store, space, hub)
        grant = grant_for(client, headers, "mira")
        assert look_id in _listed(client, grant) and client.get(f"/v1/{url}", headers=grant).status_code == 200
        files = sorted(name for name in hub.files if name.startswith(f"looks/{look_id}/"))
        assert len(files) == 3

        # The hub refuses the withdrawal's commit: incomplete, and said so.
        hub.fail_next = True
        first = client.delete(f"/v1/admin/library/mira/body-states/{look_id}", headers=headers)
        assert first.status_code == 503 and sorted(first.json()["detail"]["remaining"]) == files
        assert set(files) <= set(hub.files)  # the dataset still holds every byte
        # ... and nobody gets them: not a grant, not the admin session, not her wardrobe.
        assert look_id not in _listed(client, grant) and look_id not in _listed(client, headers)
        for who in ({}, grant, headers):
            assert client.get(f"/v1/{url}", headers=who).status_code == 404
        assert client.get("/v1/library/mira/prebuilt", headers=grant).json()["count"] == 0

        # Retry: finished. One commit took the files, her list line and added the receipt.
        assert client.delete(f"/v1/admin/library/mira/body-states/{look_id}", headers=headers).status_code == 204
        assert not set(files) & set(hub.files)
        assert json.loads(hub.files[f"withdrawn/{look_id}.json"])["state"] == "withdrawn"
        assert client.delete(f"/v1/admin/library/mira/body-states/{look_id}", headers=headers).status_code == 204

    # The Space restarts on an empty disk: everything it knows now comes from the dataset.
    shutil.rmtree(space["disk"])
    client, _store = space["start"]()
    with client:
        headers = sign_in(client)
        grant = grant_for(client, headers, "mira")
        assert look_id not in _listed(client, grant) and look_id not in _listed(client, headers)
        for who in ({}, grant, headers):
            assert client.get(f"/v1/{url}", headers=who).status_code == 404
        receipts = client.get("/v1/admin/library/mira/withdrawals", headers=headers).json()
        assert receipts["count"] == 1 and receipts["withdrawals"][0]["state"] == "withdrawn"
        assert receipts["withdrawals"][0]["attempts"] == 2
        assert client.get("/v1/admin/library/nora/withdrawals", headers=headers).json()["count"] == 0
        # A grant reads no receipts and withdraws nothing.
        assert client.get("/v1/admin/library/mira/withdrawals", headers=grant).status_code == 401
        assert client.delete(f"/v1/admin/library/mira/body-states/{look_id}", headers=grant).status_code == 401


def test_a_restart_carries_an_interrupted_withdrawal_on_and_undoes_a_stale_restore(space, hub):
    client, store = space["start"]()
    with client:
        headers, look_id, url = _import_and_publish(client, store, space, hub)
        list_key = prebuilt.wardrobe_key("mira")
        before = {name: data for name, data in hub.files.items()
                  if name.startswith(f"looks/{look_id}/") or name == list_key}
        hub.fail_next = True
        assert client.delete(f"/v1/admin/library/mira/body-states/{look_id}", headers=headers).status_code == 503
    # Shutdown published what was pending: the receipt (state "pending"). The files are still up.
    assert json.loads(hub.files[f"withdrawn/{look_id}.json"])["state"] == "pending"
    assert f"looks/{look_id}/look.vrm" in hub.files

    # Interrupted, then restarted on an empty disk: startup finishes it before serving anything.
    shutil.rmtree(space["disk"])
    client, _store = space["start"]()
    with client:
        assert not [name for name in hub.files if name.startswith(f"looks/{look_id}/")]
        assert json.loads(hub.files[f"withdrawn/{look_id}.json"])["state"] == "withdrawn"
        headers = sign_in(client)
        assert look_id not in _listed(client, headers)
        assert client.get(f"/v1/{url}", headers=headers).status_code == 404

    # The dataset's old list and files come back (a backup restored, a stale publisher).
    hub.files.update(before)
    shutil.rmtree(space["disk"])
    client, _store = space["start"]()
    with client:
        headers = sign_in(client)
        assert look_id not in _listed(client, headers)
        assert client.get(f"/v1/{url}", headers=headers).status_code == 404
        # ... and startup deleted them again: the receipt outlived the restore.
        assert not [name for name in hub.files if name.startswith(f"looks/{look_id}/")]
        assert look_id not in json.dumps(json.loads(hub.files[list_key])["looks"])
