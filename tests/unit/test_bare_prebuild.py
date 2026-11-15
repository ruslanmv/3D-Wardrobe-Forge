"""Bare prebuilds are explicitly selected, colourless and keep-existing."""
import importlib.util
from pathlib import Path

from apps.api.routes.catalog import garment_item, restricted

spec = importlib.util.spec_from_file_location("bare_prebuild", Path(__file__).parents[2] / "tools/prebuild.py")
prebuild = importlib.util.module_from_spec(spec)
spec.loader.exec_module(prebuild)


class Forge:
    token = "test-admin"

    def call(self, path, body=None):
        assert body is None, "keep-existing must never submit another job"
        if path == "/v1/library":
            return {"avatars": [{"slug": "a", "available": True, "depictsAdult": True}]}
        if path.startswith("/v1/catalog/"):
            return {"categories": [{"garments": [{"id": "body-bare-v1", "name": "Bare authored body",
                                                   "requiresAdult": True}]}]}
        return {"looks": [{"templateId": "body-bare-v1"}]}


def test_bare_template_restricted_and_colourless(template_catalog):
    t = template_catalog.get("body-bare-v1")
    assert not t.validate_semantics()
    assert restricted(t)
    item = garment_item(t)
    assert not item["supportsColor"]
    assert item["availableColors"] == item["prebuiltColors"] == []


def test_manual_only_one_per_character_and_keep_existing():
    forge = Forge()
    assert prebuild.plan(forge, None, None) == []
    pairs = prebuild.plan(forge, None, "body-bare-v1")
    assert len(pairs) == 1
    body = prebuild.job_body(pairs[0])
    assert body["options"]["baseBody"] == "bare"
    assert "ensureFoundation" not in body["options"]
    assert "color" not in body["outfit"]
    assert prebuild.build(forge, pairs[0], 10)["result"] == "present"
