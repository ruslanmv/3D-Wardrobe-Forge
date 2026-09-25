from __future__ import annotations

import pytest

from wardrobe.config import REPO_ROOT, Settings


def test_local_profile_keeps_zero_config_development():
    Settings().validate_deployment()


def test_local_storage_default_is_writable_project_directory(monkeypatch) -> None:
    monkeypatch.delenv("WARDROBE_STORAGE_ROOT", raising=False)
    settings = Settings(_env_file=None)
    assert settings.storage_root_path == REPO_ROOT / ".wardrobe"


def test_production_profile_rejects_ephemeral_unauthenticated_defaults():
    settings = Settings(wardrobe_profile="production")
    with pytest.raises(ValueError, match="production requires"):
        settings.validate_deployment()


def test_production_profile_accepts_durable_authenticated_configuration():
    settings = Settings(
        wardrobe_profile="production",
        wardrobe_job_backend="redis://redis:6379/0",
        wardrobe_storage_backend="s3",
        s3_bucket="wardrobe",
        wardrobe_auth_mode="api_key",
        wardrobe_api_key="secret",
        wardrobe_allowed_origins=["https://yourfriend.online"],
    )
    settings.validate_deployment()
