"""scripts/download.py, offline: configuration, sign-in plumbing, licence rules, the file.

The network half (VRoid Hub's API and its presigned downloads) needs a signed-in
account and is exercised by running the script; everything it decides is here.
"""

from __future__ import annotations

import importlib.util
import json
import threading
import time
import urllib.request
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("vroid_download", ROOT / "scripts" / "download.py")
dl = importlib.util.module_from_spec(spec)
spec.loader.exec_module(dl)


def vrm1(**meta):
    base = {"allowRedistribution": True, "modification": "allowModificationRedistribution",
            "avatarPermission": "everyone", "commercialUsage": "corporation", "creditNotation": "unnecessary"}
    return {"is_downloadable": True, "is_other_users_available": True,
            "latest_character_model_version": {"spec_version": "1.0", "vrm_meta": {**base, **meta}},
            "character": {"id": "1", "name": "Helen", "user": {"name": "Mhiyamin"}}, "id": "359"}


def vrm0(**licence):
    base = {"redistribution": "allow", "modification": "allow", "characterization_allowed_user": "everyone"}
    return {"is_downloadable": True, "is_other_users_available": True, "license": {**base, **licence},
            "latest_character_model_version": {"spec_version": "0.0", "vrm_meta": {}}}


# ---------------------------------------------------------------- configuration
def test_env_file_is_read_and_the_environment_wins(tmp_path):
    env = tmp_path / ".env"
    env.write_text('# app\nVROID_CLIENT_ID="abc"\nexport VROID_SCOPE=default  # comment\n'
                   "VROID_CLIENT_SECRET='s p'\nWARDROBE_ENGINE=native\n", encoding="utf-8")
    config = dl.read_env(env, environ={"VROID_CLIENT_ID": "from-env", "VROID_ACCESS_TOKEN": "t"})
    assert config["VROID_CLIENT_ID"] == "from-env"
    assert config["VROID_SCOPE"] == "default" and config["VROID_CLIENT_SECRET"] == "s p"
    assert config["VROID_ACCESS_TOKEN"] == "t"
    assert dl.read_env(tmp_path / "missing", environ={}) == {}


def test_the_model_list_is_complete_and_filterable():
    models = dl.load_models()
    assert len(models) == 9 and len({m["slug"] for m in models}) == 9
    assert all(m["modelId"].isdigit() and m["presentation"] in {"feminine", "masculine"} for m in models)
    assert [m["slug"] for m in dl.load_models(only={"vroid-helen"})] == ["vroid-helen"]
    with pytest.raises(dl.DownloadError, match="not in"):
        dl.load_models(only={"nobody"})


# ---------------------------------------------------------------- sign-in
def test_pkce_is_s256_of_a_valid_verifier():
    import base64
    import hashlib

    verifier, challenge = dl.pkce_pair()
    assert 43 <= len(verifier) <= 128 and set(verifier) <= set(
        "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-._~")
    assert challenge == base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()


def test_the_authorize_url_carries_everything_vroid_hub_requires():
    config = {"VROID_CLIENT_ID": "id", "VROID_REDIRECT_URI": dl.DEFAULT_REDIRECT, "VROID_SCOPE": "default"}
    url = dl.authorize_url(config, "st", "ch")
    for part in ("response_type=code", "client_id=id", "scope=default", "state=st", "code_challenge=ch",
                 "code_challenge_method=S256", "redirect_uri=http%3A%2F%2Flocalhost%3A18927%2Fcallback"):
        assert part in url
    assert "secret" not in url


def test_a_redirect_is_accepted_only_with_its_own_state():
    assert dl.code_from_redirect("http://localhost:18927/callback?code=C&state=S", "S") == "C"
    with pytest.raises(dl.DownloadError, match="state"):
        dl.code_from_redirect("http://localhost:18927/callback?code=C&state=other", "S")
    with pytest.raises(dl.DownloadError, match="refused"):
        dl.code_from_redirect("http://localhost:18927/callback?error=access_denied&state=S", "S")


def test_the_local_redirect_is_caught_once(unused_port):
    redirect = f"http://127.0.0.1:{unused_port}/callback"
    result = {}
    thread = threading.Thread(target=lambda: result.setdefault("code", dl._wait_for_redirect(redirect, "S")))
    thread.start()
    for _ in range(50):
        try:
            body = urllib.request.urlopen(f"{redirect}?code=THE-CODE&state=S", timeout=2).read().decode()
            break
        except OSError:
            time.sleep(0.1)
    thread.join(timeout=10)
    assert result["code"] == "THE-CODE" and "Signed in" in body


@pytest.fixture
def unused_port():
    import socket

    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


# ---------------------------------------------------------------- licences
def test_a_vrm1_model_that_allows_both_passes_with_its_terms_recorded():
    summary, problems = dl.evaluate(vrm1(otherLicenseUrl="example.com/terms"))
    assert problems == []
    assert summary["redistribution"] is True and summary["spec"] == "1.0"
    assert summary["otherLicenseUrl"] == "example.com/terms"


@pytest.mark.parametrize(("meta", "reason"), [
    ({"allowRedistribution": False}, "redistribution"),
    ({"modification": "prohibited"}, "modification"),
])
def test_a_vrm1_model_that_forbids_either_is_refused(meta, reason):
    assert any(reason in p for p in dl.evaluate(vrm1(**meta))[1])


def test_a_vrm0_model_reads_the_hub_licence_and_its_own_page_is_not_extra_terms():
    model = vrm0()
    model["latest_character_model_version"]["vrm_meta"] = {"otherLicenseUrl": f"{dl.HUB}/license?redistribution=allow"}
    summary, problems = dl.evaluate(model)
    assert problems == [] and summary["otherLicenseUrl"] is None and summary["conditionsUrl"]
    assert any("redistribution" in p for p in dl.evaluate(vrm0(redistribution="disallow"))[1])
    assert any("modification" in p for p in dl.evaluate(vrm0(modification="disallow"))[1])


def test_a_model_that_cannot_be_downloaded_or_used_by_others_is_refused():
    model = vrm1()
    model.update(is_downloadable=False, is_other_users_available=False)
    problems = dl.evaluate(model)[1]
    assert any("downloads" in p for p in problems) and any("other users" in p for p in problems)


def test_the_snapshot_names_the_creator_and_the_source():
    record = dl.snapshot({"slug": "vroid-helen", "name": "Helen", "modelId": "359"}, vrm1(), {"spec": "1.0"})
    assert record["creator"] == "Mhiyamin"
    assert record["source"].endswith("/characters/1/models/359") and record["checkedAtUtc"]


# ---------------------------------------------------------------- the file
def test_a_real_vrm_is_read_and_its_embedded_licence_reported(tmp_path):
    from wardrobe.vrm.build import CALIBRATION_BODIES, build_vrm

    path = tmp_path / "body.vrm"
    path.write_bytes(build_vrm(CALIBRATION_BODIES[0], spec="VRM1"))
    embedded = dl.embedded_licence(dl.glb_json(path))
    assert embedded["spec"] == "1.0"
    bad = tmp_path / "bad.vrm"
    bad.write_bytes(b"<html>expired</html>")
    with pytest.raises(dl.DownloadError, match="not a glTF"):
        dl.glb_json(bad)


def test_the_manifest_merges_by_slug(tmp_path):
    dl.write_manifest(tmp_path, [{"slug": "b", "bytes": 1}, {"slug": "a", "bytes": 1}])
    dl.write_manifest(tmp_path, [{"slug": "b", "bytes": 2}])
    items = json.loads((tmp_path / "models.json").read_text())["items"]
    assert [(i["slug"], i["bytes"]) for i in items] == [("a", 1), ("b", 2)]


def _fake_hub(monkeypatch, body: bytes):
    calls = []

    def request(method, url, *, token=None, form=None, body=None, redirects=True):
        calls.append((method, url.replace(dl.HUB, ""), token, redirects))
        if url.endswith("/api/download_licenses"):
            return 200, {}, json.dumps({"data": {"id": "L1"}}).encode()
        if url.endswith("/download"):
            return 302, {"Location": "https://s3.example/file?sig=1"}, b""
        return 200, {}, b"{}"

    class Response:
        def __init__(self, data):
            self.data = data

        def __enter__(self):
            import io

            return io.BytesIO(self.data)

        def __exit__(self, *exc):
            return False

    fetched = []

    def urlopen(url, timeout=None):
        fetched.append(url)
        return Response(body)

    monkeypatch.setattr(dl, "_request", request)
    monkeypatch.setattr(dl.urllib.request, "urlopen", urlopen)
    return calls, fetched


def test_a_download_follows_the_redirect_without_the_token_and_invalidates_the_licence(tmp_path, monkeypatch):
    from wardrobe.vrm.build import CALIBRATION_BODIES, build_vrm

    calls, fetched = _fake_hub(monkeypatch, build_vrm(CALIBRATION_BODIES[0], spec="VRM1"))
    target = dl.download({"slug": "vroid-helen", "modelId": "359"}, "TOKEN", tmp_path)
    assert target == tmp_path / "vroid-helen.vrm" and dl.glb_json(target)
    assert fetched == ["https://s3.example/file?sig=1"]  # plain urlopen: no bearer to the presigned URL
    assert ("GET", "/api/download_licenses/L1/download", "TOKEN", False) in calls  # redirect not followed
    assert calls[-1][:2] == ("DELETE", "/api/download_licenses/L1")
    assert not list(tmp_path.glob("*.part"))


def test_a_download_that_is_not_a_vrm_leaves_nothing_behind(tmp_path, monkeypatch):
    calls, _ = _fake_hub(monkeypatch, b"<Error>AccessDenied</Error>")
    with pytest.raises(dl.DownloadError, match="not a glTF"):
        dl.download({"slug": "vroid-helen", "modelId": "359"}, "TOKEN", tmp_path)
    assert not list(tmp_path.iterdir())
    assert calls[-1][0] == "DELETE"  # the licence is invalidated even when the file is bad
