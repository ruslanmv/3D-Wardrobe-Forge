from pydantic import BaseModel, Field


class WardrobeLook(BaseModel):
    id: str
    name: str
    type: str = "vrmVariant"
    vrm_url: str
    preview_url: str | None = None


class WardrobeManifest(BaseModel):
    schema_version: int = 1
    avatar_id: str
    source_hash: str | None = None
    looks: list[WardrobeLook] = Field(default_factory=list)
