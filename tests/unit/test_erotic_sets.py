"""ES1–ES3. Erotic sets dressed over her bare body, and taking off only their top or bottom."""
import importlib.util
from pathlib import Path

import pytest

from wardrobe.domain.jobs import BARE_MODES, CreateJobRequest, JobOptions
from wardrobe.pipeline import outfit_dictionary as od


def _job(**options):
    return {"avatar": {"storageKey": "sources/a.vrm", "depictsAdult": True},
            "outfit": {"prompt": "black balconette bra + black thong"}, "options": options}


def test_bare_dressed_is_a_bare_mode_and_keeps_the_bare_guards():
    options = JobOptions.model_validate({"baseBody": "bare-dressed"})
    assert options.over_bare_body and "bare-dressed" in BARE_MODES
    assert not JobOptions.model_validate({"baseBody": "replace-outer"}).over_bare_body


def test_bare_dressed_takes_an_outfit_and_detail_but_no_added_foundation():
    CreateJobRequest.model_validate(_job(baseBody="bare-dressed", bareDetail="natural", bareState="aroused"))
    with pytest.raises(ValueError):
        CreateJobRequest.model_validate(_job(baseBody="bare-dressed", ensureFoundation=True))
    no_outfit = _job(baseBody="bare-dressed")
    no_outfit.pop("outfit")
    with pytest.raises(ValueError):
        CreateJobRequest.model_validate(no_outfit)


def test_erotic_sets_are_private_dressed_over_bare_and_say_what_comes_off(template_catalog):
    planned = {e["id"]: e for e in od.catalogue(template_catalog)["outfits"]}
    erotic = [o for o in od.OUTFITS if o.group == "erotic"]
    assert len(erotic) >= 10
    for outfit in erotic:
        entry = planned[outfit.id]
        assert entry["rating"] == "private"
        assert entry["options"] == {"baseBody": "bare-dressed"}
        assert all(g["template"] for g in entry["garments"] if g["category"] != "underwear")
    # A two-piece set can lose either half alone; a one-piece cannot.
    assert planned["erotic-boudoir"]["partial"] == ["bottom", "top"]
    assert planned["erotic-micro-bikini"]["partial"] == ["bottom", "top"]
    assert planned["erotic-fishnet"]["partial"] == []
    # Entries that dress her as she is carry no options key at all (additive for old clients).
    assert "options" not in planned["lace-lingerie-set"]


def _prebuild():
    path = Path(__file__).parents[2] / "tools" / "prebuild.py"
    spec = importlib.util.spec_from_file_location("prebuild_tool", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_prebuild_sends_an_erotic_set_over_bare_without_an_added_foundation():
    body = _prebuild().job_body({"templateId": "outfit:erotic-boudoir", "outfit": {"prompt": "x"},
                                 "options": {"baseBody": "bare-dressed"}})
    assert body["options"]["baseBody"] == "bare-dressed" and "ensureFoundation" not in body["options"]
    plain = _prebuild().job_body({"templateId": "outfit:x", "outfit": {"prompt": "x"}})
    assert plain["options"]["ensureFoundation"] is True
