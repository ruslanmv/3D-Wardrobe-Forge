"""Wardrobe manifests — the per-avatar list of looks the chatbot consumes.

The manifest deliberately mirrors 3D-Avatar-Chatbot's ``avatars.json`` item
shape (``name`` / ``file`` / ``format``), so a wardrobe can be merged straight
into that viewer's avatar list without a translation layer.
"""

from __future__ import annotations

from datetime import UTC, datetime

from pydantic import BaseModel, ConfigDict, Field

SCHEMA_VERSION = 1


class WardrobeLook(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: str
    name: str
    type: str = "vrmVariant"
    vrm_url: str | None = Field(default=None, alias="vrmUrl")
    preview_url: str | None = Field(default=None, alias="previewUrl")
    prompt: str | None = None
    created_at: datetime | None = Field(default=None, alias="createdAt")
    fit_passed: bool | None = Field(default=None, alias="fitPassed")

    def to_avatar_item(self) -> dict:
        """Render as a 3D-Avatar-Chatbot ``avatars.json`` item."""
        return {
            "name": self.name,
            "file": (self.vrm_url or "").rsplit("/", 1)[-1],
            "url": self.vrm_url,
            "format": "vrm",
            "source": "3D-Wardrobe-Forge",
            "features": ["lipsync", "emotions", "gaze", "blink"],
            "notes": self.prompt,
        }


class WardrobeManifest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    schema_version: int = Field(default=SCHEMA_VERSION, alias="schemaVersion")
    avatar_id: str = Field(alias="avatarId")
    source_hash: str | None = Field(default=None, alias="sourceHash")
    source_name: str | None = Field(default=None, alias="sourceName")
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC), alias="updatedAt")
    looks: list[WardrobeLook] = Field(default_factory=list)

    @classmethod
    def empty(cls, avatar_id: str, *, source_hash: str | None = None, source_name: str | None = None
              ) -> WardrobeManifest:
        manifest = cls(avatarId=avatar_id, sourceHash=source_hash, sourceName=source_name)
        manifest.looks.append(
            WardrobeLook(id="original", name=source_name or "Everyday", type="source")
        )
        return manifest

    def upsert(self, look: WardrobeLook) -> WardrobeManifest:
        """Add a look, replacing any existing entry with the same id."""
        self.looks = [existing for existing in self.looks if existing.id != look.id]
        self.looks.append(look)
        self.updated_at = datetime.now(UTC)
        return self

    def get(self, look_id: str) -> WardrobeLook | None:
        return next((look for look in self.looks if look.id == look_id), None)

    def remove(self, look_id: str) -> bool:
        before = len(self.looks)
        self.looks = [look for look in self.looks if look.id != look_id or look.type == "source"]
        changed = len(self.looks) != before
        if changed:
            self.updated_at = datetime.now(UTC)
        return changed

    def to_avatar_manifest(self, base_path: str = "") -> dict:
        """Render the whole wardrobe as a chatbot-compatible avatar manifest."""
        return {
            "basePath": base_path.rstrip("/"),
            "items": [look.to_avatar_item() for look in self.looks if look.vrm_url],
        }


__all__ = ["SCHEMA_VERSION", "WardrobeLook", "WardrobeManifest"]
