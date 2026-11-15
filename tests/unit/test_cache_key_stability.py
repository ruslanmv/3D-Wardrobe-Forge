"""AA. New garments are additive: every look already in the dataset keeps its cache key.

The prebuilt dataset holds thousands of looks, each stored under ``prebuilt.cache_key``, which
hashes the template's JSON. Adding a field to ``GarmentTemplate`` or ``FitPolicy`` changes that
JSON for EVERY template, even one whose file nobody touched, and every existing look stops
being found: the Space generates on demand again and a prebuild makes them all twice.

``tests/fixtures/prebuilt_key_baseline.json`` was frozen from ultimate@0902b34, the state the
dataset's keys were written in. Never regenerate it. If one of these tests fails, the fix is
in the code (register the new field in ``ADDED_TEMPLATE_FIELDS`` / ``ADDED_FIT_FIELDS``), not
in the fixture.
"""

from __future__ import annotations

import json
from pathlib import Path

from tests.conftest import job_request
from wardrobe.domain.garments import FitPolicy, GarmentTemplate
from wardrobe.domain.jobs import CreateJobRequest
from wardrobe.pipeline import prebuilt

BASELINE = json.loads((Path(__file__).parents[1] / "fixtures" / "prebuilt_key_baseline.json").read_text())


def test_every_existing_template_hashes_as_it_did(template_catalog):
    changed = [
        template_id
        for template_id, digest in BASELINE["templateHashes"].items()
        if template_catalog.get(template_id) is None
        or prebuilt.template_fingerprint(template_catalog.get(template_id)) != digest
    ]
    assert changed == [], f"these existing looks would stop being found in the dataset: {changed}"


def test_existing_requests_keep_their_cache_keys(template_catalog):
    for case, expected in BASELINE["cacheKeys"].items():
        template_id, colour, privacy = case.split("|")
        request = CreateJobRequest.model_validate(
            job_request("library/fem-vroid/source.vrm", f"{colour} look", template_id=template_id,
                        color=colour, private=privacy == "private")
        )
        assert prebuilt.cache_key(request, template_catalog) == expected, case


def test_every_field_added_since_is_registered():
    """A new template field must be left out of the hash while it holds its old default."""
    new_template = set(GarmentTemplate.model_fields) - set(BASELINE["templateFields"])
    new_fit = set(FitPolicy.model_fields) - set(BASELINE["fitFields"])
    assert new_template <= set(prebuilt.ADDED_TEMPLATE_FIELDS), new_template - set(prebuilt.ADDED_TEMPLATE_FIELDS)
    assert new_fit <= set(prebuilt.ADDED_FIT_FIELDS), new_fit - set(prebuilt.ADDED_FIT_FIELDS)
    for name, default in prebuilt.ADDED_TEMPLATE_FIELDS.items():
        assert GarmentTemplate.model_fields[name].default == default, name
    for name, default in prebuilt.ADDED_FIT_FIELDS.items():
        assert FitPolicy.model_fields[name].default == default, name


def test_a_new_card_that_sets_a_new_field_is_still_hashed(template_catalog):
    """The exclusion is only for the old default: a slit, a finish or a sheer card counts."""
    bodystocking = template_catalog.get("jumpsuit-bodystocking-v1")
    assert bodystocking is not None and bodystocking.fit.pattern == "fishnet"
    plain = bodystocking.model_copy(update={"fit": bodystocking.fit.model_copy(update={"pattern": ""})})
    assert prebuilt.template_fingerprint(plain) != prebuilt.template_fingerprint(bodystocking)
