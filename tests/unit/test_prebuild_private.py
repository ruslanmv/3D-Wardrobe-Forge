"""BD21. The private-look generator: every state made, in packs Forge accepts, never a rebuild."""

import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).parents[2]
spec = importlib.util.spec_from_file_location("prebuild_private", ROOT / "tools/prebuild_private.py")
pp = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pp)

STATES = list(json.loads((ROOT / "assets/body_detail/states.json").read_text())["states"])
EXTRAS = set(json.loads((ROOT / "assets/body_detail/extras.json").read_text())["extras"])


def test_every_state_is_in_a_pack_forge_accepts():
    packs = pp.state_groups(STATES)
    assert {s for states in packs.values() for s in states} == set(STATES)
    for states in packs.values():
        assert states[0] == "closed" and len(states) <= pp.MAX_STATES and len(set(states)) == len(states)


def test_a_state_forge_adds_later_is_still_made():
    packs = pp.state_groups(STATES + [f"new-state-{i}" for i in range(12)])
    assert "other" in packs and "other-2" in packs
    assert sum(len(v) - 1 for k, v in packs.items() if k.startswith("other")) == 12


def test_extras_sets_are_real_and_within_the_limit():
    for extras in pp.EXTRAS_SETS.values():
        assert set(extras) <= EXTRAS and len(extras) <= pp.MAX_EXTRAS


def test_plan_skips_a_character_not_declared_adult_and_sends_the_studio_body():
    packs = pp.state_groups(STATES)
    pairs = pp.plan([{"slug": "a", "depictsAdult": True}, {"slug": "b"}], ["natural"], packs, pp.EXTRAS_SETS)
    assert all(p.get("skip") for p in pairs if p["slug"] == "b")
    assert not any(p.get("skip") for p in pairs if p["slug"] == "a")
    body = pp.job_body(next(p for p in pairs if p["extras"]))
    assert body["outfit"]["templateId"] == "body-bare-v1"
    assert body["options"]["baseBody"] == "bare" and body["options"]["bareDetail"] == "natural"
    assert body["options"]["bareStates"] and body["options"]["bareExtras"]


class Forge:
    def __init__(self):
        self.sent = []

    def call(self, path, body=None):
        if body is not None:
            self.sent.append(body)
            return {"id": "j1", "state": "rejected", "reason": "body_surface_not_permitted", "error": "no"}
        return {"looks": [{"body": {"detail": "natural", "states": ["open", "closed"], "extras": []}}]}


def test_a_listed_body_is_not_rebuilt_and_a_gate_refusal_is_reported_not_failed():
    forge = Forge()
    held = pp.listed(forge, "a")
    present = pp.build(
        forge,
        {"slug": "a", "preset": "natural", "look": "x", "states": ["closed", "open"], "extras": []},
        held,
        10,
    )
    assert present["result"] == "present" and not forge.sent
    refused = pp.build(
        forge,
        {"slug": "a", "preset": "natural", "look": "y", "states": ["closed", "cum"], "extras": []},
        held,
        10,
    )
    assert refused["result"] == "refused" and refused["reasonCode"] == "body_surface_not_permitted"


def test_the_prebuild_workflow_can_make_the_private_looks():
    import yaml

    flow = yaml.safe_load((ROOT / ".github/workflows/prebuild-wardrobe.yml").read_text())
    inputs = (
        flow[True]["workflow_dispatch"]["inputs"]
        if True in flow
        else flow["on"]["workflow_dispatch"]["inputs"]
    )
    # A drop-down (GitHub's phone site shows no tick box): "yes" by default, so one click on
    # Prebuild wardrobe makes the private looks (the owner's choice, 2026-11-20).
    assert inputs["private_looks"]["type"] == "choice" and set(inputs["private_looks"]["options"]) == {"yes", "no"}
    steps = flow["jobs"]["build"]["steps"]
    step = next(s for s in steps if s.get("name", "").startswith("Private looks"))
    assert "tools/prebuild_private.py" in step["run"] and "--admin-token-file" in step["run"]
    assert step["if"] == "inputs.private_looks == 'yes'"


def test_the_studio_opens_the_collections_browser():
    html = (ROOT / "apps/studio/index.html").read_text()
    assert 'id="collections-btn"' in html and 'id="registry-dialog"' in html
    app = (ROOT / "apps/studio/js/app.js").read_text()
    assert "initCollections(" in app and "./collections.js" in app
    page = (ROOT / "apps/studio/js/collections.js").read_text()
    # The page never decides what is private: it draws what the registry answers for this caller.
    for call in ("registry(", "registryAssign", "registryFavourite", "registryCreate"):
        assert call in page


def test_bd25_repaint_takes_only_open_detailed_looks_built_before_the_fix():
    opened = pp.anus_open_of()
    assert opened["doggy-anal-fisted"] >= 0.5 and opened["closed"] == 0
    looks = [
        # Open and old: painted again, exactly as asked (preset, states, extras).
        {"lookId": "a", "builtAt": "2026-11-21T01:00:00+00:00",
         "body": {"detail": "natural", "states": ["closed", "doggy-anal-fisted"], "extras": ["glitter"]}},
        # Open but built after the fix: kept.
        {"lookId": "b", "builtAt": "2026-11-21T09:00:00+00:00",
         "body": {"detail": "natural", "states": ["closed", "doggy-anal-fisted"], "extras": []}},
        # Old but closed: kept.
        {"lookId": "c", "builtAt": "2026-11-21T01:00:00+00:00",
         "body": {"detail": "natural", "states": ["closed", "aroused"], "extras": []}},
        # Not a detailed look (an outfit, a plain bare body): never.
        {"lookId": "d", "builtAt": "2026-11-21T01:00:00+00:00"},
        {"lookId": "e", "builtAt": "2026-11-21T01:00:00+00:00", "body": {"states": ["doggy-anal-fisted"]}},
    ]
    pairs = pp.repaint_plan(looks, "avatar-sample-a", "2026-11-21T08:00:00", 0.5, opened)
    assert [p["look"] for p in pairs] == ["repaint:a"]
    assert pairs[0]["preset"] == "natural" and pairs[0]["extras"] == ["glitter"]
    assert pairs[0]["states"] == ["closed", "doggy-anal-fisted"]
    # A repaint is built even though its body is listed (that is the point of it).
    assert pairs[0]["repaint"] is True
