"""3D Wardrobe Forge HTTP API."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from apps.api.dependencies import require_api_key
from apps.api.routes.avatars import router as avatars_router
from apps.api.routes.generate import router as generate_router
from apps.api.routes.jobs import router as jobs_router
from apps.api.routes.looks import router as looks_router
from apps.api.routes.wardrobes import router as wardrobes_router
from wardrobe import __version__
from wardrobe.config import get_settings
from wardrobe.engines import BlenderEngine
from wardrobe.pipeline.orchestrator import get_orchestrator

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    settings.validate_deployment()
    logging.basicConfig(level=settings.app_log_level.upper())

    orchestrator = get_orchestrator()
    await orchestrator.start()
    app.state.orchestrator = orchestrator
    try:
        yield
    finally:
        await orchestrator.stop()


app = FastAPI(
    title="3D Wardrobe Forge",
    version=__version__,
    description=(
        "Give it a VRM avatar and an outfit request; get the same character "
        "wearing a new outfit as a validated VRM, with a preview and a fit report."
    ),
    lifespan=lifespan,
)

# The browser client is served from a different origin to the forge.
settings = get_settings()
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.wardrobe_allowed_origins,
    allow_credentials=False,
    allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
    allow_headers=["*"],
)

api_dependencies = [Depends(require_api_key)]
app.include_router(jobs_router, prefix="/v1", dependencies=api_dependencies)
app.include_router(avatars_router, prefix="/v1", dependencies=api_dependencies)
app.include_router(looks_router, prefix="/v1", dependencies=api_dependencies)
app.include_router(wardrobes_router, prefix="/v1", dependencies=api_dependencies)
app.include_router(generate_router, prefix="/v1", dependencies=api_dependencies)


@app.get("/health", tags=["service"])
def health() -> dict:
    return {"ok": True, "service": "3D-Wardrobe-Forge", "version": __version__}


@app.get("/v1/capabilities", tags=["service"])
def capabilities() -> dict:
    """What this deployment can actually do, for the client to adapt to."""
    settings = get_settings()
    orchestrator = get_orchestrator()
    blender = BlenderEngine.available(settings)

    return {
        "version": __version__,
        "engines": {
            "native": True,
            "blender": blender,
            "default": settings.wardrobe_engine,
            "bodyMasking": blender,
            "generatedMeshes": blender,
        },
        "provider": settings.wardrobe_provider,
        "templates": len(orchestrator.catalog),
        "categories": sorted({template.category for template in orchestrator.catalog}),
        "outputVersions": ["source", "VRM0", "VRM1"],
        "maxAvatarBytes": settings.max_avatar_bytes,
        "strictLicensing": settings.strict_licensing,
    }


__all__ = ["app"]
