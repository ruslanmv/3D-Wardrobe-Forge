"""Provider selection and response-shape parsing.

No network here: these tests pin the payload shapes the adapters expect, so a
breaking change upstream shows up as a failing parse rather than a failed user
job. The nightly workflow runs the same adapters against the live APIs.
"""

from __future__ import annotations

import pytest

from wardrobe.config import Settings
from wardrobe.domain.garments import TemplateCatalog
from wardrobe.domain.looks import MaterialPlan, OutfitMode, OutfitPlan
from wardrobe.errors import ProviderError
from wardrobe.providers import (
    MockGarmentProvider,
    TemplateGarmentProvider,
    create_provider,
    provider_for_mode,
)
from wardrobe.providers.meshy import _parse_task as parse_meshy
from wardrobe.providers.meshy import _submitted_id as meshy_id
from wardrobe.providers.remote import RemoteTask, dig
from wardrobe.providers.tripo import _parse_task as parse_tripo


@pytest.fixture
def plan() -> OutfitPlan:
    return OutfitPlan(
        name="Black A-line",
        category="dress",
        templateId="dress-a-line-v1",
        silhouette="a-line",
        hem="knee",
        material=MaterialPlan(colorName="black", fabric="satin"),
    )


# ----------------------------------------------------------------------
# selection
# ----------------------------------------------------------------------
def test_template_provider_is_the_default(settings: Settings, template_catalog: TemplateCatalog):
    assert isinstance(provider_for_mode(OutfitMode.AUTO, settings, template_catalog), TemplateGarmentProvider)
    assert isinstance(
        provider_for_mode(OutfitMode.TEMPLATE, settings, template_catalog), TemplateGarmentProvider
    )


def test_mock_provider_is_selectable(settings: Settings, template_catalog: TemplateCatalog):
    mocked = settings.model_copy(update={"wardrobe_provider": "mock"})
    assert isinstance(provider_for_mode(OutfitMode.AUTO, mocked, template_catalog), MockGarmentProvider)


def test_generated_mode_needs_an_ai_provider(settings: Settings, template_catalog: TemplateCatalog):
    with pytest.raises(ProviderError, match="requires WARDROBE_PROVIDER"):
        provider_for_mode(OutfitMode.GENERATED, settings, template_catalog)


def test_unknown_provider_is_an_error(settings: Settings, template_catalog: TemplateCatalog):
    with pytest.raises(ProviderError, match="unknown garment provider"):
        create_provider("imaginary", settings, template_catalog)


def test_remote_providers_require_a_key(settings: Settings, template_catalog: TemplateCatalog):
    for name in ("meshy", "tripo"):
        with pytest.raises(ProviderError, match="no API key"):
            create_provider(name, settings, template_catalog)


# ----------------------------------------------------------------------
# template provider
# ----------------------------------------------------------------------
async def test_template_provider_resolves_the_template(template_catalog: TemplateCatalog, plan: OutfitPlan):
    provider = TemplateGarmentProvider(template_catalog)
    artifact = await provider.create(plan, template=template_catalog.get("dress-a-line-v1"))

    assert artifact.source == "template"
    assert artifact.template_id == "dress-a-line-v1"
    assert artifact.coverage
    assert artifact.metadata["bodyClearanceMm"] > 0
    assert not artifact.metadata.get("requiresBlender")


async def test_template_provider_is_deterministic(template_catalog: TemplateCatalog, plan: OutfitPlan):
    provider = TemplateGarmentProvider(template_catalog)
    first = await provider.create(plan)
    second = await provider.create(plan)
    assert first.id == second.id


async def test_template_provider_falls_back_within_the_category(template_catalog: TemplateCatalog):
    provider = TemplateGarmentProvider(template_catalog)
    artifact = await provider.create(OutfitPlan(name="X", category="skirt"))
    assert template_catalog.get(artifact.template_id).category == "skirt"


async def test_template_provider_rejects_an_unknown_category(template_catalog: TemplateCatalog):
    from wardrobe.errors import PlanningError

    provider = TemplateGarmentProvider(template_catalog)
    with pytest.raises(PlanningError, match="no template available"):
        await provider.create(OutfitPlan(name="X", category="spacesuit"))


# ----------------------------------------------------------------------
# shared remote helpers
# ----------------------------------------------------------------------
def test_dig_finds_the_first_matching_path():
    payload = {"data": {"output": {"pbr_model": "https://example/model.glb"}}}
    assert dig(payload, ("output", "model"), ("data", "output", "pbr_model")) == "https://example/model.glb"
    assert dig(payload, ("nope",), default="fallback") == "fallback"


# ----------------------------------------------------------------------
# Meshy response shapes
# ----------------------------------------------------------------------
def test_meshy_submit_response_shapes():
    assert meshy_id({"result": "task-123"}) == "task-123"
    assert meshy_id({"id": "task-456"}) == "task-456"
    assert meshy_id({"result": {"id": "task-789"}}) == "task-789"


def test_meshy_submit_without_an_id_is_an_error():
    with pytest.raises(ProviderError, match="no task id"):
        meshy_id({"unexpected": True})


def test_meshy_success_payload():
    task = parse_meshy(
        {
            "id": "task-1",
            "status": "SUCCEEDED",
            "progress": 100,
            "model_urls": {"glb": "https://example/model.glb", "fbx": "https://example/model.fbx"},
        }
    )
    assert isinstance(task, RemoteTask)
    assert task.status == "SUCCEEDED"
    assert task.model_url == "https://example/model.glb"


def test_meshy_wrapped_result_payload():
    task = parse_meshy({"result": {"id": "task-2", "status": "IN_PROGRESS", "progress": 42}})
    assert task.task_id == "task-2"
    assert task.progress == 42.0
    assert task.model_url is None


# ----------------------------------------------------------------------
# Tripo response shapes
# ----------------------------------------------------------------------
def test_tripo_success_payload():
    task = parse_tripo(
        {
            "code": 0,
            "data": {
                "task_id": "trip-1",
                "status": "success",
                "progress": 100,
                "output": {"pbr_model": "https://example/model.glb"},
            },
        }
    )
    assert task.task_id == "trip-1"
    assert task.status == "success"
    assert task.model_url == "https://example/model.glb"


def test_tripo_nested_url_object():
    task = parse_tripo(
        {"code": 0, "data": {"task_id": "trip-2", "status": "success",
                             "result": {"pbr_model": {"url": "https://example/m.glb"}}}}
    )
    assert task.model_url == "https://example/m.glb"


def test_tripo_error_code_is_surfaced():
    with pytest.raises(ProviderError, match="code 2000"):
        parse_tripo({"code": 2000, "message": "insufficient balance"})


# ----------------------------------------------------------------------
# prompts
# ----------------------------------------------------------------------
def test_generated_prompts_ask_for_a_garment_only(settings: Settings, plan: OutfitPlan):
    """A generated mesh containing a body could never be fitted to an avatar."""
    from wardrobe.providers.meshy import MeshyProvider
    from wardrobe.providers.tripo import TripoProvider

    keyed = settings.model_copy(update={"meshy_api_key": "test", "tripo_api_key": "test"})
    for provider in (MeshyProvider(keyed), TripoProvider(keyed)):
        prompt = provider.build_prompt(plan)
        assert "dress" in prompt
        assert "black" in prompt
        assert "no person" in prompt or "no character" in prompt
        assert "mannequin" in prompt


# ----------------------------------------------------------------------
# mock provider
# ----------------------------------------------------------------------
async def test_mock_provider_records_calls(plan: OutfitPlan):
    provider = MockGarmentProvider()
    artifact = await provider.create(plan)
    assert artifact.source == "mock"
    assert provider.calls == [plan]
