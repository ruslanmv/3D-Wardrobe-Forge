from fastapi import FastAPI

from apps.api.routes.jobs import router as jobs_router

app = FastAPI(
    title="3D Wardrobe Forge",
    version="0.1.0",
    description="Generate fitted wardrobe looks for VRM avatars.",
)

app.include_router(jobs_router, prefix="/v1")


@app.get("/health")
def health():
    return {"ok": True, "service": "3D-Wardrobe-Forge", "version": "0.1.0"}
