"""Single source of configuration for the API, the worker and the CLI."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", env_prefix="")

    # -- service ---------------------------------------------------------
    app_env: str = "development"
    app_host: str = "0.0.0.0"
    app_port: int = 8080
    app_log_level: str = "INFO"
    #: Public base URL used when minting artifact URLs. Empty = relative paths.
    public_base_url: str = ""
    #: local | space | production. Production rejects unsafe ephemeral settings.
    wardrobe_profile: str = "local"
    #: Static delivery target used by the CLI.
    wardrobe_target: str = "yourfriend"
    #: Browser origins allowed to call the API. Keep wildcard only for local/demo use.
    wardrobe_allowed_origins: list[str] = Field(default_factory=lambda: ["*"])
    #: none | api_key. Hosted production deployments should use api_key or an upstream gateway.
    wardrobe_auth_mode: str = "none"
    wardrobe_api_key: str = ""
    #: Signs the operator in to the Studio's account menu (apps/api/admin.py), where
    #: an adult declaration can be made per avatar for that session only. Empty: no
    #: admin, and the Studio offers no sign-in. Set it as a secret, never in a file.
    wardrobe_admin_password: str = ""
    #: The user name that goes with it on the Studio's log-in form.
    wardrobe_admin_username: str = "admin"
    #: How long an admin session lasts before it signs itself out.
    wardrobe_admin_session_hours: float = 8.0

    # -- pipeline --------------------------------------------------------
    #: auto picks blender when available and falls back to the native engine.
    wardrobe_engine: str = "auto"
    wardrobe_provider: str = "template"
    wardrobe_job_backend: str = "memory"
    wardrobe_job_concurrency: int = 2
    wardrobe_job_timeout_s: int = 900
    #: native | web | auto — how hosiery looks' previews are rendered (wardrobe.hosiery.previews).
    #: Every other look keeps the native preview it always had.
    wardrobe_preview_backend: str = "native"

    # -- storage ---------------------------------------------------------
    wardrobe_storage_backend: str = "local"
    # Keep the zero-configuration development server writable for unprivileged
    # users. Container deployments override this with /data/wardrobe.
    wardrobe_storage_root: str = str(REPO_ROOT / ".wardrobe")
    wardrobe_database_url: str = ""

    s3_endpoint: str = ""
    s3_bucket: str = ""
    s3_region: str = "us-east-1"
    s3_access_key_id: str = ""
    s3_secret_access_key: str = ""
    s3_signed_url_ttl_s: int = 3600

    # -- assets ----------------------------------------------------------
    wardrobe_template_root: str = str(REPO_ROOT / "assets" / "garment_templates")
    wardrobe_fixture_root: str = str(REPO_ROOT / "assets" / "fixtures")
    #: The Studio's avatar library: models.json plus the VRMs tools/fetch_library.py verified.
    wardrobe_library_root: str = str(REPO_ROOT / "assets" / "library")

    # -- safety ----------------------------------------------------------
    max_avatar_bytes: int = 128 * 1024 * 1024
    max_output_bytes: int = 256 * 1024 * 1024
    fetch_timeout_s: float = 60.0
    #: Only these URL schemes may be fetched for a source avatar.
    allowed_source_schemes: list[str] = Field(default_factory=lambda: ["https"])
    #: Optional host allowlist. Empty means "any public host".
    allowed_source_hosts: list[str] = Field(default_factory=list)
    #: Refuse to fetch from private/loopback/link-local addresses (SSRF guard).
    block_private_networks: bool = True
    #: Treat unknown usage terms as requiring an explicit caller attestation.
    strict_licensing: bool = True
    #: Delete the fetched source VRM once the job finishes.
    delete_source_after_job: bool = True

    # -- providers -------------------------------------------------------
    meshy_api_key: str = ""
    meshy_base_url: str = "https://api.meshy.ai"
    tripo_api_key: str = ""
    tripo_base_url: str = "https://api.tripo3d.ai"
    provider_timeout_s: float = 600.0

    # -- blender ---------------------------------------------------------
    blender_bin: str = "blender"
    blender_timeout_s: int = 900
    wardrobe_blender_script: str = str(REPO_ROOT / "worker" / "blender" / "run_pipeline.py")

    # ------------------------------------------------------------------
    @property
    def storage_root_path(self) -> Path:
        return Path(self.wardrobe_storage_root)

    @property
    def template_root_path(self) -> Path:
        return Path(self.wardrobe_template_root)

    def artifact_url(self, key: str) -> str:
        base = self.public_base_url.rstrip("/")
        return f"{base}/v1/assets/{key}" if base else f"/v1/assets/{key}"

    def validate_deployment(self) -> None:
        """Fail fast when a named deployment profile is internally unsafe."""
        profile = self.wardrobe_profile.lower()
        if profile not in {"local", "space", "production"}:
            raise ValueError(f"unknown WARDROBE_PROFILE: {self.wardrobe_profile!r}")

        if self.wardrobe_auth_mode not in {"none", "api_key"}:
            raise ValueError(f"unknown WARDROBE_AUTH_MODE: {self.wardrobe_auth_mode!r}")
        if self.wardrobe_auth_mode == "api_key" and not self.wardrobe_api_key:
            raise ValueError("WARDROBE_API_KEY is required when WARDROBE_AUTH_MODE=api_key")

        if profile == "production":
            problems: list[str] = []
            if self.wardrobe_job_backend.lower() in {"memory", "asyncio"}:
                problems.append("production requires Redis-backed jobs")
            if self.wardrobe_storage_backend.lower() == "local":
                problems.append("production requires durable object storage")
            if self.wardrobe_auth_mode == "none":
                problems.append("production requires API authentication or a configured gateway")
            if "*" in self.wardrobe_allowed_origins:
                problems.append("production CORS must not allow every origin")
            if problems:
                raise ValueError("; ".join(problems))


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


settings = get_settings()

__all__ = ["Settings", "get_settings", "settings", "REPO_ROOT"]
