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
            # As the real route answers since AF5: body modes are not listed as garments (BE3).
            return {"categories": [{"garments": [{"id": "under-briefs-v2", "name": "Briefs"}]}]}
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
    assert not [p for p in prebuild.plan(forge, None, None) if p["templateId"] == "body-bare-v1"]
    pairs = prebuild.plan(forge, None, "body-bare-v1")
    assert len(pairs) == 1
    body = prebuild.job_body(pairs[0])
    assert body["options"]["baseBody"] == "bare"
    assert "ensureFoundation" not in body["options"]
    assert "color" not in body["outfit"]
    assert prebuild.build(forge, pairs[0], 10)["result"] == "present"


def test_the_real_catalogue_route_omits_body_modes_and_bare_is_still_planned(template_catalog):
    """BE3. The operator's bare prebuild planned 0 looks against a real Forge: the catalogue it
    planned from leaves body modes out. Bare is planned per character, without the listing."""
    from apps.api.routes.catalog import garment_item

    listed = {garment_item(t)["id"] for t in template_catalog.all() if not t.is_body_mode}
    assert "body-bare-v1" not in listed

    class Library(Forge):
        def call(self, path, body=None):
            if path == "/v1/library":
                return {"avatars": [{"slug": "a", "available": True, "depictsAdult": True},
                                    {"slug": "b", "available": True},
                                    {"slug": "c", "available": False, "depictsAdult": True}]}
            raise AssertionError(f"bare planning must not need {path}")

    pairs = prebuild.plan(Library(), None, "body-bare-v1")
    assert [(p["slug"], p.get("skip")) for p in pairs] == [
        ("a", None), ("b", "the bare body needs a character declared adult")]
