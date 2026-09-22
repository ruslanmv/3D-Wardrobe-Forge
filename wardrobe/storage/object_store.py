"""Artifact storage: generated VRMs, previews, fit reports and manifests."""

from __future__ import annotations

import asyncio
import shutil
from abc import ABC, abstractmethod
from pathlib import Path

from wardrobe.config import Settings
from wardrobe.policy.file_safety import validate_storage_key

CONTENT_TYPES = {
    ".vrm": "model/gltf-binary",
    ".glb": "model/gltf-binary",
    ".json": "application/json",
    ".webp": "image/webp",
    ".png": "image/png",
}


def content_type_for(key: str) -> str:
    return CONTENT_TYPES.get(Path(key).suffix.lower(), "application/octet-stream")


class ObjectStore(ABC):
    """Minimal async object storage interface."""

    @abstractmethod
    async def put(self, key: str, data: bytes, *, content_type: str | None = None) -> str: ...

    @abstractmethod
    async def get(self, key: str) -> bytes: ...

    @abstractmethod
    async def delete(self, key: str) -> bool: ...

    @abstractmethod
    async def exists(self, key: str) -> bool: ...

    @abstractmethod
    def url_for(self, key: str) -> str: ...

    async def put_path(self, key: str, path: str | Path, *, content_type: str | None = None) -> str:
        data = await asyncio.to_thread(Path(path).read_bytes)
        return await self.put(key, data, content_type=content_type)


class LocalObjectStore(ObjectStore):
    """Filesystem-backed store; the default for development and CLI runs."""

    def __init__(self, root: str | Path, settings: Settings | None = None) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self._settings = settings

    def _path(self, key: str) -> Path:
        validate_storage_key(key)
        path = (self.root / key).resolve()
        if not str(path).startswith(str(self.root.resolve())):
            raise ValueError(f"storage key escapes the storage root: {key!r}")
        return path

    async def put(self, key: str, data: bytes, *, content_type: str | None = None) -> str:
        path = self._path(key)

        def _write() -> None:
            path.parent.mkdir(parents=True, exist_ok=True)
            temporary = path.with_suffix(path.suffix + ".part")
            temporary.write_bytes(data)
            temporary.replace(path)  # atomic publish

        await asyncio.to_thread(_write)
        return self.url_for(key)

    async def get(self, key: str) -> bytes:
        return await asyncio.to_thread(self._path(key).read_bytes)

    async def delete(self, key: str) -> bool:
        path = self._path(key)

        def _delete() -> bool:
            if path.is_dir():
                shutil.rmtree(path, ignore_errors=True)
                return True
            if path.exists():
                path.unlink()
                return True
            return False

        return await asyncio.to_thread(_delete)

    async def exists(self, key: str) -> bool:
        return await asyncio.to_thread(self._path(key).exists)

    def url_for(self, key: str) -> str:
        if self._settings is not None:
            return self._settings.artifact_url(key)
        return f"/v1/assets/{key}"

    def local_path(self, key: str) -> Path:
        """Escape hatch for the Blender worker, which needs real file paths."""
        return self._path(key)


class S3ObjectStore(ObjectStore):
    """S3-compatible store (AWS S3, MinIO, R2).

    ``boto3`` is an optional dependency: install the ``s3`` extra to use this.
    """

    def __init__(self, settings: Settings) -> None:
        try:
            import boto3  # noqa: PLC0415 - optional dependency, imported on use
        except ImportError as exc:  # pragma: no cover - depends on the extra
            raise RuntimeError(
                "S3 storage requires boto3; install with: pip install '3d-wardrobe-forge[s3]'"
            ) from exc

        if not settings.s3_bucket:
            raise RuntimeError("S3_BUCKET must be set when WARDROBE_STORAGE_BACKEND=s3")

        self.bucket = settings.s3_bucket
        self.settings = settings
        self._client = boto3.client(
            "s3",
            endpoint_url=settings.s3_endpoint or None,
            region_name=settings.s3_region,
            aws_access_key_id=settings.s3_access_key_id or None,
            aws_secret_access_key=settings.s3_secret_access_key or None,
        )

    async def put(self, key: str, data: bytes, *, content_type: str | None = None) -> str:
        validate_storage_key(key)
        await asyncio.to_thread(
            self._client.put_object,
            Bucket=self.bucket,
            Key=key,
            Body=data,
            ContentType=content_type or content_type_for(key),
        )
        return self.url_for(key)

    async def get(self, key: str) -> bytes:
        validate_storage_key(key)
        response = await asyncio.to_thread(self._client.get_object, Bucket=self.bucket, Key=key)
        return await asyncio.to_thread(response["Body"].read)

    async def delete(self, key: str) -> bool:
        validate_storage_key(key)
        await asyncio.to_thread(self._client.delete_object, Bucket=self.bucket, Key=key)
        return True

    async def exists(self, key: str) -> bool:
        validate_storage_key(key)
        try:
            await asyncio.to_thread(self._client.head_object, Bucket=self.bucket, Key=key)
            return True
        except Exception:
            return False

    def url_for(self, key: str) -> str:
        """Pre-signed URL so generated avatars are never world-readable."""
        return self._client.generate_presigned_url(
            "get_object",
            Params={"Bucket": self.bucket, "Key": key},
            ExpiresIn=self.settings.s3_signed_url_ttl_s,
        )


def create_object_store(settings: Settings) -> ObjectStore:
    backend = settings.wardrobe_storage_backend.lower()
    if backend == "local":
        return LocalObjectStore(settings.storage_root_path, settings)
    if backend == "s3":
        return S3ObjectStore(settings)
    raise ValueError(f"unknown storage backend: {backend!r}")


__all__ = [
    "ObjectStore",
    "LocalObjectStore",
    "S3ObjectStore",
    "create_object_store",
    "content_type_for",
]
