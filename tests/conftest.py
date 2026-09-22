"""Shared fixtures.

Every avatar used in the tests is generated, not shipped: the fixtures are
built from :mod:`wardrobe.vrm.build`, so the suite needs no third-party VRM
binaries and no licence exceptions.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from wardrobe.config import Settings
from wardrobe.domain.garments import TemplateCatalog
from wardrobe.pipeline.orchestrator import Orchestrator
from wardrobe.queue.jobs import AsyncioJobQueue
from wardrobe.storage.database import InMemoryJobRepository, InMemoryWardrobeRepository
from wardrobe.storage.object_store import LocalObjectStore
from wardrobe.vrm.build import CALIBRATION_BODIES, BodyProportions, build_vrm

REPO_ROOT = Path(__file__).resolve().parent.parent
TEMPLATE_ROOT = REPO_ROOT / "assets" / "garment_templates"


@pytest.fixture(scope="session")
def template_catalog() -> TemplateCatalog:
    return TemplateCatalog.from_directory(TEMPLATE_ROOT)


@pytest.fixture(scope="session")
def calibration_bodies() -> tuple[BodyProportions, ...]:
    return CALIBRATION_BODIES


@pytest.fixture(scope="session")
def vrm_bytes() -> bytes:
    """A VRM 1.0 avatar of medium proportions."""
    return build_vrm(CALIBRATION_BODIES[1], spec="VRM1")


@pytest.fixture(scope="session")
def vrm0_bytes() -> bytes:
    """A VRM 0.x avatar of medium proportions."""
    return build_vrm(CALIBRATION_BODIES[1], spec="VRM0")


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(
        wardrobe_storage_root=str(tmp_path / "storage"),
        wardrobe_job_backend="memory",
        wardrobe_engine="native",
        wardrobe_provider="template",
        wardrobe_template_root=str(TEMPLATE_ROOT),
        strict_licensing=True,
        public_base_url="",
    )


@pytest.fixture
def store(settings: Settings) -> LocalObjectStore:
    return LocalObjectStore(settings.storage_root_path, settings)


@pytest.fixture
def orchestrator(settings: Settings, store: LocalObjectStore, template_catalog: TemplateCatalog):
    return Orchestrator(
        settings=settings,
        store=store,
        jobs=InMemoryJobRepository(),
        wardrobes=InMemoryWardrobeRepository(),
        queue=AsyncioJobQueue(concurrency=1),
        catalog=template_catalog,
    )


@pytest.fixture
async def stored_avatar(store: LocalObjectStore, vrm_bytes: bytes) -> str:
    """Put the medium calibration avatar in storage and return its key."""
    key = "sources/test-avatar.vrm"
    await store.put(key, vrm_bytes)
    return key


def job_request(storage_key: str, prompt: str, **options) -> dict:
    """Build a CreateJobRequest payload for the given source and prompt."""
    return {
        "avatar": {"storageKey": storage_key, "avatarId": options.pop("avatar_id", "test-avatar")},
        "outfit": {
            "prompt": prompt,
            "mode": options.pop("mode", "template"),
            "templateId": options.pop("template_id", None),
        },
        "options": {
            "renderPreview": options.pop("render_preview", False),
            "engine": options.pop("engine", "native"),
            **options,
        },
    }
